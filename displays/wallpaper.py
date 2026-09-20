"""User-owned Omarchy background clone with independent wallpaper groups.

The original renderer is retained in the clone, including theme IPC and effects.
Only image geometry and source selection change. Never edit packaged files.
"""
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from adapter import DisplayError


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'omarchy/wallpaper.json'


def load():
    path = config_path()
    return json.loads(path.read_text()) if path.exists() else {'version': 1, 'groups': []}


def validate(document):
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('groups'), list):
        raise DisplayError('Invalid wallpaper settings.')
    used = set()
    result = {'version': 1, 'groups': []}
    for group in document['groups']:
        if not isinstance(group, dict):
            raise DisplayError('Invalid wallpaper group.')
        outputs = group.get('outputs')
        if not isinstance(outputs, list) or not outputs or any(not isinstance(o, str) or not o or len(o) > 128 for o in outputs):
            raise DisplayError('Choose at least one display for each wallpaper group.')
        if len(set(outputs)) != len(outputs) or used.intersection(outputs):
            raise DisplayError('A display can belong to only one wallpaper group.')
        used.update(outputs)
        mode, fit = group.get('mode'), group.get('fit')
        if mode not in ('repeat', 'span') or fit not in ('crop', 'fit'):
            raise DisplayError('Invalid wallpaper placement or fit.')
        if mode == 'span' and len(outputs) < 2:
            raise DisplayError('Select at least two displays to span a wallpaper.')
        image = group.get('image')
        if image is not None:
            if not isinstance(image, str) or not image:
                raise DisplayError('Choose an image, or use the current theme wallpaper.')
            path = Path(image).expanduser()
            if not path.is_file() or not os.access(path, os.R_OK) or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.avif'):
                raise DisplayError('Wallpaper must be a readable PNG, JPEG, WebP, BMP, GIF or AVIF image.')
            image = str(path.resolve())
        result['groups'].append(dict(outputs=outputs, mode=mode, image=image, fit=fit))
    return result


INJECTION = '''
  // Hypertile wallpaper groups; the theme renderer and IPC remain Omarchy's.
  property var wallpaperConfig: ({version: 1, groups: []})
  FileView {
    id: wallpaperSettings
    path: (Quickshell.env("XDG_CONFIG_HOME") || root.home + "/.config") + "/omarchy/wallpaper.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.wallpaperConfig = JSON.parse(text()) } catch (e) { console.warn("Wallpaper settings:", e) }
    }
  }
'''
PANEL = '''
      readonly property var wallpaperGroup: Wallpaper.groupFor(root.wallpaperConfig, modelData.name)
      readonly property var wallpaperFrame: Wallpaper.frame(root.wallpaperConfig, modelData.name,
        Quickshell.screens.map(s => ({name: s.name, x: s.x, y: s.y, width: s.width, height: s.height})))
      property bool customImageFailed: false
      onWallpaperGroupChanged: customImageFailed = false
      function wallpaperSource(themeImage) {
        return root.imageUrl(wallpaperGroup.image && !customImageFailed ? wallpaperGroup.image : themeImage)
      }
      contentItem.clip: true
'''


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise DisplayError('This Omarchy background renderer needs an updated Hypertile adapter.')
    return source.replace(old, new)


def render(source):
    """Fail before activation if an Omarchy upgrade changes any integration point."""
    source = 'import "Wallpaper.js" as Wallpaper\n' + source
    source = replace_once(source, '  property string currentBackground:', INJECTION + '\n  property string currentBackground:')
    source = replace_once(source, '      screen: modelData', PANEL + '\n      screen: modelData')
    for name, image in [('base', 'displayedBackground'), ('oldFrame', 'oldBackground'), ('incomingFrame', 'incomingBackground')]:
        import re
        pattern = r'(id: ' + name + r'\s+)anchors.fill: parent\s+source: root.imageUrl\(root.' + image + r'\)\s+fillMode: Image.PreserveAspectCrop'
        replacement = (r'\1x: panel.wallpaperFrame.x\n        y: panel.wallpaperFrame.y\n'
            '        width: panel.wallpaperFrame.width\n        height: panel.wallpaperFrame.height\n'
            '        source: panel.wallpaperSource(root.' + image + ')\n'
            '        fillMode: panel.wallpaperGroup.fit === "fit" ? Image.PreserveAspectFit : Image.PreserveAspectCrop')
        source, count = re.subn(pattern, replacement, source)
        if count != 1:
            raise DisplayError('This Omarchy background renderer needs an updated Hypertile image adapter.')
    # A deleted/broken custom image falls back to the theme instead of a blank screen.
    source = replace_once(source, 'if (status === Image.Ready && root.finishingTransition)',
        'if (status === Image.Error && panel.wallpaperGroup.image) panel.customImageFailed = true\n          if (status === Image.Ready && root.finishingTransition)')
    source = replace_once(source, '      color: "transparent"', '      color: "black"')
    source = replace_once(source, '    target: "background"', '\n'.join([
        '    target: "background"',
        '    function wallpaperState(): string {',
        '      return JSON.stringify({settings: root.wallpaperConfig, screens: Quickshell.screens.map(s => ({name: s.name, group: Wallpaper.groupFor(root.wallpaperConfig, s.name), frame: Wallpaper.frame(root.wallpaperConfig, s.name, Quickshell.screens.map(m => ({name: m.name, x: m.x, y: m.y, width: m.width, height: m.height})))}))})',
        '    }']))
    return source


