"""Package the runtime and theme sources; tests, hooks and CI stay in the repository."""
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
TOP_LEVEL = (
    'build.py', 'theme_packs.py', 'server.py', 'live_feed.py', 'start_studio.py',
    'setup_studio.py', 'lan_access.py', 'LICENSE', 'THIRD_PARTY.md', 'THEMES.md', 'narration.py', 'README.md', 'requirements.txt',
    'Start Studio.command', 'Start Studio.sh', 'Start Studio.bat',
)
WEB = ('*.js', '*.css', '*.html', '*.json', '*.svg', '*.ttf', '*.woff2', '*.webp', '*.png')
# Only known file types are shipped, so stray local files in these folders stay out.
DIRECTORIES = {
    'docs': ('*.md', '*.png', '*.gif', '*.svg'),
    'themes': ('*.json', '*.webp', '*.png', '*.ttf', '*.woff2', 'LICENSE'),
    'frontend': WEB,
    'static': WEB,
    'providers': ('*.py',),
    'licenses': ('*.txt',),
}


def package(target, static_source=None):
    target = Path(target)
    static_source = Path(static_source) if static_source is not None else ROOT / 'static'
    files = [ROOT / name for name in TOP_LEVEL]
    entries = [(path, Path('agents-on-air') / path.relative_to(ROOT)) for path in files]
    for name, patterns in DIRECTORIES.items():
        source = static_source if name == 'static' else ROOT / name
        entries.extend((path, Path('agents-on-air') / name / path.relative_to(source))
                       for path in source.rglob('*') if path.is_file() and not path.is_symlink()
                       and '__pycache__' not in path.parts and not path.name.startswith('.')
                       and any(path.match(pattern) for pattern in patterns))
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
