# Pure selection policy, also exercised without changing real displays.
function Get-RecoveryChoice($Devices, $CaptureId, $BaselineIds) {
    $physical=@($Devices | Where-Object {$_.id -ine $CaptureId -and $_.available})
    $active=@($physical | Where-Object {$_.active})
    if ($active.Count -gt 0) { return @{action='keep-physical'; ids=@($active.id)} }
    if ($BaselineIds.Count -gt 0 -and @($BaselineIds | Where-Object {$_ -notin $physical.id}).Count -eq 0) {
        return @{action='baseline'; ids=@($BaselineIds)}
    }
    $internal=@($physical | Where-Object {$_.internalPanel})
    if ($internal.Count -gt 0) { return @{action='single'; ids=@($internal[0].id)} }
    if ($physical.Count -gt 0) { return @{action='single'; ids=@($physical[0].id)} }
    return @{action='pending'; ids=@()}
}

function Get-SunshineActivity($Lines, $NowSeconds) {
    $count=$null; $pending=@()
    foreach($line in $Lines) {
        if ($line -match 'Sunshine version:') {$count=0;$pending=@()}
        if ($line -match 'New streaming session started \[active sessions: (\d+)\]') {
            $slots=[int]$Matches[1]
            # Session slots can still include a disconnected client whose worker
            # is shutting down. Count actual connection events, not those slots.
            if ($null -eq $count -and $slots -eq 1) {$count=0}
            if ($line -match '^\[([^\]]+)\]') {
                try {
                    $date=[DateTime]::ParseExact($Matches[1],'yyyy-MM-dd HH:mm:ss.fff',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::AssumeLocal)
                    $pending+=([DateTimeOffset]$date).ToUnixTimeSeconds()+45
                } catch {return $null}
            } else {return $null}
        }
        if ($line -match 'CLIENT CONNECTED') {
            if ($null -ne $count) {$count++}
            if ($pending.Count) {$pending=@($pending | Select-Object -Skip 1)}
        }
        if ($line -match 'CLIENT DISCONNECTED' -and $null -ne $count) {$count=[Math]::Max(0,$count-1)}
        if ($line -match ': Initial Ping Timeout') {
            if ($pending.Count) {$pending=@($pending | Select-Object -Skip 1)} else {$count=$null}
        } elseif ($line -match ': Ping Timeout' -and $null -ne $count) {
            if ($count -eq 1) {$count=0} elseif ($count -gt 1) {$count=$null}
        }
    }
    if ($null -eq $count) {return $null}
    return $count+@($pending | Where-Object {$_ -gt $NowSeconds}).Count
}