def install_renderer():
    from service import atomic
    root = config_path().parent / 'plugins'
    # Use Omarchy's supported clone operation, retaining its replacement metadata.
    clone = root / ((os.environ.get('USER') or getpass.getuser()) + '.background')
    assets = root / 'jmartin.hypertile/plugin/Wallpaper.js'
    if not assets.is_file():
        raise DisplayError('Install Hypertile before configuring wallpaper groups.')
    stock = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell/plugins/background/Background.qml'
    generated = render(stock.read_text())
    marker = clone / 'hypertile-renderer.json'
    if clone.exists() and not marker.exists():
        raise DisplayError('An existing custom background clone is present. It has been left unchanged.')
    if marker.exists():
        previous = json.loads(marker.read_text())
        for name, digest in previous.items():
            if hashlib.sha256((clone / name).read_bytes()).hexdigest() != digest:
                raise DisplayError('The background clone has local edits. It has been left unchanged.')
    else:
        subprocess.run(['omarchy', 'plugin', 'clone', 'omarchy.background'], check=True, capture_output=True, text=True, timeout=20)
        (clone / 'Background.omarchy.qml.bak').write_text((clone / 'Background.qml').read_text())
    # A new component URL bypasses Quickshell's cached QML after an upgrade.
    helper = assets.read_text()
    revision = hashlib.sha256((generated + helper).encode()).hexdigest()[:16]
    renderer_name = 'BackgroundH' + revision + '.qml'
    helper_name = 'WallpaperH' + revision + '.js'
    generated = generated.replace('import "Wallpaper.js"', 'import "' + helper_name + '"')
    manifest = json.loads((clone / 'manifest.json').read_text())
    manifest['entryPoints']['service'] = renderer_name
    files = {renderer_name: generated, helper_name: helper,
             'manifest.json': json.dumps(manifest, indent=2) + '\n'}
    changed = False
    for name, content in files.items():
        if (clone / name).exists() and (clone / name).read_text() == content:
            continue
        changed = True
        temp = clone / (name + '.tmp')
        temp.write_text(content)
        temp.replace(clone / name)
    if changed:
        atomic(marker, {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()})
        subprocess.run(['omarchy-shell', 'shell', 'rescanPlugins'], check=True, capture_output=True, text=True, timeout=10)
    shell_config = json.loads((config_path().parent / 'shell.json').read_text())
    if clone.name in shell_config.get('disabledPlugins', []) or not any(p.get('id') == clone.name for p in shell_config.get('plugins', [])):
        subprocess.run(['omarchy', 'plugin', 'enable', clone.name], check=True, capture_output=True, text=True, timeout=10)
    return clone.name, changed


def reload_shell_later():
    # Renderer upgrades require a fresh Quickshell VFS/component cache. Let the
    # response reach the UI before restarting; this child survives UI teardown.
    subprocess.Popen(['sh', '-c', 'sleep 2; exec omarchy restart shell'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def apply_detached(request):
    # Installing a background clone reloads shell plugins, which can destroy the
    # QML Process waiting for us. Its worker must survive to finish the save.
    with tempfile.TemporaryDirectory(prefix='hypertile-wallpaper-') as directory:
        out = Path(directory) / 'result.json'
        err = Path(directory) / 'error.txt'
        with out.open('w') as stdout, err.open('w') as stderr:
            worker = subprocess.Popen([sys.executable, str(Path(__file__).with_name('service.py')),
                                       'wallpaper', '--worker', '--json', json.dumps(request)],
                                      stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                      start_new_session=True)
            worker.wait(timeout=60)
        try:
            result = json.loads(out.read_text())
        except ValueError:
            raise DisplayError(err.read_text().strip() or 'Wallpaper setup did not finish.')
        if worker.returncode:
            raise DisplayError(result.get('error', 'Could not apply wallpaper settings.'))
        return result
