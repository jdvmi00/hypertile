"""Session integration: remote sources remain owned by the stream controller."""
import json
import os
from pathlib import Path
import socket


def capture(desktop):
    path = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hypertile/streams/state.json"
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return desktop
    if state.get("version") != 1:
        raise ValueError("unsupported stream state version; session capture paused")
    sources, tokens = [], set()
    for r in state["computers"].values():
        if r.get("token"):
            tokens.add(("HYPERTILE_STREAM_TOKEN=" + r["token"]).encode())
        if r["desired"]:
            sources.append({"computer": r["computer"], "profile": r["profile"], **r["assignment"]})
    windows = []
    for w in desktop["windows"]:
        managed = bool(w.get("stream"))
        if tokens and w.get("pid"):
            try:
                env = (Path("/proc") / str(w["pid"]) / "environ").read_bytes().split(b"\0")
                managed = managed or bool(tokens.intersection(env))
            except OSError:
                pass
        if not managed:
            windows.append(w)
    desktop["windows"] = windows
    desktop["streams"] = sorted(sources, key=lambda s: s["computer"])
    desktop.pop("scene_content", None)  # Compositor addresses are not scene definitions.
    desktop["scenes"] = [{"workspace": workspace, "document": r["document"]}
                         for workspace, r in state.get("scenes", {}).items()
                         if r.get("document") and r.get("phase") != "restored"]
    addresses = {w["address"] for w in windows}
    for ws in desktop["workspaces"]:
        ws["order"] = [a for a in ws.get("order", []) if a in addresses]
    if desktop.get("active") not in addresses:
        desktop["active"] = None
    return desktop


def restore(sources, scenes=()):
    if not sources and not scenes:
        return []
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "hypertile-stream/control.sock"
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(1)
            client.connect(str(runtime))
            client.sendall(json.dumps({"command": "session-restore", "sources": sources, "scenes": scenes}).encode() + b"\n")
            # Submission is optional for local recovery. Stream state owns retries,
            # offline assignments and disconnect tombstones independently.
        return []
    except OSError:
        return ["Stream controller unavailable; local recovery continued. Remote assignments remain in the snapshot."]
