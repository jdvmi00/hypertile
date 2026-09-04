#!/usr/bin/env python3
"""Check a built compositor without affecting the desktop.

Usage: python3 headless-check.py /absolute/path/to/Hyprland /absolute/path/to/check.so
Requires foot, hyprctl, and the matching headless-ack-check.cpp plugin build.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

binary, plugin = (str(Path(p).resolve()) for p in sys.argv[1:3])
with tempfile.TemporaryDirectory(prefix="ht-") as directory:
    root = Path(directory)
    runtime = root / "r"
    runtime.mkdir(mode=0o700)
    config = root / "test.lua"
    config.write_text('''hl.monitor({output="HEADLESS-1", mode="1920x1080@60", position="0x0", scale=1})
hl.monitor({output="", disabled=true})
hl.config({animations={enabled=false}, xwayland={enabled=false}, misc={disable_hyprland_logo=true, disable_splash_rendering=true}})
''')
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), HYPRLAND_HEADLESS_ONLY="1",
               HYPRLAND_NO_SD_VARS="1", HYPRLAND_NO_SD_NOTIFY="1")
    for name in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "NOTIFY_SOCKET"):
        env.pop(name, None)
    # Aquamarine 0.14 needs a renderer from a parent Wayland backend even
    # when the test uses only headless outputs. Disable that backend's output.
    parent = Path(os.environ["WAYLAND_DISPLAY"])
    if not parent.is_absolute():
        parent = Path(os.environ["XDG_RUNTIME_DIR"]) / parent
    env["WAYLAND_DISPLAY"] = str(parent)
    client = None
    with (root / "compositor.log").open("w+") as log:
        compositor = subprocess.Popen([binary, "--config", str(config)], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            instances = []
            while time.monotonic() < deadline and compositor.poll() is None:
                result = subprocess.run(["hyprctl", "instances", "-j"], env=env, capture_output=True, text=True)
                if result.returncode == 0:
                    try:
                        instances = [i for i in json.loads(result.stdout) if i["pid"] == compositor.pid]
                    except json.JSONDecodeError:
                        instances = []  # hyprctl may print a non-JSON notice before the socket exists.
                    if instances and (runtime / "hypr" / instances[0]["instance"] / ".socket.sock").exists():
                        break
                time.sleep(.1)
            assert instances and compositor.poll() is None, "Headless compositor did not start"
            env["HYPRLAND_INSTANCE_SIGNATURE"] = instances[0]["instance"]
            env["WAYLAND_DISPLAY"] = instances[0]["wl_socket"]

            def ctl(*args):
                result = subprocess.run(["hyprctl", *args], env=env, capture_output=True, text=True, timeout=10)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                return result.stdout

            monitors = json.loads(ctl("monitors", "-j"))
            if not monitors:
                ctl("output", "create", "headless", "HEADLESS-1")
                monitors = json.loads(ctl("monitors", "-j"))
            assert monitors and all(m["name"].startswith("HEADLESS") for m in monitors), "Unexpected physical output"
            assert not ctl("configerrors").strip(), "Headless config errors"
            client = subprocess.Popen(["foot", "--app-id=hypertile-backport-smoke", "sh", "-c", "sleep 60"],
                                      env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if any(w["class"] == "hypertile-backport-smoke" for w in json.loads(ctl("clients", "-j"))):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError("Headless test client did not map")
            ctl("plugin", "load", plugin)
            plugins = json.loads(ctl("plugin", "list", "-j"))
            assert any(p["name"] == "hypertile-ack-check" for p in plugins), "Compiled onAck regression failed"
            ctl("plugin", "unload", plugin)
            print("PASS: packaged compositor starts headlessly, maps a Wayland client, preserves both future records,")
            print("      and acknowledges 2218x1246 through its compiled onAck handler. Diagnostic unloaded.")
        except Exception:
            log.flush()
            log.seek(0)
            print(log.read()[-12000:], file=sys.stderr)
            raise
        finally:
            for process in (client, compositor):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
