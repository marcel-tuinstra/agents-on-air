"""Run the same offline source, build, test and archive checks locally and in CI."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build import build  # noqa: E402
from package import package  # noqa: E402


def command(*args):
    print('+', ' '.join(str(arg) for arg in args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def files_under(folder):
    return {path.relative_to(folder): path for path in folder.rglob('*') if path.is_file()}


def comparable_bytes(path):
    contents = path.read_bytes()
    if path.suffix.lower() in {'.js', '.css', '.html', '.json', '.svg', '.txt'}:
        return contents.replace(b'\r\n', b'\n')
    return contents


def compare_generated(generated):
    expected = files_under(ROOT / 'static')
    actual = files_under(generated)
    missing = expected.keys() - actual.keys()
    extra = actual.keys() - expected.keys()
    changed = {name for name in expected.keys() & actual.keys()
               if comparable_bytes(expected[name]) != comparable_bytes(actual[name])}
    if missing or extra or changed:
        parts = [f'{kind}: {", ".join(str(name) for name in sorted(names))}'
                 for kind, names in [('missing', missing), ('extra', extra), ('changed', changed)] if names]
        raise ValueError('Generated static/ differs from tracked release assets; run build.py and stage the results. '
                         + '; '.join(parts))


def verify(package_out=None):
    with tempfile.TemporaryDirectory(prefix='agents-on-air-verify-') as temporary:
        generated = Path(temporary) / 'static'
        build(generated)
        compare_generated(generated)
        command(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v')
        for test in sorted((ROOT / 'tests').glob('*.cjs')):
            command('node', str(test))
        target = Path(package_out) if package_out else Path(temporary) / 'agents-on-air.zip'
        target.parent.mkdir(parents=True, exist_ok=True)
        package(target, static_source=generated)
        print(f'Verified ZIP: {target}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-out', type=Path, help='Keep the verified release ZIP at this path')
    args = parser.parse_args()
    try:
        verify(args.package_out)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'verify: {error}', file=sys.stderr)
        sys.exit(1)
