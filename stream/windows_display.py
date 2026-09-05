"""Typed transport to the Windows console-session display helper.

SSH only submits bounded JSON operations to a private mailbox. The installed
helper owns display writes, journals and offline recovery on the laptop.
"""
import base64
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = r"C:\ProgramData\Hypertile\display"
ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def powershell(alias, script, timeout=35):
    if not ALIAS.fullmatch(alias):
        raise ValueError("invalid Windows SSH alias")
    if len(script.encode("utf-8")) > 4096:
        # Windows OpenSSH can leave large stdin submissions waiting for EOF.
        # Stage installation packages with SFTP; runtime requests stay small.
        stage = "C:/ProgramData/Hypertile/setup-" + uuid.uuid4().hex
        powershell(alias, "$ErrorActionPreference='Stop'; $p='" + stage + "'; New-Item -ItemType Directory -Path $p -Force | Out-Null; "
                   "icacls.exe $p /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' | Out-Null; "
                   "if ($LASTEXITCODE -ne 0) {throw 'Cannot protect installation package'}; @{ok=$true} | ConvertTo-Json -Compress")
        try:
            with tempfile.NamedTemporaryFile(suffix=".ps1") as source:
                source.write(script.encode("utf-8")); source.flush()
                p = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                                    source.name, alias + ":" + stage + "/Install.ps1"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                if p.returncode:
                    raise ValueError("Windows display package transfer failed")
            return powershell(alias, "& '" + stage + "/Install.ps1'", timeout=timeout)
        finally:
            powershell(alias, "Remove-Item -LiteralPath '" + stage + "' -Recurse -Force; @{ok=$true} | ConvertTo-Json -Compress")
    # stdin avoids Windows cmd.exe's command-line length limit. No password,
    # interpolated shell command or machine-specific key is stored in a scene.
    launcher = "& ([ScriptBlock]::Create([Console]::In.ReadToEnd()))"
    encoded = base64.b64encode(launcher.encode("utf-16le")).decode()
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                        "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR", alias,
                        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                       input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode:
        raise ValueError("host-unreachable: Windows SSH/helper unavailable")
    try:
        return json.loads(p.stdout.lstrip("\ufeff"))
    except ValueError:
        raise ValueError("display-probe-failed: invalid Windows helper reply") from None


def remote(computer, display, operation, **values):
    if operation not in ("probe", "status", "prepare", "restore"):
        raise ValueError("unsupported Windows display operation")
    request = {"version": 1, "operation": operation, "pairing_uuid": computer["pairing_uuid"],
               "capture_id": display["device_id"], "expires": int(time.time()) + 60, **values}
    payload = base64.b64encode(json.dumps(request).encode()).decode()
    script = r"""$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\Hypertile\display'
try {
 $status=Get-Content (Join-Path $root 'status.json') -Raw | ConvertFrom-Json
 if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$status.observed_at -gt 10) {throw 'display-helper-unavailable: console helper stopped'}
 $request=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
 if ($request.pairing_uuid -ine $status.pairing_uuid -or $request.capture_id -ine $status.capture_id) {throw 'host-identity-mismatch'}
 if ($request.operation -in @('status','probe')) {
  @{ok=$true;result=$status} | ConvertTo-Json -Depth 12 -Compress
 } else {
  $id=[guid]::NewGuid().ToString('N')+'.json'
  $path=Join-Path $root ('requests\'+$id)
  $tmp=$path+'.tmp'
  [IO.File]::WriteAllText($tmp,($request | ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
  [IO.File]::Move($tmp,$path)
  $response=Join-Path $root ('responses\'+$id)
  $until=(Get-Date).AddSeconds(25)
  while (-not (Test-Path $response) -and (Get-Date) -lt $until) {Start-Sleep -Milliseconds 200}
  if (-not (Test-Path $response)) {throw 'display-helper-timeout: operation may still finish; restoration is required'}
  Get-Content $response -Raw
  Remove-Item $response
 }
} catch {@{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress}
""".replace("__PAYLOAD__", payload)
    response = powershell(computer["ssh"]["alias"], script)
    if not response.get("ok"):
        raise ValueError(response.get("error", "Windows display operation failed"))
    result = response["result"]
    if result.get("pairing_uuid", "").lower() != computer["pairing_uuid"].lower() or result.get("capture_id", "").lower() != display["device_id"].lower():
        raise ValueError("host-identity-mismatch")
    return result


def prepare(record, host, persist):
    journal = record.setdefault("journal", {})
    entry = journal.setdefault("windows", {"owner": uuid.uuid4().hex, "sequence": 0, "phase": "intent"})
    entry["sequence"] += 1
    persist()  # Includes the owner even if SSH times out after the host write.
    result = host.remote("prepare", owner=entry["owner"], sequence=entry["sequence"])
    active = result.get("active", [])
    if result.get("owner") != entry["owner"] or result.get("phase") not in ("preparing", "streaming") or len(active) != 1 or active[0]["id"].lower() != host.display["device_id"].lower():
        raise ValueError("display-readback-failed: Windows recovery required")
    entry["phase"] = "applied"
    record["resolved"] = {**record.get("resolved", {}), "restoration": "managed", "display": result}
    persist()


def restore(record, host, persist):
    entry = record.get("journal", {}).get("windows")
    if not entry:
        return True
    if entry["phase"] != "restoring":
        entry["sequence"] += 1
        # Persist sequence first, but keep retrying the same restore after a lost
        # acknowledgement. A status read alone cannot cancel a late preparation.
        persist()
        result = host.remote("restore", owner=entry["owner"], sequence=entry["sequence"])
        entry["phase"] = "restoring"
        persist()
    else:
        result = host.remote("status")
    record["resolved"] = {**record.get("resolved", {}), "display": result}
    active = result.get("active", [])
    physical = active and all(d["id"].lower() != host.display["device_id"].lower() for d in active)
    if result.get("phase") == "idle" and not result.get("error") and physical:
        del record["journal"]["windows"]
        persist()
        return True
    return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Install the narrowly scoped Windows display helper over approved SSH")
    parser.add_argument("--ssh", required=True)
    parser.add_argument("--pairing-uuid", required=True)
    parser.add_argument("--output-uuid", required=True)
    parser.add_argument("--capture-hardware", required=True, help="Exact EDID hardware ID, for example MTT1337")
    args = parser.parse_args()
    for value in (args.pairing_uuid, args.output_uuid.strip("{}")):
        if not re.fullmatch(r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}", value):
            parser.error("invalid Sunshine UUID")
    if not re.fullmatch(r"[A-Z0-9]{7}", args.capture_hardware):
        parser.error("invalid EDID hardware ID")
    folder = Path(__file__).with_name("windows")
    package = {"files": {p.name: base64.b64encode(p.read_bytes()).decode() for p in folder.iterdir()
                         if p.name in ("Guard.ps1", "Policy.ps1", "Display.cs", "Test.ps1")},
               "pairing_uuid": args.pairing_uuid, "output_uuid": "{" + args.output_uuid.strip("{}") + "}",
               "capture_hardware": args.capture_hardware}
    payload = base64.b64encode(json.dumps(package).encode()).decode()
    script = "$package=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "')) | ConvertFrom-Json\n"
    script += "try {\n" + (folder / "Install.ps1").read_text() + "\n} catch { @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress }\n"
    print(json.dumps(powershell(args.ssh, script, timeout=90), indent=2))
