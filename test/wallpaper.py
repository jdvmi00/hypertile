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

# Integration points from Omarchy's sized BackgroundMedia renderer. The
# opt-in wallpaper_integration.py also loads the complete installed renderer.
SIZED_SOURCE = '''
  property string currentBackground: ""
  property var nativeSizes: ({})
    var paths = [displayedBackground, incomingBackground, oldBackground, preparedBackground]
    target: "background"
      screen: modelData
      color: "transparent"
      readonly property int decodeWidth: sized ? Math.ceil(width * screen.devicePixelRatio) : 0
      readonly property int decodeHeight: sized ? Math.ceil(height * screen.devicePixelRatio) : 0
      BackgroundMedia {
        id: base
        anchors.fill: parent
        path: root.displayedBackground
        constrainDecode: true
        decodeSize: panel.decodeSize(root.displayedBackground)
        onReadyChanged: {
          if (ready && root.finishingTransition) {
            root.incomingBackground = ""
            root.oldBackground = ""
            root.preparedBackground = ""
            root.finishingTransition = false
            root.pruneNativeSizes()
          }
        }
      }
      Image {
        id: oldFrame
        anchors.fill: parent
        readonly property size decode: panel.decodeSize(root.oldBackground)
        source: decode.width > 0 ? root.imageUrl(root.oldBackground) : ""
        sourceSize.width: decode.width
        sourceSize.height: decode.height
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        onStatusChanged: panel.maybeStartReveal()
      }
        Image {
          id: incomingFrame
          anchors.fill: parent
          readonly property string framePath: root.incomingBackground || root.preparedBackground
          readonly property size decode: panel.decodeSize(framePath)
          source: decode.width > 0 ? root.imageUrl(framePath) : ""
          sourceSize.width: decode.width
          sourceSize.height: decode.height
          fillMode: Image.PreserveAspectCrop
          asynchronous: true
          cache: false
          onStatusChanged: panel.maybeStartReveal()
        }
'''

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
        source = 'import QtQuick\nItem {\n  property string currentBackground: ""\n  IpcHandler {\n    target: "background"\n  }\n  Item {\n      screen: modelData\n      color: "transparent"\n      onStatusChanged: { if (status === Image.Ready && root.finishingTransition) {} }\n'
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
            # An upstream renderer upgrade replaces the component URL while
            # retaining the custom-image helper and idempotent installation.
            (stock / 'Background.qml').write_text(SIZED_SOURCE)
            self.assertEqual(wallpaper.install_renderer(), (clone.name, True))
            upgraded = json.loads((clone / 'manifest.json').read_text())
            self.assertNotEqual(upgraded['entryPoints']['service'], manifest['entryPoints']['service'])
            renderer = clone / upgraded['entryPoints']['service']
            generated = renderer.read_text()
            self.assertEqual(wallpaper.install_renderer(), (clone.name, False))
            renderer.write_text(generated + '// local edit')
            with self.assertRaisesRegex(DisplayError, 'local edits'):
                wallpaper.install_renderer()

    def test_sized_renderer_preserves_bounded_decode_and_reveal(self):
        generated = wallpaper.render(SIZED_SOURCE)
        for fragment in ('sourceSize.width: decode.width', 'sourceSize.height: decode.height',
                         'asynchronous: true', '!root.isVideo(framePath)',
                         'width: panel.wallpaperFrame.width', 'panel.customImageFailed = true'):
            self.assertEqual(generated.count(fragment), 3, fragment)
        self.assertEqual(generated.count('cache: false'), 2)
        self.assertIn('root.isVideo(panel.wallpaperPath(root.displayedBackground)) ? "transparent" : "black"', generated)
        self.assertEqual(generated.count('panel.maybeStartReveal()'), 2)
        self.assertIn('onFinishingTransitionChanged() { base.finishTransition() }', generated)
        self.assertIn('onWallpaperConfigChanged: requestWallpaperSizes()', generated)
        self.assertIn('Math.ceil(wallpaperFrame.width * screen.devicePixelRatio)', generated)
        self.assertIn('root.oldBackground ? panel.wallpaperPath(root.oldBackground) : ""', generated)
        self.assertIn('.concat((wallpaperConfig.groups || []).map(group => group.image))', generated)

    def test_unknown_sized_renderer_fails_before_activation(self):
        for point in ('path: root.displayedBackground', 'id: incomingFrame',
                      'sourceSize.width: decode.width\n        sourceSize.height: decode.height\n        fillMode: Image.PreserveAspectCrop',
                      'var paths = [displayedBackground, incomingBackground, oldBackground, preparedBackground]',
                      'Math.ceil(width * screen.devicePixelRatio)', 'onStatusChanged: panel.maybeStartReveal()'):
            with self.subTest(point=point), self.assertRaisesRegex(DisplayError, 'updated Hypertile'):
                wallpaper.render(SIZED_SOURCE.replace(point, '/* upstream change */', 1))

    def test_adapter_fails_closed_for_unknown_renderer(self):
        with self.assertRaises(DisplayError): wallpaper.render('unexpected upstream code')
        stock = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell/plugins/background/Background.qml'
        if stock.is_file():
            self.assertIn('panel.customImageFailed = true', wallpaper.render(stock.read_text()))
        for missing in ('if (status === Image.Ready && root.finishingTransition)', '      color: "transparent"', '    target: "background"'):
            source = 'import QtQuick\nItem {\n  property string currentBackground: ""\n  IpcHandler {\n    target: "background"\n  }\n  Item {\n      screen: modelData\n      color: "transparent"\n      onStatusChanged: { if (status === Image.Ready && root.finishingTransition) {} }\n'
            for name, image in [('base','displayedBackground'), ('oldFrame','oldBackground'), ('incomingFrame','incomingBackground')]:
                source += 'Image { id: ' + name + '\nanchors.fill: parent\nsource: root.imageUrl(root.' + image + ')\nfillMode: Image.PreserveAspectCrop\n}\n'
            with self.assertRaisesRegex(DisplayError, 'updated Hypertile'):
                wallpaper.render(source.replace(missing, '/* changed upstream */'))

if __name__ == '__main__': unittest.main()
