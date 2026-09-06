"""Retire known legacy runtime files; never remove configuration or journals.

Callers must hold the shared legacy writer lock before checking or deleting.
Remote Desktops holds the same shared lock; the old controller requires EX.
"""
import json
from pathlib import Path

def check_legacy(state):
    path = state / "streams/state.json"
    if not path.exists():
        return
    value = json.loads(path.read_text())
    if value.get("version") != 1 or not isinstance(value.get("computers"), dict):
        raise ValueError("Unrecognized legacy state; preserve its recovery tools before upgrading")
    pending = [name for name, record in value["computers"].items() if record.get("desired") or record.get("journal")]
    if pending:
        raise ValueError("Disconnect/restore legacy Hypertile connections before upgrading: " + ", ".join(pending))

def obsolete(bin_dir, data):
    root = data / "hypertile"
    paths = [bin_dir / "hypertile-stream", root / "session/streams.py"]
    paths += [root / "stream" / (name + ".py") for name in
              ("controller", "mac_display", "windows_display", "audio", "quality", "scenes", "scene_service", "apps", "browse", "ipc")]
    paths += [root / "stream/windows" / name for name in
              ("Guard.ps1", "Policy.ps1", "Display.cs", "Test.ps1", "Install.ps1")]
    return paths

def cleanup(bin_dir, data):
    for path in obsolete(bin_dir, data):
        path.unlink(missing_ok=True)
