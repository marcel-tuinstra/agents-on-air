"""Start the extracted release without dependencies, accounts or personal chats."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile


def check_package(archive_path):
    with tempfile.TemporaryDirectory(prefix='agents-on-air-install-') as temporary:
        base = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(base)
        app = base / 'agents-on-air'
        # An unrelated working directory catches accidental workspace-relative paths.
        cwd = base / 'empty-workspace'
        cwd.mkdir()
        codex = base / 'codex'
        claude = base / 'claude'
        codex.mkdir()
        claude.mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('STUDIO_NARRATION_') and key != 'PYTHONPATH'}
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONIOENCODING='utf-8',
                   CODEX_HOME=str(codex), CLAUDE_CONFIG_DIR=str(claude))
        # --help exercises the real launcher without opening a browser in CI.
        help_result = subprocess.run([sys.executable, '-I', str(app / 'start_studio.py'), '--help'],
                                     cwd=cwd, env=env, capture_output=True, text=True,
                                     encoding='utf-8', timeout=15)
        if help_result.returncode or '--codex-home' not in help_result.stdout:
            raise ValueError('ZIP launcher failed its startup check.')
        with (base / 'server.log').open('w+', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(app / 'server.py'), '--port', '0',
                                        '--codex-home', str(codex), '--claude-home', str(claude)],
                                       cwd=cwd, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 15
                url = None
                while time.monotonic() < deadline:
                    log.seek(0)
                    match = re.search(r'Agents on Air: (http://127\.0\.0\.1:\d+)', log.read())
                    if match:
                        url = match.group(1)
                        break
                    if process.poll() is not None:
                        raise ValueError('ZIP server exited before startup.')
                    time.sleep(.05)
                if not url:
                    raise ValueError('ZIP server did not start within 15 seconds.')
                with urllib.request.urlopen(url, timeout=5) as response:
                    html = response.read().decode()
                    cookie = response.headers['Set-Cookie'].split(';')[0]
                if 'Agents on Air' not in html:
                    raise ValueError('ZIP did not serve the studio.')

                def get(path):
                    request = urllib.request.Request(url + path, headers={'Cookie': cookie})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return response.read()

                catalog = json.loads(get('/api/catalog'))
                if catalog['chats']:
                    raise ValueError('Fresh install unexpectedly found chats.')
                if json.loads(get('/api/narration/config'))['enabled']:
                    raise ValueError('Fresh install enabled external processing.')
                assets = set(re.findall(r'(?:src|href)="(/[^"?#]+)', html))
                assets.update(json.loads((app / 'static/themes.json').read_text())['assets'])
                assets.update('/fonts/' + name for name in ('Lora.ttf', 'Nunito.ttf', 'PixelifySans.ttf'))
                for asset in sorted(assets):
                    if not get(asset):
                        raise ValueError(f'Empty packaged asset: {asset}')
                print(f'Fresh ZIP: launcher, empty catalog, settings and {len(assets)} assets passed.', flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    check_package(Path(sys.argv[1]))
