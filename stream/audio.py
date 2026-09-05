"""Mute only this managed client's local playback for a host-headset profile."""
import json
import shutil
import subprocess


def host_headset(pid, run=subprocess.run):
    if not shutil.which("pactl"):
        return {"state": "unverified", "error": "Install pactl or mute Moonlight locally for host-headset audio"}
    try:
        result = run(["pactl", "--format=json", "list", "sink-inputs"], capture_output=True, text=True, timeout=3, check=True)
        streams = [v for v in json.loads(result.stdout) if str(v.get("properties", {}).get("application.process.id")) == str(pid)]
        for stream in streams:
            if not stream.get("mute"):
                run(["pactl", "set-sink-input-mute", str(int(stream["index"])), "1"], capture_output=True, timeout=3, check=True)
        return {"state": "local-muted" if streams else "waiting-for-audio", "playback": "unverified"}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {"state": "unverified", "error": "Could not mute local playback: " + type(error).__name__}
