"""Private single-writer IPC for the scene service."""
import fcntl
import json
import os
import select
import signal
import socket
import subprocess
import time
from service import Compositor

def require(value, message):
    if not value:
        raise ValueError(message)


def request(runtime, payload, timeout=55):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout)
        client.connect(str(runtime / "control.sock"))
        client.sendall(json.dumps(payload).encode() + b"\n")
        data = bytearray()
        while not data.endswith(b"\n") and len(data) < 2_000_000:
            part = client.recv(65536)
            if not part:
                break
            data.extend(part)
        result = json.loads(data)
        require(result.get("ok"), result.get("error", "controller request failed"))
        return result["result"]


def daemon(root, runtime, config, factory):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(runtime, 0o700)
    with (root / "writer.lock").open("w") as lock:
        instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        require(instance, "start the controller inside the Hyprland session")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            previous = request(runtime, {"command": "status"})
            if previous.get("instance") == instance:
                return
            alive = subprocess.run(["hyprctl", "-i", previous["instance"], "version"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            require(alive.returncode != 0, "controller belongs to another running compositor")
            request(runtime, {"command": "stop"})
            for _ in range(50):
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.1)
            else:
                raise ValueError("previous controller has not stopped")
        controller = factory(root, config, Compositor(instance, runtime))
        def stop(*_):
            controller.running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        path = runtime / "control.sock"
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(16)
            try:
                next_tick = 0
                while controller.running:
                    if select.select([server], [], [], min(1, max(0, next_tick - time.monotonic())))[0]:
                        with server.accept()[0] as client:
                            client.settimeout(2)
                            try:
                                data = bytearray()
                                while not data.endswith(b"\n") and len(data) < 65536:
                                    part = client.recv(8192)
                                    if not part:
                                        break
                                    data.extend(part)
                                payload = json.loads(data)
                                result = {"ok": True, "result": controller.command(payload)}
                                if payload.get("command") not in ("status", "stop"):
                                    next_tick = 0
                            except Exception as error:
                                result = {"ok": False, "error": str(error)}
                            try:
                                client.sendall(json.dumps(result).encode() + b"\n")
                            except OSError:
                                pass  # Intent remains durable if the CLI disconnects.
                    if time.monotonic() >= next_tick:
                        try:
                            controller.tick()
                        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                            # A compositor outage must not erase sources or launch duplicates.
                            controller.applied.clear()
                        next_tick = time.monotonic() + controller.tick_interval()
            finally:
                path.unlink(missing_ok=True)
