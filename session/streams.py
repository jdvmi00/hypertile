"""Session integration for independent scenes and preserved legacy stream recovery."""
import copy
import json
import os
from pathlib import Path
import socket


def capture(desktop):
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hypertile"
    path = root / "streams/state.json"
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        state = {"version": 1, "computers": {}}
    if state.get("version") != 1:
        raise ValueError("unsupported stream state version; session capture paused")
    scene_path = root / "scenes/state.json"
    scene_state = json.loads(scene_path.read_text()) if scene_path.exists() else state
    if scene_state.get("version") != 1:
        raise ValueError("unsupported scene state version; session capture paused")
    if scene_state.get("browse", {}).get("active"):
        raise ValueError("layout preview is active; retaining the last committed session checkpoint")
    sources, tokens = [], set()
    for r in state["computers"].values():
        if r.get("token"):
            tokens.add(("HYPERTILE_STREAM_TOKEN=" + r["token"]).encode())
        if r["desired"]:
            sources.append({"computer": r["computer"], "profile": r["profile"], **r["assignment"]})
    scene_refs, scene_windows = [], set()
    for workspace, record in scene_state.get("scenes", {}).items():
        if not record.get("document") or record.get("phase") in ("restored", "waiting-session"):
            continue
        doc = copy.deepcopy(record["document"])
        for key, source in list(doc["sources"].items()):
            if source["type"] != "app":
                continue
            app = record.get("apps", {}).get(key, {})
            ref = app.get("window")
            window = next((w for w in desktop["windows"] if ref and all(w.get(k) == v for k, v in ref.items())), None)
            if app.get("status") in ("moved", "closed") or (ref and (not window or window["workspace"] != workspace or window.get("pin") != source["zone"] or window.get("floating"))):
                del doc["sources"][key]  # Recovery preserves user departures; saved definitions stay intact.
            elif window:
                scene_windows.add(window["address"])
            else:
                candidates = [w for w in desktop["windows"] if w.get("class") == source["app_class"]
                              and (not source.get("app_title") or w.get("title") == source["app_title"])]
                if len(candidates) > 1:
                    del doc["sources"][key]  # Preserve every unassigned peer through normal app recovery.
                elif candidates:
                    scene_windows.add(candidates[0]["address"])
        scene_refs.append({"workspace": workspace, "document": doc})
    windows = []
    for w in desktop["windows"]:
        managed = bool(w.get("stream")) or w["address"] in scene_windows
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
    desktop["scenes"] = scene_refs
    addresses = {w["address"] for w in windows}
    for ws in desktop["workspaces"]:
        ws["order"] = [a for a in ws.get("order", []) if a in addresses]
    if desktop.get("active") not in addresses:
        desktop["active"] = None
    return desktop


def restore(sources, scenes=()):
    warnings = []
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    # Keep source recovery available without coupling generic scenes to it.
    legacy = [r for r in scenes if any(s["type"] == "stream" for s in r["document"]["sources"].values())]
    if legacy:
        warnings.append("Legacy stream scenes need migration to installed app sources; their saved definitions were kept.")
    scenes = [r for r in scenes if r not in legacy]
    for entry, payload, label in (
        ("hypertile-stream", {"command": "session-restore", "sources": sources}, "Stream controller"),
        ("hypertile-scenes", {"command": "session-restore", "scenes": scenes}, "Scene service"),
    ):
        if not payload.get("sources") and not payload.get("scenes"):
            continue
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(1)
                client.connect(str(runtime / entry / "control.sock"))
                client.sendall(json.dumps(payload).encode() + b"\n")
                data = bytearray()
                while not data.endswith(b"\n") and len(data) < 65536:
                    part = client.recv(4096)
                    if not part:
                        break
                    data.extend(part)
                result = json.loads(data)
                if not result.get("ok"):
                    raise ValueError(result.get("error", "restore was refused"))
        except (OSError, ValueError) as error:
            warnings.append(label + " unavailable; local recovery continued. Saved assignments were kept. " + str(error))
    return warnings
