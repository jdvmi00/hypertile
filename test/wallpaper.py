import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
import wallpaper
from adapter import DisplayError
from service import Service, atomic

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, XDG_CONFIG_HOME=self.temp.name)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.image = Path(self.temp.name) / 'fixed.png'
        self.image.write_bytes(b'fixture')
        self.doc = {'version':1, 'groups':[
            {'outputs':['DP-1','DP-2'],'mode':'span','image':None,'fit':'crop'},
            {'outputs':['DP-3'],'mode':'repeat','image':str(self.image),'fit':'fit'}]}
    def test_independent_image_and_theme_groups(self):
        self.assertEqual(wallpaper.validate(self.doc), self.doc)
        self.assertEqual(wallpaper.load(), {'version':1, 'groups':[]})
    def test_invalid_membership_and_images(self):
        for change in ({'outputs':['DP-1']}, {'outputs':['DP-1','DP-1']}, {'mode':'bad'}, {'fit':'bad'}, {'image':'/not-here.png'}):
            doc = copy.deepcopy(self.doc)
            doc['groups'][0].update(change)
            with self.assertRaises(DisplayError): wallpaper.validate(doc)
        self.doc['groups'][1]['outputs'] = ['DP-1']
        with self.assertRaisesRegex(DisplayError,'only one'): wallpaper.validate(self.doc)
    def test_apply_checks_stale_settings_preview_and_persists(self):
        class Adapter:
            def displays(self): return [{'connector':'DP-1'},{'connector':'DP-2'},{'connector':'DP-3'}]
        service = Service(Adapter(), Path(self.temp.name) / 'state')
        service.policy = None
        request = {'previous':wallpaper.load(),'settings':self.doc}
        with patch.object(wallpaper, 'install_renderer', return_value=('user.background', False)) as install:
            atomic(service.pending_path, {'token':'test'})
            with self.assertRaisesRegex(DisplayError,'preview'): service.wallpaper(request)
            install.assert_not_called()
            service.pending_path.unlink()
            service.wallpaper(request)
            self.assertEqual(wallpaper.load(), self.doc)
            with self.assertRaisesRegex(DisplayError,'elsewhere'): service.wallpaper(request)
            self.assertEqual(install.call_count, 1)
    def test_unknown_output_does_not_install(self):
        class Adapter:
            def displays(self): return []
        service = Service(Adapter(), Path(self.temp.name) / 'state')
        service.policy = None
        with patch.object(wallpaper, 'install_renderer') as install:
            with self.assertRaisesRegex(DisplayError,'no longer available'):
                service.wallpaper({'previous':wallpaper.load(),'settings':self.doc})
            install.assert_not_called()
    def test_renderer_patch_and_upgrade_preserve_local_edits(self):
        source = 'import QtQuick\nItem {\n  property string currentBackground: ""\n  IpcHandler {\n    target: "background"\n  }\n  Item {\n      screen: modelData\n      color: "transparent"\n'
        for name, image in [('base','displayedBackground'), ('oldFrame','oldBackground'), ('incomingFrame','incomingBackground')]:
            source += 'Image { id: ' + name + '\nanchors.fill: parent\nsource: root.imageUrl(root.' + image + ')\nfillMode: Image.PreserveAspectCrop\n}\n'
        source += '}\n}\n'
        root = wallpaper.config_path().parent / 'plugins'
        clone = root / ((os.environ.get('USER') or wallpaper.getpass.getuser()) + '.background')
        clone.mkdir(parents=True)
        (clone / 'manifest.json').write_text(json.dumps({'entryPoints':{'service':'Background.qml'}}))
        (clone / 'hypertile-renderer.json').write_text('{}')
        assets = root / 'jmartin.hypertile/plugin'
        assets.mkdir(parents=True)
        (assets / 'Wallpaper.js').write_text('// test helper')
        (wallpaper.config_path().parent / 'shell.json').write_text(json.dumps({'plugins':[{'id':clone.name}]}))
        stock = Path(self.temp.name) / 'stock/shell/plugins/background'
        stock.mkdir(parents=True)
        (stock / 'Background.qml').write_text(source)
        with patch.dict(os.environ, OMARCHY_PATH=str(Path(self.temp.name)/'stock')), patch.object(wallpaper.subprocess, 'run'):
            self.assertEqual(wallpaper.install_renderer(), (clone.name, True))
            manifest = json.loads((clone/'manifest.json').read_text())
            renderer = clone/manifest['entryPoints']['service']
            generated = renderer.read_text()
            self.assertEqual(generated.count('width: panel.wallpaperFrame.width'), 3)
            self.assertIn('function wallpaperState()', generated)
            self.assertEqual(wallpaper.install_renderer(), (clone.name, False))
            renderer.write_text(generated + '// local edit')
            with self.assertRaisesRegex(DisplayError, 'local edits'):
                wallpaper.install_renderer()

    def test_adapter_fails_closed_for_unknown_renderer(self):
        with self.assertRaises(DisplayError): wallpaper.render('unexpected upstream code')

if __name__ == '__main__': unittest.main()
