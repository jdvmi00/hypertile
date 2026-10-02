"""Opt-in Displays QML smoke test with simulated outputs, on an Omarchy session.

No physical display or user configuration is changed. A disposable preview
window exercises immediate switching, saved-display removal, catalog refresh,
and Switch back.
Pass --screenshots DIRECTORY to retain before/after panel images.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--screenshots', type=Path)
args = parser.parse_args()
root = Path(tempfile.mkdtemp(prefix='hypertile-mirror-ux-'))
images = args.screenshots or root
images.mkdir(parents=True, exist_ok=True)
for name in ('Commons', 'Ui'):
    (root / name).symlink_to(Path('/usr/share/omarchy/shell') / name, target_is_directory=True)
(root / 'plugin').symlink_to(ROOT / 'plugin', target_is_directory=True)
displays = []
for connector, width, height, scale in [('DP-1',3840,2160,1.5),('HDMI-A-1',1920,1080,1)]:
    displays.append(dict(id=connector,identity=connector,connector=connector,connected=True,enabled=True,awake=True,
                         width=width,height=height,scale=scale,refresh=60,transform=0,x=0,y=0,
                         description='4K display' if connector=='DP-1' else '1080p display',
                         modes=[f'{width}x{height}@60.00Hz']))
displays[1]['mirror_of']='DP-1'
displays.append(dict(displays[0], id='old-display', connector='OLD-DP', connected=False, mirror_of=None))
(root/'state.json').write_text(json.dumps(dict(version=1,displays=displays,workspaces=[],confirmed=dict(workspaces={}),pending=None)))
ctl=root/'ctl'
ctl.write_text('''#!/usr/bin/env python3
import json, sys
from pathlib import Path
path=Path(__file__).with_name('state.json')
state=json.loads(path.read_text())
if sys.argv[2]=='wallpaper': result=dict(settings=dict(version=1,groups=[]))
elif sys.argv[2]=='use-display':
    selected=next(d for d in state['displays'] if d['connector']==sys.argv[3])
    previous=selected['mirror_of']
    for d in state['displays']:
        if d['connected']: d['mirror_of']=None if d['id']==selected['id'] else selected['id']
    path.write_text(json.dumps(state))
    result=dict(used=True,connector=selected['connector'],previous_source=previous,message='Desktop sized for '+selected['connector']+'. Other displays in the group mirror it.')
elif sys.argv[2]=='remove-display':
    identity=sys.argv[3]
    state['displays']=[d for d in state['displays'] if d['id']!=identity]
    path.write_text(json.dumps(state))
    result=dict(removed=identity,message='Saved display removed.')
elif sys.argv[2] in ('preview','keep'): raise RuntimeError('Immediate removal must not request Preview or Keep')
else: result=state
print(json.dumps(result))
''')
ctl.chmod(0o755)
qml='''import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "plugin" as Hypertile
ShellRoot {
    QtObject {
        id: overlay
        property string ctl: CTL_PATH
        property bool displaysMode: true
        property var layouts: []
        property color foreground: Color.foreground
        property color mutedForeground: Color.muted
        property color accent: Color.accent
        property color surfaceColor: Color.background
        property string fontFamily: "JetBrainsMono Nerd Font"
        property int uiFont: 14
        property int uiFontSmall: 12
        property int uiCaption: 11
        property int uiPad: 16
        property int radiusCard: 12
        property int radiusControl: 6
        function focusKeys() {}
        function placeDisplayConfirmation() {}
        function showDisplays() {}
    }
    FloatingWindow {
        id: window
        visible: true
        title: "Hypertile mirror switching — preview"
        implicitWidth: 1100
        implicitHeight: 750
        color: Color.background
        Hypertile.DisplaysPane {
            id: pane
            anchors.fill: parent
            anchors.margins: 12
            overlay: overlay
            selectedIndex: 1
        }
    }
    IpcHandler {
        target: "preview"
        function state(): string { return JSON.stringify({catalog:pane.catalog,draft:pane.draft,dirty:pane.dirty,pending:pane.pending,previous:pane.previousSource,error:pane.error,notice:pane.notice,busy:pane.busy}); }
        function use(): void { pane.useDisplay(pane.selectedDisplay.connector); }
        function back(): void { pane.useDisplay(pane.previousSource); }
        function remove(): void {
            pane.selectedIndex = 0;
            pane.setDisplay("scale", 2);
            pane.selectedIndex = pane.draft.displays.findIndex(function(d) { return d.id === "old-display"; });
            pane.removeSelectedDisplay();
        }
        function snapshot(path: string): void { pane.grabToImage(function(image) {image.saveToFile(path);}); }
    }
}
'''.replace('CTL_PATH',json.dumps(str(ctl)))
(root/'shell.qml').write_text(qml)
log=(root/'preview.log').open('w')
process=subprocess.Popen(['quickshell','-p',str(root)],stdout=log,stderr=log)
try:
    def ipc(*args):
        result=subprocess.run(['quickshell','-p',str(root),'ipc','call','preview',*args],capture_output=True,text=True,timeout=5)
        if result.returncode: raise RuntimeError(result.stderr)
        return result.stdout
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and process.poll() is None:
        try:
            state=json.loads(ipc('state'))
            if state.get('catalog'): break
        except Exception: pass
        time.sleep(.2)
    else: raise RuntimeError((root/'preview.log').read_text())
    assert not state['error'],state
    clients=json.loads(subprocess.check_output(['hyprctl','-j','clients'],text=True))
    for client in clients:
        if client.get('pid')==process.pid:
            address=json.dumps('address:'+client['address'])
            subprocess.run(['hyprctl','eval','hl.dispatch(hl.dsp.window.float({window='+address+',action="on"})); hl.dispatch(hl.dsp.window.resize({window='+address+',x=1100,y=750}))'],check=True,capture_output=True)
    time.sleep(.3)
    ipc('snapshot',str(images / 'mirror-before.png'))
    time.sleep(.4)
    ipc('use')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=json.loads(ipc('state'))
        if state['previous']=='DP-1' and not state['busy'] and state['catalog']['displays'][0].get('mirror_of') == 'HDMI-A-1':
            break
        time.sleep(.1)
    assert state['previous']=='DP-1' and not state['error'], state
    ipc('snapshot',str(images / 'mirror-after.png'))
    time.sleep(.4)
    ipc('back')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=json.loads(ipc('state'))
        if state['previous']=='HDMI-A-1' and not state['busy'] and state['catalog']['displays'][1].get('mirror_of') == 'DP-1': break
        time.sleep(.1)
    assert state['previous']=='HDMI-A-1' and not state['error'],state
    print('PASS: real QML source action, status, Switch back and rendered previews')
    ipc('remove')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=json.loads(ipc('state'))
        if not state['busy'] and len(state['catalog']['displays']) == 2 and len(state['draft']['displays']) == 2: break
        time.sleep(.1)
    assert not state['error'] and not state['pending'], state
    assert len(state['catalog']['displays']) == len(state['draft']['displays']) == 2, state
    assert state['dirty'] and state['draft']['displays'][0]['scale'] == 2, state
    assert state['catalog']['displays'][0]['scale'] == 1.5, 'Removal must not save unrelated edits'
    print('PASS: real QML removal saves immediately, refreshes the list and retains unrelated unsaved edits without Preview or Keep')
    if args.screenshots: print('Panel images:', images)
except Exception:
    print((root / 'preview.log').read_text()[-2400:])
    raise
finally:
    process.terminate()
    process.wait(timeout=5)
    log.close()
    shutil.rmtree(root)
