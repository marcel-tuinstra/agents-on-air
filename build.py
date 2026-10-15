"""Build the frontend using only files shipped with this project."""
from pathlib import Path
import shutil
from theme_packs import build_themes, load_packs

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'frontend'
OUTPUT = ROOT / 'static'
SCRIPTS = (
    'marked.js', 'purify.js', 'markdown.js', 'stage-model.js',
    'themes.js', 'voice-profiles.js', 'speech.js', 'body.js', 'rig.js',
    'controllers.js', 'stream.js', 'work-view.js', 'captions.js', 'app.js', 'settings.js',
)


def build(output=OUTPUT):
    output = Path(output)
    load_packs(ROOT / "themes")  # Reject malformed packs before touching generated output.
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE / 'public', output, dirs_exist_ok=True)
    for source in sorted(SOURCE.iterdir()):
        if source.suffix in ('.js', '.css'):
            shutil.copyfile(source, output / source.name)
    catalog, controls = build_themes(ROOT / 'themes', output)
    room = (SOURCE / 'room.html').read_text(encoding='utf-8')
    room = room.replace('<header class="appbar"></header>',
                        '<header class="appbar">' + (SOURCE / 'toolbar.html').read_text(encoding='utf-8') + '</header>')
    room = room.replace('<!-- SETTINGS -->', (SOURCE / 'settings.html').read_text(encoding='utf-8'))
    room = room.replace('<!-- CHANNELS -->', controls)
    scripts = ''.join(f'<script src="/{name}" defer></script>' for name in SCRIPTS)
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Agents on Air · Live</title><link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/themes.css">'
            '</head><body><div id="studio-hub" data-theme="midnight">'
            + room + '</div>' + scripts + '</body></html>')
    (output / 'index.html').write_text(page, encoding='utf-8')


if __name__ == '__main__':
    build()
