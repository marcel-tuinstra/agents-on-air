import json
from pathlib import Path
import shutil
import tempfile
import unittest
from theme_packs import build_themes, load_packs

ROOT=Path(__file__).resolve().parents[1]
class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'themes';self.output=self.root/'static'
        self.source.mkdir();self.output.mkdir()
        shutil.copytree(ROOT/'themes/paper',self.source/'custom-fox')
        self.manifest=self.source/'custom-fox/theme.json'
        self.change(id='custom-fox',name='Custom fox',shortName='Fox')
    def change(self,**values):
        data=json.loads(self.manifest.read_text());data.update(values);self.manifest.write_text(json.dumps(data))
    def test_add_and_remove_pack_assets_and_namespace_audio(self):
        catalog,controls=build_themes(self.source,self.output)
        self.assertIn('custom-fox',catalog);self.assertIn('custom-fox',controls)
        self.assertEqual(catalog['custom-fox']['voiceSlots'][0],'custom-fox/paper')
        self.assertTrue((self.output/'themes/custom-fox/cast.webp').exists())
        shutil.copytree(ROOT/'themes/pocket',self.source/'pocket')
        self.change(enabled=False)
        catalog,_=build_themes(self.source,self.output)
        self.assertNotIn('custom-fox',catalog)
        self.assertFalse((self.output/'themes/custom-fox').exists())
        self.assertNotIn('custom-fox',(self.output/'themes.json').read_text())
    def test_bad_paths_css_and_audio_are_rejected(self):
        for value in ('../cast.webp','https://example.test/cast.webp'):
            self.change(cast=value)
            with self.assertRaises(ValueError):load_packs(self.source)
        self.change(cast='cast.webp',tokens={'--ink':'red; background:url(https://example.test)'})
        with self.assertRaises(ValueError):load_packs(self.source)
        self.change(tokens={})
        audio=self.source/'custom-fox/audio.json';data=json.loads(audio.read_text());data['voices']['paper']['interval']=0
        audio.write_text(json.dumps(data))
        with self.assertRaises(ValueError):load_packs(self.source)
    def test_linked_asset_and_empty_installation_are_rejected(self):
        image=self.source/'custom-fox/cast.webp';image.unlink();image.symlink_to(ROOT/'themes/paper/cast.webp')
        with self.assertRaises(ValueError):load_packs(self.source)
        self.change(enabled=False)
        with self.assertRaises(ValueError):load_packs(self.source)
    def test_builtin_voice_profiles_preserve_parameters(self):
        packs=load_packs(ROOT/'themes');self.assertEqual([m['id'] for _,m,_ in packs],['midnight','paper','pocket'])
        self.assertEqual(packs[0][2]['voices']['midnight']['interval'],.10625)
        self.assertEqual(packs[1][2]['voices']['paper']['interval'],.065)
        self.assertEqual(packs[2][2]['voices']['pocket-pixel']['interval'],.0475)

    def test_reserved_identity_empty_mouth_and_invalid_token_are_rejected(self):
        self.change(tokens={'ink':'red'})
        with self.assertRaises(ValueError):load_packs(self.source)
        self.change(tokens={})
        path=self.source/'custom-fox/audio.json';data=json.loads(path.read_text())
        data['voices']['paper']['templates'][0]['mouth']=''
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):load_packs(self.source)
        self.change(id='constructor')
        (self.source/'custom-fox').rename(self.source/'constructor')
        with self.assertRaises(ValueError):load_packs(self.source)
