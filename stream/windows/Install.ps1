$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\Hypertile\display'
$task='Hypertile Display Recovery'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'Administrator setup is required'}
if (Test-Path (Join-Path $root 'config.json')) {throw 'Display helper is already installed; stop and review before upgrading'}
$sunshineRoot=Join-Path $env:ProgramFiles 'Sunshine\config'
$sunshineState=Get-Content (Join-Path $sunshineRoot 'sunshine_state.json') -Raw | ConvertFrom-Json
if ($sunshineState.root.uniqueid -ine $package.pairing_uuid) {throw 'Paired Sunshine identity mismatch'}
$confPath=Join-Path $sunshineRoot 'sunshine.conf'
$original=[IO.File]::ReadAllText($confPath)
$output=[regex]::Matches($original,'(?m)^output_name\s*=\s*([^\r\n]+)')
if ($output.Count -ne 1 -or $output[0].Groups[1].Value.Trim() -ine $package.output_uuid) {throw 'Sunshine capture output changed; stopped before editing'}
$null=New-Item -ItemType Directory -Path $root -Force
& icacls.exe $root /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' ('*'+$identity.User.Value+':(OI)(CI)M') | Out-Null
if ($LASTEXITCODE -ne 0) {throw 'Could not protect helper files'}
foreach($name in @('requests','responses')) {$null=New-Item -ItemType Directory -Path (Join-Path $root $name) -Force}
foreach($file in $package.files.PSObject.Properties) {
 if ($file.Name -notin @('Guard.ps1','Policy.ps1','Display.cs','Test.ps1')) {throw 'Unexpected package file'}
 [IO.File]::WriteAllBytes((Join-Path $root $file.Name),[Convert]::FromBase64String($file.Value))
}
. (Join-Path $root 'Policy.ps1')
function Assert-NoStream {
 $activity=Get-SunshineActivity @(Get-Content (Join-Path $sunshineRoot 'sunshine.log') -Tail 12000) ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
 if ($null -eq $activity) {throw 'Cannot confirm Sunshine is idle; stopped before changing its configuration'}
 if ($activity -gt 0) {throw 'Disconnect every stream before installing display recovery'}
}
Assert-NoStream
$principal=New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$probeTask='Hypertile Display Probe '+[guid]::NewGuid().ToString('N')
$inventoryPath=Join-Path $root ('inventory-'+[guid]::NewGuid().ToString('N')+'.json')
$probeCode="try { & '$root\Test.ps1' | Set-Content '$inventoryPath' -Encoding utf8 } catch { @{error=`$_.Exception.Message} | ConvertTo-Json | Set-Content '$inventoryPath' -Encoding utf8 }"
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($probeCode))
$action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand '+$encoded)
try {
 $null=Register-ScheduledTask -TaskName $probeTask -Action $action -Principal $principal -Settings $settings
 Start-ScheduledTask -TaskName $probeTask
 $until=(Get-Date).AddSeconds(25)
 while (-not (Test-Path $inventoryPath) -and (Get-Date) -lt $until) {Start-Sleep -Milliseconds 300}
 if (-not (Test-Path $inventoryPath)) {throw 'Console display probe did not run'}
 $inventory=Get-Content $inventoryPath -Raw | ConvertFrom-Json
 if ($inventory.error) {throw $inventory.error}
} finally {Stop-ScheduledTask -TaskName $probeTask -ErrorAction SilentlyContinue;Unregister-ScheduledTask -TaskName $probeTask -Confirm:$false -ErrorAction SilentlyContinue}
$capture=@($inventory.devices | Where-Object {$_.id -match ('(?i)#'+[regex]::Escape($package.capture_hardware)+'#')})
if ($capture.Count -ne 1) {throw 'Expected one virtual capture display; stopped before changing Sunshine'}
if ($capture[0].active) {throw 'Restore the physical desktop before installing display recovery'}
$config=@{version=1;pairing_uuid=$package.pairing_uuid;output_uuid=$package.output_uuid;capture_id=$capture[0].id;sunshine_config=$sunshineRoot;account=$identity.Name}
$backup=Join-Path $root 'sunshine.conf.before'
[IO.File]::WriteAllText($backup,$original,[Text.UTF8Encoding]::new($false))
$pattern='(?m)^dd_configuration_option\s*=[^\r\n]*'
if ([regex]::Matches($original,$pattern).Count -ne 1) {throw 'Expected one Sunshine display option'}
$updated=[regex]::Replace($original,$pattern,'dd_configuration_option = disabled')
$written=$false
try {
 Assert-NoStream
 if ([IO.File]::ReadAllText($confPath) -cne $original) {throw 'Sunshine configuration changed during setup'}
 $config | ConvertTo-Json | Set-Content (Join-Path $root 'config.json') -Encoding utf8
 [IO.File]::WriteAllText($confPath,$updated,[Text.UTF8Encoding]::new($false));$written=$true
 Restart-Service SunshineService
 (Get-Service SunshineService).WaitForStatus('Running',[TimeSpan]::FromSeconds(15))
 $guardCode="try { & '$root\Guard.ps1' } catch { @{error=`$_.Exception.Message;line=`$_.InvocationInfo.ScriptLineNumber} | ConvertTo-Json | Set-Content '$root\fatal.json' -Encoding utf8; exit 1 }"
 $guardEncoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($guardCode))
 $action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand '+$guardEncoded)
 $trigger=New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
 $null=Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Trigger $trigger -Settings $settings
 $started=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
 Start-ScheduledTask -TaskName $task
 $until=(Get-Date).AddSeconds(25)
 while (-not (Test-Path (Join-Path $root 'status.json')) -and (Get-Date) -lt $until) {Start-Sleep -Milliseconds 300}
 if (-not (Test-Path (Join-Path $root 'status.json'))) {throw 'Display helper did not start'}
 $status=Get-Content (Join-Path $root 'status.json') -Raw | ConvertFrom-Json
 if ($status.error) {throw $status.error}
 # Require another successful write: startup alone does not prove the loop lives.
 Start-Sleep -Seconds 5
 $status=Get-Content (Join-Path $root 'status.json') -Raw | ConvertFrom-Json
 if ($status.error -or $status.observed_at -le $started -or [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$status.observed_at -gt 4) {throw 'Display helper did not remain healthy'}
 @{ok=$true;installed=$root;task=$task;tests_passed=$inventory.tests_passed;device_id=$capture[0].id;status=$status} | ConvertTo-Json -Depth 12 -Compress
} catch {
 $failure=$_
 Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
 Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
 if ($written -and [IO.File]::ReadAllText($confPath) -ceq $updated) {[IO.File]::WriteAllText($confPath,$original,[Text.UTF8Encoding]::new($false));Restart-Service SunshineService}
 Remove-Item (Join-Path $root 'config.json') -ErrorAction SilentlyContinue
 throw $failure
}
