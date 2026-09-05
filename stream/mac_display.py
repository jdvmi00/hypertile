"""Typed Mac display operations, sent to the user's approved SSH account.

No persistent remote agent is installed. REQUEST is supplied by the client.
Only the display mode and Sunshine output_name can be changed.
"""
import json
import ctypes
import fcntl
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

BETTER = "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"


def same_setting(field, a, b):
    if field != "mode":
        return a == b
    # EDID/CLI mode lists round nominal timings (60 can read back as 59.95).
    return (isinstance(a, dict) and isinstance(b, dict) and a.get("resolution") == b.get("resolution")
            and a.get("hidpi") == b.get("hidpi")
            and (a["refresh"] == b["refresh"] or
                 (type(a["refresh"]) in (int, float) and type(b["refresh"]) in (int, float)
                  and abs(a["refresh"] - b["refresh"]) < .15)))


def manages_mode(display, observed):
    return display.get("adapter") != "macos" and (not display.get("follow_main") or observed["identity"]["UUID"].lower() == display["uuid"].lower())


def run(argv):
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
    if p.returncode or p.stdout.strip() == "Failed.":
        raise ValueError("display-operation-failed: check BetterDisplay, display connection and permissions")
    return p.stdout.strip()


def restart_sunshine():
    subprocess.run(["/usr/bin/pkill", "-TERM", "-x", "Sunshine"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(["/usr/bin/pgrep", "-x", "Sunshine"], stdout=subprocess.DEVNULL).returncode:
            break
        time.sleep(.1)
    else:
        raise ValueError("Sunshine did not stop; display restore may be pending")
    run(["/usr/bin/open", "/Applications/Sunshine.app"])


def lid_closed():
    result = run(["/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"])
    match = re.search(r'"AppleClamshellState"\s*=\s*(Yes|No)', result)
    return match[1] == "Yes" if match else None


def native_display():
    """Read the primary screen through CoreGraphics; never change its mode."""
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, list(args)
        return fn
    u32, ptr = ctypes.c_uint32, ctypes.c_void_p
    main = bind(cg, "CGMainDisplayID", u32)()
    if not bind(cg, "CGDisplayIsActive", u32, u32)(main):
        raise ValueError("display-missing: main display is inactive")
    # Native profiles own only the current capture output, not a persistent
    # physical display mode. Include the live ID and hardware identifiers so
    # a changed primary screen cannot reuse another screen's write guard.
    hardware = [bind(cg, name, u32, u32)(main) for name in
                ("CGDisplayVendorNumber", "CGDisplayModelNumber", "CGDisplaySerialNumber")]
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, "coregraphics:" + str([main, *hardware]))).upper()
    mode = bind(cg, "CGDisplayCopyDisplayMode", ptr, u32)(main)
    if not mode:
        raise ValueError("display-missing: main display has no mode")
    try:
        values = {key: bind(cg, "CGDisplayModeGet" + key, ctypes.c_size_t, ptr)(mode)
                  for key in ("Width", "Height", "PixelWidth", "PixelHeight")}
        refresh = bind(cg, "CGDisplayModeGetRefreshRate", ctypes.c_double, ptr)(mode)
    finally:
        bind(cg, "CGDisplayModeRelease", None, ptr)(mode)
    built_in = bool(bind(cg, "CGDisplayIsBuiltin", u32, u32)(main))
    return ({"UUID": identity, "displayID": str(main), "name": "Built-in Display" if built_in else "External Display"},
            {"resolution": f'{values["Width"]}x{values["Height"]}',
             "hidpi": values["PixelWidth"] > values["Width"],
             "refresh": refresh if refresh else "variable"},
            f'{values["PixelWidth"]}x{values["PixelHeight"]}')


