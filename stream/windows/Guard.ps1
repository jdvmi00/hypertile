# Runs only in the configured user's console session. Fixed display operations;
# requests cannot contain code, paths, process names, or arbitrary commands.
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=$PSScriptRoot
. (Join-Path $root 'Policy.ps1')
Add-Type -Path (Join-Path $root 'Display.cs')
$config=Get-Content (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
$mutex=[Threading.Mutex]::new($false,'Local\HypertileDisplayGuard')
try {$locked=$mutex.WaitOne(0)} catch [Threading.AbandonedMutexException] {$locked=$true}
if (-not $locked) {exit 0}
function Write-Json($Path,$Value) {
    $tmp=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($tmp,($Value | ConvertTo-Json -Depth 16),[Text.UTF8Encoding]::new($false))
    if (Test-Path $Path) {[IO.File]::Replace($tmp,$Path,[NullString]::Value)} else {[IO.File]::Move($tmp,$Path)}
}
$statePath=Join-Path $root 'state.json'
$state=@{version=1;owner='';sequence=0;phase='idle';baseline=$null;retired=@();ever_owned=$false;deadline=0;error=$null}
if (Test-Path $statePath) {
    $saved=Get-Content $statePath -Raw | ConvertFrom-Json
    foreach($p in $saved.PSObject.Properties) {$state[$p.Name]=$p.Value}
}
function Save-State {Write-Json $statePath $state}
function Now {return [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
function Assert-Identity {
    $sunshine=Get-Content (Join-Path $config.sunshine_config 'sunshine_state.json') -Raw | ConvertFrom-Json
    if ($sunshine.root.uniqueid -ine $config.pairing_uuid) {throw 'host-identity-mismatch'}
    $conf=Get-Content (Join-Path $config.sunshine_config 'sunshine.conf') -Raw
    if ($conf -notmatch '(?m)^dd_configuration_option\s*=\s*disabled\s*$') {throw 'display-owner-conflict: Sunshine display automation must remain disabled'}
    $output=[regex]::Matches($conf,'(?m)^output_name\s*=\s*([^\r\n]+)')
    if ($output.Count -ne 1 -or $output[0].Groups[1].Value.Trim() -ine $config.output_uuid) {throw 'capture-display-changed'}
    if ($conf -match '(?m)^min_log_level\s*=\s*(warning|error|fatal|none)') {throw 'stream-observation-unavailable: Sunshine must log connection events'}
}
function Get-Activity {
    if (-not (Get-Process sunshine -ErrorAction SilentlyContinue | Where-Object {$_.SessionId -eq (Get-Process -Id $PID).SessionId})) {return 0}
    # Unknown/truncated logs block recovery rather than guessing idle.
    return Get-SunshineActivity @(Get-Content (Join-Path $config.sunshine_config 'sunshine.log') -Tail 12000) (Now)
}
function View($Devices) {
    return @{version=1;owner=$state.owner;sequence=$state.sequence;phase=$state.phase;error=$state.error;
        active=@($Devices | Where-Object {$_.active});available=@($Devices | Where-Object {$_.available});
        capture_id=$config.capture_id;pairing_uuid=$config.pairing_uuid;observed_at=(Now)}
}
function Recover {
    $devices=@([HypertileDisplay]::Inspect())
    $ids=@(); if ($state.baseline) {$ids=@($state.baseline.ids | Where-Object {$_ -ine $config.capture_id})}
    $choice=Get-RecoveryChoice $devices $config.capture_id $ids
    if ($choice.action -eq 'pending') {$state.phase='restore-pending';$state.error='physical-display-unavailable: open the lid or attach a monitor';return}
    $captureActive=@($devices | Where-Object {$_.active -and $_.id -ieq $config.capture_id}).Count -gt 0
    if ($choice.action -eq 'keep-physical') {
        if ($captureActive) {[HypertileDisplay]::Remove($config.capture_id)}
    } elseif ($choice.action -eq 'baseline') {
        try {[HypertileDisplay]::Restore($state.baseline.paths,$state.baseline.modes)}
        catch {
            # Dock changes can invalidate adapter/source IDs despite the same
            # monitor identity. Recover one verified physical output in that case.
            $fallback=@($devices | Where-Object {$_.available -and $_.id -ine $config.capture_id} | Sort-Object internalPanel -Descending)[0]
            [HypertileDisplay]::Only($fallback.id,$true)
        }
    } else {[HypertileDisplay]::Only($choice.ids[0],$true)}
    $after=@([HypertileDisplay]::Inspect() | Where-Object {$_.active})
    if ($after.Count -eq 0 -or @($after | Where-Object {$_.id -ieq $config.capture_id}).Count -gt 0) {throw 'restore-readback-failed'}
    $state.phase='idle';$state.error=$null
}
function Handle($Request) {
    if ($Request.version -ne 1 -or $Request.pairing_uuid -ine $config.pairing_uuid -or $Request.capture_id -ine $config.capture_id) {throw 'host-identity-mismatch'}
    if ($Request.expires -lt (Now) -or $Request.expires -gt ((Now)+90)) {throw 'request-expired'}
    if ($Request.operation -notin @('probe','prepare','restore','status')) {throw 'unsupported-operation'}
    Assert-Identity
    if ($Request.operation -in @('probe','status')) {return (View @([HypertileDisplay]::Inspect()))}
    if ($Request.owner -cnotmatch '^[0-9a-f]{32}$' -or $Request.sequence -isnot [int] -or $Request.sequence -lt 1) {throw 'invalid-operation-token'}
    $state.retired=@($state.retired | Where-Object {$_.expires -gt (Now)})
    if ($Request.operation -eq 'prepare' -and $Request.owner -in @($state.retired.owner)) {throw 'operation-cancelled'}
    if ($state.owner -eq $Request.owner -and $Request.sequence -le $state.sequence) {
        if ($Request.sequence -eq $state.sequence) {return (View @([HypertileDisplay]::Inspect()))}
        throw 'stale-operation'
    }
    if ($Request.operation -eq 'restore') {
        if ($state.owner -ne $Request.owner -and $state.phase -ne 'idle') {throw 'display-owned-by-another-session'}
        # Tombstone before restoring; a delayed preparation cannot resurrect it.
        $state.retired=@($state.retired | Where-Object {$_.owner -ne $Request.owner})+@(@{owner=$Request.owner;expires=(Now)+120})
        if ($state.owner -ne $Request.owner -and $state.phase -eq 'idle') {Save-State;return (View @([HypertileDisplay]::Inspect()))}
        if ($state.owner -eq $Request.owner) {$state.sequence=$Request.sequence}
        $state.phase='restore-pending';$state.deadline=(Now)+2;Save-State
    } else {
        if ($state.owner -ne $Request.owner -and $state.phase -ne 'idle') {throw 'restore-pending: finish the previous session first'}
        $active=Get-Activity
        if ($null -eq $active) {throw 'stream-observation-unavailable'}
        if ($active -gt 0 -and $state.owner -ne $Request.owner) {throw 'another-stream-is-active'}
        if ($state.owner -ne $Request.owner) {
            $baseline=[HypertileDisplay]::Capture()
            if ($baseline.ids -contains $config.capture_id) {throw 'unmanaged-virtual-display: recover physical displays before connecting'}
            $state.baseline=$baseline
        }
        $state.owner=$Request.owner;$state.sequence=$Request.sequence;$state.phase='preparing';$state.deadline=(Now)+45;$state.error=$null;$state.ever_owned=$true
        Save-State
        [HypertileDisplay]::Only($config.capture_id,$false)
        $after=@([HypertileDisplay]::Inspect() | Where-Object {$_.active})
        if ($after.Count -ne 1 -or $after[0].id -ine $config.capture_id) {throw 'display-readback-failed'}
        Save-State
    }
    return (View @([HypertileDisplay]::Inspect()))
}
try {
    while($true) {
        $changed=$state | ConvertTo-Json -Depth 16 -Compress
        foreach($file in @(Get-ChildItem (Join-Path $root 'requests') -Filter '*.json' | Sort-Object Name)) {
            $reply=Join-Path $root ('responses\'+$file.Name)
            try {
                if ($file.Length -gt 8192) {throw 'request-too-large'}
                $request=Get-Content $file.FullName -Raw | ConvertFrom-Json
                $result=Handle $request
                Write-Json $reply @{ok=$true;result=$result}
            } catch {Write-Json $reply @{ok=$false;error=$_.Exception.Message}}
            Remove-Item -LiteralPath $file.FullName
        }
        try {
            Assert-Identity
            $activity=Get-Activity
            $devices=@([HypertileDisplay]::Inspect())
            if ($null -eq $activity) {$state.error='stream-observation-unavailable: cannot confirm Sunshine is idle'}
            if ($activity -gt 0) {
                if ($state.phase -in @('preparing','streaming')) {$state.phase='streaming';$state.deadline=(Now)+15}
                # Never restore during any active stream, including one not ours.
            } elseif ($null -ne $activity -and $state.ever_owned -and (Now) -ge $state.deadline) {
                $virtualActive=@($devices | Where-Object {$_.active -and $_.id -ieq $config.capture_id}).Count -gt 0
                if ($state.phase -ne 'idle' -or $virtualActive) {Recover}
            }
            if ($state.phase -eq 'streaming') {
                $active=@($devices | Where-Object {$_.active})
                if ($active.Count -ne 1 -or $active[0].id -ine $config.capture_id) {$state.error='display-conflict: display layout changed during streaming'} else {$state.error=$null}
            }
            Write-Json (Join-Path $root 'status.json') (View @([HypertileDisplay]::Inspect()))
        } catch {
            $state.error=$_.Exception.Message
            if ($state.phase -notin @('idle','streaming','preparing')) {$state.phase='restore-pending'}
            Write-Json (Join-Path $root 'status.json') @{version=1;phase=$state.phase;owner=$state.owner;error=$state.error;observed_at=(Now);pairing_uuid=$config.pairing_uuid;capture_id=$config.capture_id}
        }
        if (($state | ConvertTo-Json -Depth 16 -Compress) -ne $changed) {Save-State}
        Get-ChildItem (Join-Path $root 'responses') -Filter '*.json' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 64 | Remove-Item
        Start-Sleep -Seconds 2
    }
} finally {$mutex.ReleaseMutex();$mutex.Dispose()}
