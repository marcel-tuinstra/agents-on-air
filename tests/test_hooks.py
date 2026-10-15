"""Git hook checks use mocked plumbing; no extra checkout or index is created."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_staged
import install_hooks
import pre_push
import verify
from build import build
from package import package
import zipfile


class StagedChecks(unittest.TestCase):
    def test_hook_without_python_fails_explicitly(self):
        shell = shutil.which('sh')
        if shell is None:
            self.skipTest('POSIX shell unavailable')
        hook = Path(__file__).resolve().parents[1] / '.githooks' / 'pre-commit'
        with tempfile.TemporaryDirectory() as empty_path:
            result = subprocess.run([shell, str(hook)], cwd=hook.parents[1],
                                    env={**os.environ, 'PATH': empty_path},
                                    capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python 3.9+ is required', result.stderr)

    def test_invalid_staged_python_json_and_javascript_fail(self):
        for name, content in [('broken.py', b'def broken(:\n'),
                              ('broken.json', b'{bad'),
                              ('broken.js', b'function ( {')]:
            with self.subTest(name=name), self.assertRaises((SyntaxError, ValueError)):
                check_staged.check_blob(name, content)

    def test_valid_staged_module_uses_module_parser(self):
        module = b'import { readFileSync } from "node:fs";\nexport const value = 1;\n'
        check_staged.check_blob('module.mjs', module)

    def test_partial_staging_checks_index_blob_not_worktree_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / 'partial.py'
            worktree.write_text('def broken(:\n')
            def staged_git(*args):
                if 'diff' in args:
                    return b'partial.py\0'
                if 'show' in args:
                    return b'answer = 42\n'
                raise AssertionError(args)
            clean = SimpleNamespace(returncode=0, stdout='', stderr='')
            with patch.object(check_staged, 'git', side_effect=staged_git) as source, \
                 patch.object(check_staged.subprocess, 'run', return_value=clean):
                check_staged.check_staged()
            self.assertEqual(source.call_args_list[-1].args, ('show', ':partial.py'))
            self.assertIn('broken', worktree.read_text())

    def test_missing_node_fails_javascript_check(self):
        with patch.object(check_staged.subprocess, 'run', side_effect=FileNotFoundError('node')):
            with self.assertRaises(FileNotFoundError):
                check_staged.check_blob('app.js', b'const ok = true;\n')

    def test_staged_whitespace_blocks_commit(self):
        bad = SimpleNamespace(returncode=2, stdout='app.py:1: trailing whitespace', stderr='')
        with patch.object(check_staged.subprocess, 'run', return_value=bad):
            with self.assertRaisesRegex(ValueError, 'trailing whitespace'):
                check_staged.check_staged()


class PushChecks(unittest.TestCase):
    HEAD = 'a' * 40
    OLD = 'b' * 40

    def line(self, sha=None):
        return f'refs/heads/main {sha or self.HEAD} refs/heads/main {self.OLD}\n'

    def test_non_head_push_is_rejected(self):
        with patch.object(pre_push, 'git', side_effect=[self.HEAD, self.OLD]):
            with self.assertRaisesRegex(ValueError, 'not HEAD'):
                pre_push.check_push([self.line(self.OLD)])

    def test_dirty_checkout_is_rejected(self):
        with patch.object(pre_push, 'git', side_effect=[self.HEAD, self.HEAD,
                                                      self.HEAD, ' M frontend/app.js']):
            with self.assertRaisesRegex(ValueError, 'differs from HEAD'):
                pre_push.check_push([self.line()])

    def test_submitted_sha_must_still_be_head(self):
        with patch.object(pre_push, 'git', side_effect=[self.HEAD, self.HEAD, self.OLD]):
            with self.assertRaisesRegex(ValueError, 'queued at'):
                pre_push.check_push([self.line(self.OLD)])

    def test_clean_head_and_ref_deletion(self):
        with patch.object(pre_push, 'git', side_effect=[self.HEAD, self.HEAD, self.HEAD, '']):
            self.assertTrue(pre_push.check_push([self.line()]))
        deletion = self.line('0' * 40)
        with patch.object(pre_push, 'git', return_value=self.HEAD) as git:
            self.assertFalse(pre_push.check_push([deletion]))
            git.assert_called_once_with('rev-parse', 'HEAD')


class InstallerChecks(unittest.TestCase):
    def fixture(self, temporary):
        root = Path(temporary).resolve()
        (root / '.githooks').mkdir()
        for name in ('pre-commit', 'pre-push'):
            (root / '.githooks' / name).write_text('#!/bin/sh\n')
        (root / '.git' / 'hooks').mkdir(parents=True)
        return root

    def reply(self, stdout='', returncode=0):
        return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)

    def test_conflicting_path_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            responses = [self.reply(str(root)), self.reply('other-hooks')]
            with patch.object(install_hooks, 'ROOT', root), \
                 patch.object(install_hooks, 'git', side_effect=responses) as git:
                with self.assertRaisesRegex(ValueError, 'Existing core.hooksPath'):
                    install_hooks.install()
                self.assertEqual(git.call_count, 2)

    def test_active_default_hook_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            (root / '.git' / 'hooks' / 'pre-commit').write_text('#!/bin/sh\n')
            responses = [self.reply(str(root)), self.reply(returncode=1),
                         self.reply(returncode=1),
                         self.reply(str(root / '.git' / 'hooks'))]
            with patch.object(install_hooks, 'ROOT', root), \
                 patch.object(install_hooks, 'git', side_effect=responses) as git:
                with self.assertRaisesRegex(ValueError, 'Existing default Git hooks'):
                    install_hooks.install()
                self.assertEqual(git.call_count, 4)

    def test_inherited_hook_path_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            responses = [self.reply(str(root)), self.reply(returncode=1),
                         self.reply('global-hooks')]
            with patch.object(install_hooks, 'ROOT', root), \
                 patch.object(install_hooks, 'git', side_effect=responses) as git:
                with self.assertRaisesRegex(ValueError, 'inherited core.hooksPath'):
                    install_hooks.install()
                self.assertEqual(git.call_count, 3)

    def test_installs_once_then_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fixture(tmp)
            responses = [self.reply(str(root)), self.reply(returncode=1),
                         self.reply(returncode=1),
                         self.reply(str(root / '.git' / 'hooks')), self.reply(),
                         self.reply(str(root)), self.reply('.githooks')]
            with patch.object(install_hooks, 'ROOT', root), \
                 patch.object(install_hooks, 'git', side_effect=responses) as git:
                install_hooks.install()
                install_hooks.install()
            self.assertEqual(sum(call.args[:3] == ('config', '--local', 'core.hooksPath')
                                 for call in git.call_args_list), 1)


class VerificationPaths(unittest.TestCase):
    def test_text_line_endings_normalize_but_binary_remains_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text_file = folder / 'page.html'
            text_file.write_bytes(b'a\r\nb\r\n')
            self.assertEqual(verify.comparable_bytes(text_file), b'a\nb\n')
            binary_file = folder / 'image.png'
            binary_file.write_bytes(b'a\r\nb')
            self.assertEqual(verify.comparable_bytes(binary_file), b'a\r\nb')

    def test_build_uses_temp_output_and_package_uses_same_assets(self):
        with patch.object(verify, 'build') as build, \
             patch.object(verify, 'compare_generated') as compare, \
             patch.object(verify, 'command'), \
             patch.object(verify, 'package') as package:
            verify.verify()
        generated = build.call_args.args[0]
        self.assertNotEqual(generated, verify.ROOT / 'static')
        self.assertEqual(compare.call_args.args[0], generated)
        self.assertEqual(package.call_args.kwargs['static_source'], generated)
        self.assertNotEqual(package.call_args.args[0].parent, verify.ROOT)

    def test_real_build_and_zip_leave_static_files_untouched(self):
        static = verify.ROOT / 'static'
        before = {path.relative_to(static): (path.stat().st_size, path.stat().st_mtime_ns)
                  for path in static.rglob('*') if path.is_file()}
        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / 'static'
            target = Path(tmp) / 'release.zip'
            build(generated)
            package(target, static_source=generated)
            with zipfile.ZipFile(target) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('agents-on-air/static/index.html', archive.namelist())
                for name in ('agents-on-air/.gitattributes',
                             'agents-on-air/.githooks/pre-commit',
                             'agents-on-air/.githooks/pre-push',
                             'agents-on-air/scripts/verify.py',
                             'agents-on-air/scripts/install_hooks.py'):
                    self.assertIn(name, archive.namelist())
                if os.name != 'nt':
                    for name in ('agents-on-air/.githooks/pre-commit',
                                 'agents-on-air/.githooks/pre-push'):
                        self.assertTrue((archive.getinfo(name).external_attr >> 16) & 0o111)
        after = {path.relative_to(static): (path.stat().st_size, path.stat().st_mtime_ns)
                 for path in static.rglob('*') if path.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
