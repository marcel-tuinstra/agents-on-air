"""Build-time, data-only channel packs. Theme folders never execute code."""
import html
import json
import math
import re
import shutil
from pathlib import Path

ID = re.compile(r'^[a-z][a-z0-9-]{0,39}$')
FILE = re.compile(r'^[A-Za-z0-9_-]+\.(webp|png|ttf|woff2)$')
TOKENS = {'ink','muted','bg','panel','line','accent','onaccent','sidebar-bg','desk-edge',
          'font-ui','font-display','diff-add','diff-add-bg','diff-remove','diff-remove-bg'}


def local_file(folder, name, limit=12_000_000):
    if not isinstance(name,str) or Path(name).name != name:
        raise ValueError('Theme files must be direct children of the pack folder.')
    path=folder/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Theme file is missing, linked or too large: '+name)
    return path


def number(value, minimum, maximum):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and minimum <= value <= maximum


def validate_audio(data):
    if not isinstance(data,dict):raise ValueError('Audio must be a JSON object.')
    voices=data.get('voices',{}); slots=data.get('slots',[])
    if not isinstance(voices,dict) or not isinstance(slots,list) or not all(isinstance(v,str) for v in slots):raise ValueError('Invalid audio structure.')
    if not 1 <= len(voices) <= 11 or len(slots)!=11 or any(v not in voices for v in slots):
        raise ValueError('Audio needs 11 cast slots pointing to 1–11 voices.')
    bounds={'interval':(.025,.3),'space':(0,.4),'duration':(.025,.5),'attack':(.001,.1),
            'decay':(.001,.2),'rms':(.001,.15),'pitchVariation':(0,.2)}
    for key,voice in voices.items():
        if not ID.fullmatch(key) or not isinstance(voice,dict):raise ValueError('Invalid voice ID.')
        for field,(low,high) in bounds.items():
            if not number(voice.get(field),low,high):raise ValueError('Invalid audio parameter: '+field)
        templates=voice.get('templates',[])
        if not 1 <= len(templates) <= 32:raise ValueError('Voice needs 1–32 sound templates.')
        for template in templates:
            if not isinstance(template,dict):raise ValueError('Template must be an object.')
            if not number(template.get('pitch'),60,1200) or template.get('mouth') not in set('ABCDEFGHX'):
                raise ValueError('Invalid pitch or mouth shape.')
            if 'partials' in template:
                parts=template['partials']
                if not 1 <= len(parts) <= 64 or any(len(pair)!=2 or not number(pair[0],.1,64) or not number(pair[1],0,1) for pair in parts):
                    raise ValueError('Invalid partial weights.')
            else:
                harmonics=template.get('harmonics',[])
                if not 1 <= len(harmonics) <= 64 or not all(number(v,0,1) for v in harmonics):
                    raise ValueError('Invalid harmonic weights.')
        for field in ('sentencePause','commaPause'):
            if field in voice and not number(voice[field],0,2):raise ValueError('Invalid pause.')
    return data


