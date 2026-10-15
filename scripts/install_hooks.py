"""Install only this repository's hooks without replacing an existing setup."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OWN_PATH = '.githooks'


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                          text=True, check=check)


def install():
    root = Path(git('rev-parse', '--show-toplevel').stdout.strip()).resolve()
    if root != ROOT:
        raise ValueError(f'Run the installer in its own checkout: {ROOT}')
    current = git('config', '--local', '--get', 'core.hooksPath', check=False)
    if current.returncode == 0:
        value = current.stdout.strip()
        configured = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        if configured == root / OWN_PATH:
            print('Hooks already installed for this repository.')
            return
        raise ValueError(f'Existing core.hooksPath is {value!r}; leaving it untouched.')
    if current.returncode != 1:
        raise ValueError(current.stderr.strip() or 'Could not inspect core.hooksPath.')
    inherited = git('config', '--get', 'core.hooksPath', check=False)
    if inherited.returncode == 0:
        raise ValueError(f'Existing inherited core.hooksPath is {inherited.stdout.strip()!r}; '
                         'leaving it untouched.')
    if inherited.returncode != 1:
        raise ValueError(inherited.stderr.strip() or 'Could not inspect inherited core.hooksPath.')
    hooks = Path(git('rev-parse', '--git-path', 'hooks').stdout.strip())
    if not hooks.is_absolute():
        hooks = root / hooks
    existing = sorted(path.name for path in hooks.iterdir()
                      if path.is_file() and not path.name.endswith('.sample')) if hooks.exists() else []
    if existing:
        raise ValueError('Existing default Git hooks: ' + ', '.join(existing) +
                         '. Leaving them untouched; review and migrate them first.')
    for name in ('pre-commit', 'pre-push'):
        hook = root / OWN_PATH / name
        if not hook.is_file():
            raise ValueError(f'Missing hook: {hook}')
    git('config', '--local', 'core.hooksPath', OWN_PATH)
    print('Installed repository-local pre-commit and pre-push hooks.')


if __name__ == '__main__':
    try:
        install()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'install-hooks: {error}', file=sys.stderr)
        sys.exit(1)
