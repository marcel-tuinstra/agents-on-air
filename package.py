"""Package source and runtime; never include local chat data or QA captures."""
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
TOP_LEVEL = (
    '.gitignore', 'build.py', 'theme_packs.py', 'package.py', 'server.py', 'live_feed.py', 'start_studio.py',
    'setup_studio.py', 'LICENSE', 'THIRD_PARTY.md', 'THEMES.md', 'narration.py', 'README.md', 'requirements.txt',
    'Start Studio.command', 'Start Studio.sh', 'Start Studio.bat',
)
DIRECTORIES = ('.github', 'themes', 'frontend', 'static', 'providers', 'tests', 'licenses')


def package(target):
    files = [ROOT / name for name in TOP_LEVEL]
    for name in DIRECTORIES:
        files.extend(path for path in (ROOT / name).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix != '.pyc' and not path.name.startswith('.'))
    partial = target.with_suffix('.zip.tmp')
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            archive.write(path, Path('agents-on-air') / path.relative_to(ROOT))
    with zipfile.ZipFile(partial) as archive:
        if archive.testzip() is not None:
            raise ValueError('Package verification failed.')
    os.replace(partial, target)


if __name__ == '__main__':
    target = ROOT.parent / 'agents-on-air.zip'
    package(target)
    print(f'Package: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MiB)')