def load_packs(source):
    packs=[]
    for folder in sorted(source.iterdir()):
        if not folder.is_dir() or folder.name.startswith('.'):continue
        if folder.is_symlink():raise ValueError('Linked theme directories are not supported.')
        manifest=json.loads(local_file(folder,'theme.json',64_000).read_text())
        if not isinstance(manifest,dict):raise ValueError('Theme manifest must be an object.')
        if manifest.get('enabled') is False:continue
        identity=manifest.get('id','')
        if not ID.fullmatch(identity) or identity != folder.name or identity in ('constructor','prototype'):raise ValueError('Theme ID must match its folder.')
        if manifest.get('schemaVersion')!=1 or manifest.get('rig') not in ('midnight','paper','pocket'):
            raise ValueError('Unsupported theme schema or rig.')
        for field in ('name','shortName','role','direction','license'):
            if not isinstance(manifest.get(field),str) or not 1 <= len(manifest[field]) <= 240:raise ValueError('Missing theme '+field)
        for field in ('cast','scenery'):
            name=manifest.get(field,'')
            if not FILE.fullmatch(name) or Path(name).suffix not in ('.png','.webp'):raise ValueError('Use PNG or WebP theme images.')
            local_file(folder,name)
        if not number(manifest.get('sceneryPosition'),0,100):raise ValueError('Invalid scenery position.')
        crop=manifest.get('portrait',[])
        if len(crop)!=4 or not all(number(v,0,256) for v in crop) or min(crop[2:])<=0:raise ValueError('Invalid portrait crop.')
        for key,value in manifest.get('tokens',{}).items():
            if not key.startswith('--') or key[2:] not in TOKENS or not isinstance(value,str) or not re.fullmatch(r'[\w\s#.,%"\'-]+',value):
                raise ValueError('Invalid theme CSS token.')
        fonts=manifest.get('fonts',[])
        if len(fonts)>2:raise ValueError('At most two local fonts are supported.')
        for font in fonts:
            if not isinstance(font,dict):raise ValueError('Font must be an object.')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9 -]{0,40}',font.get('family','')) or not FILE.fullmatch(font.get('file','')) or Path(font['file']).suffix not in ('.ttf','.woff2'):
                raise ValueError('Invalid local font.')
            local_file(folder,font['file'],4_000_000)
        audio=validate_audio(json.loads(local_file(folder,manifest.get('audio','audio.json'),128_000).read_text()))
        packs.append((folder,manifest,audio))
    if not 1 <= len(packs) <= 32:raise ValueError('Enable between 1 and 32 themes.')
    # Keep the established order; community packs follow alphabetically.
    order={'midnight':0,'paper':1,'pocket':2}
    return sorted(packs,key=lambda p:(order.get(p[1]['id'],3),p[1]['id']))


def build_themes(source, output):
    packs=load_packs(source);catalog={};voices={};css=[];assets=[]
    generated=output/'themes'
    if generated.is_symlink():raise ValueError('Generated theme output cannot be a symlink.')
    if generated.exists():shutil.rmtree(generated)
    for folder,manifest,audio in packs:
        identity=manifest['id'];target=output/'themes'/identity;target.mkdir(parents=True,exist_ok=True)
        data={**manifest,'voiceSlots':[identity+'/'+v for v in audio['slots']]}
        for field in ('cast','scenery'):
            data[field]='/themes/'+identity+'/'+manifest[field]
        for name in sorted({manifest['cast'],manifest['scenery'],*(f['file'] for f in manifest.get('fonts',[]))}):
            shutil.copyfile(folder/name,target/name);assets.append('/themes/'+identity+'/'+name)
        for voice,profile in audio['voices'].items():
            voices[identity+'/'+voice]=profile
            if identity in ('midnight','paper','pocket'):voices[voice]=profile
        catalog[identity]=data
        for font in manifest.get('fonts',[]):
            css.append('@font-face{font-family:"'+font['family']+'";src:url("/themes/'+identity+'/'+font['file']+'");font-display:swap;}')
        declarations=';'.join(k+':'+v for k,v in manifest['tokens'].items())
        css.append('#studio-hub[data-channel="'+identity+'"],body[data-channel="'+identity+'"]{'+declarations+'}')
    (output/'themes.json').write_text(json.dumps({'assets':assets}))
    (output/'themes.js').write_text('window.StudioThemes = '+json.dumps(catalog,ensure_ascii=True)+';\n')
    (output/'themes.css').write_text('\n'.join(css)+'\n')
    (output/'voice-profiles.js').write_text('/* Generated from theme audio.json files. */\n(function(scope){scope.StudioVoiceProfiles='+json.dumps(voices)+';})(typeof window === "undefined" ? globalThis : window);\n')
    controls=''.join('<label class="channel-option" title="'+html.escape(m['name'],quote=True)+'"><input type="radio" name="studio-channel" value="'+m['id']+'" aria-label="'+html.escape(m['name'],quote=True)+'"><span class="channel-avatar"><canvas width="128" height="128" data-channel-portrait="'+m['id']+'" aria-hidden="true"></canvas></span><span>'+html.escape(m['shortName'])+'</span></label>' for _,m,_ in packs)
    return catalog,controls