def display(request):
    state = json.loads((Path.home() / ".config/sunshine/sunshine_state.json").read_text())
    identity = state.get("root", {}).get("uniqueid", "")
    if identity.lower() != request["pairing_uuid"].lower():
        raise ValueError("host-identity-mismatch: SSH host is not the paired Sunshine computer")
    native = request.get("adapter") == "macos"
    if native:
        ids, native_mode, render_resolution = native_display()
        identity = ids["UUID"]
        if request.get("expected_identity") and identity.lower() != request["expected_identity"].lower():
            raise ValueError("display-topology-changed: main display changed before the operation")
    else:
        graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        graphics.CGMainDisplayID.restype = ctypes.c_uint32
        identity = request["display_uuid"]
        if request.get("follow_main"):
            ids = json.loads(run([BETTER, "get", "-type=Display", "-displayID=" + str(graphics.CGMainDisplayID()), "-identifiers"]))
            identity = ids["UUID"]
        if request.get("expected_identity") and identity.lower() != request["expected_identity"].lower():
            raise ValueError("display-topology-changed: main display changed before the operation")
        if not re.fullmatch(r"[A-Fa-f0-9-]{36}", identity):
            raise ValueError("invalid display UUID")
        def get(key):
            # UUID alone also matches BetterDisplay's default display group.
            # Restrict all reads and writes to a physical Display before resolving.
            return run([BETTER, "get", "-type=Display", "-UUID=" + identity, "-" + key])
        try:
            ids = json.loads(get("identifiers"))
        except (ValueError, KeyError):
            raise ValueError("display-missing: selected display is unavailable") from None
        if not isinstance(ids, dict) or ids.get("UUID", "").lower() != identity.lower():
            raise ValueError("display-missing: no unique UUID match")
        graphics.CGDisplayIsActive.argtypes = [ctypes.c_uint32]
        graphics.CGDisplayIsActive.restype = ctypes.c_uint32
        if not graphics.CGDisplayIsActive(int(ids["displayID"])):
            raise ValueError("display-missing: selected display is disconnected")
    config = Path.home() / ".config/sunshine/sunshine.conf"
    text = config.read_text()
    outputs = re.findall(r"^\s*output_name\s*=\s*(.*?)\s*$", text, re.M)
    if len(outputs) > 1:
        raise ValueError("display-configuration-invalid: duplicate output_name")
    def get_mode():
        if native:
            return native_mode
        refresh = get("refreshRate")
        return {"resolution": get("resolution"), "hidpi": get("hiDPI") == "on",
                "refresh": refresh if refresh == "ProMotion" else float(refresh.removesuffix("Hz"))}
    mode = get_mode()
    current = {"mode": mode, "output": outputs[0] if outputs else None}
    if request["operation"] == "probe":
        modes = []
        for line in ([] if native else get("displayModeList").splitlines()):
            m = re.fullmatch(r"\d+ - (\d+x\d+)( HiDPI)? (\d+(?:\.\d+)?)Hz.*", line.strip())
            if m:
                modes.append({"resolution": m[1], "hidpi": bool(m[2]), "refresh": float(m[3])})
        power = run(["/usr/bin/pmset", "-g", "batt"])
        return {"identity": ids, "current": current, "modes": modes,
                "topology": {"lid_closed": lid_closed(), "display_id": ids["displayID"], "display_uuid": identity},
                "sunshine_uuid": request["pairing_uuid"],
                "ac_power": "AC Power" in power, "permissions": "unknown",
                "render_resolution": render_resolution if native else "x".join(str(int(v) * (2 if mode["hidpi"] else 1)) for v in mode["resolution"].split("x"))}
    if request["operation"] == "refresh":
        if not all(same_setting(k, current[k], request["expected"][k]) for k in current):
            raise ValueError("restore-conflict: capture changed before refreshing input")
        restart_sunshine()
        return {"refreshed": ids["displayID"]}
    field, expected, value = request["field"], request["expected"], request["value"]
    # Compare and change in one remote invocation; preserve a manual change.
    if field not in current or not same_setting(field, current[field], expected):
        raise ValueError("restore-conflict: current setting differs from the journal")
    if field == "mode":
        if native:
            raise ValueError("unsupported display field: native desktop preserves the host mode")
        if not re.fullmatch(r"[0-9]{3,5}x[0-9]{3,5}", value["resolution"]):
            raise ValueError("invalid resolution")
        if type(value["hidpi"]) is not bool or not (value["refresh"] == "ProMotion" or
                (type(value["refresh"]) in (int, float) and 20 <= value["refresh"] <= 240)):
            raise ValueError("invalid display mode")
        run([BETTER, "set", "-type=Display", "-UUID=" + identity, "-resolution=" + value["resolution"],
             "-hiDPI=" + ("on" if value["hidpi"] else "off"), "-refreshRate=" + str(value["refresh"])])
        if not same_setting("mode", get_mode(), value):
            raise ValueError("display-readback-failed: restoration required")
        # Sunshine's macOS input context caches displayScaling at startup.
        # A mode switch must refresh it even when output_name stays the same.
        restart_sunshine()
    elif field == "output":
        if value is not None and not re.fullmatch(r"\d{1,10}", value):
            raise ValueError("invalid capture output")
        updated = re.sub(r"^\s*output_name\s*=.*\n?", "", text, flags=re.M)
        if value is not None:
            updated = updated.rstrip() + "\noutput_name = " + value + "\n"
        fd, path = tempfile.mkstemp(dir=config.parent)
        try:
            with os.fdopen(fd, "w") as out:
                out.write(updated)
                out.flush()
                os.fsync(out.fileno())
            os.replace(path, config)
        finally:
            if os.path.exists(path):
                os.unlink(path)
        restart_sunshine()
    else:
        raise ValueError("unsupported display field")
    return {"changed": field}


if __name__ == "__main__":
    try:
        # A client timeout can leave a remote operation finishing its write.
        # Serialize probes too: restoration cannot observe the old value and
        # discard its journal while an earlier write is still in flight.
        with (Path.home() / ".config/sunshine/hypertile-display.lock").open("a") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = display(REQUEST)
        print(json.dumps({"ok": True, "result": result}))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
