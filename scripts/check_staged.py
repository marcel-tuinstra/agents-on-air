"""Check the exact blobs in Git's index before committing."""
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
JS_SUFFIXES = {'.js', '.cjs', '.mjs'}


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def check_blob(path, contents):
    suffix = Path(path).suffix.lower()
    if suffix == '.py':
        ast.parse(contents, filename=path)
    elif suffix == '.json':
        json.loads(contents)
    elif suffix in JS_SUFFIXES:
        command = ['node', '--check']
        if suffix == '.mjs':
            command.append('--input-type=module')
        result = subprocess.run(command, input=contents, capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr.decode(errors='replace').strip() or 'node --check failed')


def check_staged():
    whitespace = subprocess.run(['git', 'diff', '--cached', '--check'], cwd=ROOT,
                                capture_output=True, text=True)
    if whitespace.returncode:
        raise ValueError(whitespace.stdout.strip() or whitespace.stderr.strip())
    names = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').split(b'\0')
    for raw in names:
        if not raw:
            continue
        path = raw.decode('utf-8', 'surrogateescape')
        suffix = Path(path).suffix.lower()
        if suffix not in {'.py', '.json', *JS_SUFFIXES}:
            continue
        try:
            # Git's :path syntax reads the staged blob, including for partial staging.
            contents = git('show', ':' + path)
            check_blob(path, contents)
        except (SyntaxError, UnicodeError, ValueError, subprocess.CalledProcessError) as error:
            raise ValueError(f'{path}: {error}') from error


if __name__ == '__main__':
    try:
        check_staged()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'pre-commit: {error}', file=sys.stderr)
        sys.exit(1)
