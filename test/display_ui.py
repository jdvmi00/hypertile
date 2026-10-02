"""Opt-in Displays QML smoke test with simulated outputs, on an Omarchy session.

No physical display or user configuration is changed. A disposable preview
window exercises the automatic refresh, immediate switching, saved-display
removal, catalog refresh, and Switch back.
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
    displays[-1]['automatic_modes'] = [dict(width=width, height=height, refresh=60,
        mode_policy='highres', label='Automatic (highest resolution)')]
displays[1]['mirror_of']='DP-1'
displays.append(dict(displays[0], id='old-display', connector='OLD-DP', connected=False, mirror_of=None))
(root/'state.json').write_text(json.dumps(dict(version=1,displays=displays,workspaces=[],confirmed=dict(workspaces={}),pending=None)))
ctl=root/'ctl'
ctl.write_text('''#!/usr/bin/env python3
import json, sys, time
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
elif sys.argv[2]=='list':
    hold = path.with_name('hold-list')
    if hold.exists():
        path.with_name('list-started').touch()
        deadline = time.monotonic() + 10
        while hold.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        path.with_name('list-released').touch()
    result=state
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
    QtObject {
        id: probe
        property int drafts: 0
        function find(label) {
            var items = [pane];
            while (items.length) {
                var item = items.pop();
                if (item.accessibleLabel === label)
                    return item;
                for (var i = 0; item.children && i < item.children.length; i++)
                    items.push(item.children[i]);
            }
            return null;
        }
    }
    Connections {
        target: pane
        function onDraftChanged() { probe.drafts++; }
    }
    IpcHandler {
        target: "preview"
        function state(): string { return JSON.stringify({catalog:pane.catalog,draft:pane.draft,dirty:pane.dirty,pending:pane.pending,previous:pane.previousSource,error:pane.error,notice:pane.notice,busy:pane.busy,drafts:probe.drafts,engaged:!!pane.engaged}); }
        // A half-typed coordinate: "-" is not yet a number, so nothing commits.
        function select(index: int): void { pane.selectedIndex = index; }
        function refresh(): void { pane.refresh(); }
        function type(): string {
            var field = probe.find("X position");
            field.remove(0, field.length);
            field.insert(0, "-");
            field.textEdited();
            return field.text;
        }
        function typed(): string { return probe.find("X position").text; }
        function leave(): void { probe.find("X position").editingFinished(); }
        function list(open: bool): void {
            var popup = probe.find("Display rotation").popup;
            if (open) popup.open(); else popup.close();
        }
        function use(): void { pane.useDisplay(pane.selectedDisplay.connector); }
        function back(): void { pane.useDisplay(pane.previousSource); }
        function automatic(): string {
            pane.selectedIndex = 0;
            var items = [pane];
            while (items.length) {
                var item = items.pop();
                if (item.accessibleLabel === "Resolution and refresh rate") {
                    item.activated(0);
                    item.forceActiveFocus();
                    Qt.callLater(function() { pane.reveal(item); });
                    return item.displayText;
                }
                for (var i = 0; item.children && i < item.children.length; i++)
                    items.push(item.children[i]);
            }
            return "missing mode picker";
        }
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
    def move(x):
        external = json.loads((root/'state.json').read_text())
        external['displays'][0]['x'] = x
        (root/'state.json').write_text(json.dumps(external))
    def settled(condition):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            state = json.loads(ipc('state'))
            if condition(state): return state
            time.sleep(.2)
        raise AssertionError(state)
    drafts = json.loads(ipc('state'))['drafts']
    time.sleep(4.5)
    assert json.loads(ipc('state'))['drafts'] == drafts, 'An unchanged catalog must not replace the draft'
    move(640)
    settled(lambda s: s['draft']['displays'][0]['x'] == 640 and not s['dirty'])
    ipc('select', '0')
    assert ipc('type').strip() == '-'
    move(0)
    time.sleep(4.5)
    state = json.loads(ipc('state'))
    assert state['engaged'] and state['draft']['displays'][0]['x'] == 640 and ipc('typed').strip() == '-', state
    ipc('leave')
    state = settled(lambda s: s['draft']['displays'][0]['x'] == 0)
    assert not state['engaged'] and not state['dirty'] and ipc('typed').strip() == '0', state
    ipc('list', 'true')
    move(640)
    time.sleep(4.5)
    state = json.loads(ipc('state'))
    assert state['engaged'] and state['draft']['displays'][0]['x'] == 0, state
    ipc('list', 'false')
    move(0)
    time.sleep(.3)
    state = settled(lambda s: not s['engaged'] and s['catalog']['displays'][0]['x'] == 0 and s['draft']['displays'][0]['x'] == 0)
    for editing in ('field', 'list'):
        # Start input only after the service has captured a changed catalog,
        # then release its response while the control is still in use.
        hold = root / 'hold-list'
        started = root / 'list-started'
        released = root / 'list-released'
        started.unlink(missing_ok=True)
        released.unlink(missing_ok=True)
        hold.touch()
        move(640)
        ipc('refresh')
        settled(lambda s: started.exists())
        if editing == 'field':
            assert ipc('type').strip() == '-'
        else:
            ipc('list', 'true')
        hold.unlink()
        settled(lambda s: released.exists())
        # Allow the released response and another timer tick to be handled.
        time.sleep(2.5)
        state = json.loads(ipc('state'))
        assert state['engaged'] and not state['dirty'], state
        assert state['catalog']['displays'][0]['x'] == state['draft']['displays'][0]['x'] == 0, state
        if editing == 'field':
            assert ipc('typed').strip() == '-'
            ipc('leave')
        else:
            ipc('list', 'false')
        settled(lambda s: s['catalog']['displays'][0]['x'] == s['draft']['displays'][0]['x'] == 640)
        move(0)
        settled(lambda s: s['catalog']['displays'][0]['x'] == s['draft']['displays'][0]['x'] == 0)
    ipc('select', '1')
    print('PASS: the open pane follows external changes, keeps an unchanged draft, and defers new or in-flight refreshes during input')
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
    assert 'Automatic (highest resolution)' in ipc('automatic')
    state = json.loads(ipc('state'))
    assert state['draft']['displays'][0]['mode_policy'] == 'highres' and state['dirty'], state
    time.sleep(.2)
    ipc('snapshot', str(images / 'automatic-mode.png'))
    time.sleep(.4)
    print('PASS: automatic mode selection updates the real QML draft and rendered inspector')
    if args.screenshots: print('Panel images:', images)
except Exception:
    print((root / 'preview.log').read_text()[-2400:])
    raise
finally:
    process.terminate()
    process.wait(timeout=5)
    log.close()
    shutil.rmtree(root)
