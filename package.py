"""Package source and runtime; never include local chat data or QA captures."""
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
TOP_LEVEL = (
    '.gitignore', 'build.py', 'theme_packs.py', 'package.py', 'server.py', 'live_feed.py', 'start_studio.py',
    'setup_studio.py', 'LICENSE', 'THIRD_PARTY.md', 'THEMES.md', 'narration.py', 'README.md', 'requirements.txt',
    'Start Studio.command', 'Start Studio.sh', 'Start Studio.bat', '.gitattributes',
)
DIRECTORIES = ('.github', '.githooks', 'docs', 'themes', 'frontend', 'static',
               'providers', 'tests', 'licenses', 'scripts')


def package(target, static_source=None):
    target = Path(target)
    static_source = Path(static_source) if static_source is not None else ROOT / 'static'
    files = [ROOT / name for name in TOP_LEVEL]
    entries = [(path, Path('agents-on-air') / path.relative_to(ROOT)) for path in files]
    for name in DIRECTORIES:
        source = static_source if name == 'static' else ROOT / name
        entries.extend((path, Path('agents-on-air') / name / path.relative_to(source))
                       for path in source.rglob('*') if path.is_file()
                       and '__pycache__' not in path.parts
                       and path.suffix != '.pyc' and not path.name.startswith('.'))
    partial = target.with_suffix('.zip.tmp')
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, archive_name in sorted(entries, key=lambda entry: str(entry[1])):
            archive.write(path, archive_name)
    with zipfile.ZipFile(partial) as archive:
        if archive.testzip() is not None:
            raise ValueError('Package verification failed.')
    os.replace(partial, target)


if __name__ == '__main__':
    target = ROOT.parent / 'agents-on-air.zip'
    package(target)
    print(f'Package: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MiB)')
