param([switch]$PolicyOnly)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Policy.ps1')
function Device($id,$active,$available,$internal) {return @{id=$id;active=$active;available=$available;internalPanel=$internal}}
$v=Device 'virtual' $true $true $false
$i=Device 'internal' $false $true $true
$d=Device 'dock' $false $true $false
$cases=@(
 @{devices=@($v,$i);baseline=@('dock');action='single';id='internal'},
 @{devices=@($v);baseline=@('dock');action='pending';id=$null},
 @{devices=@($v,(Device 'internal' $false $false $true));baseline=@('dock');action='pending';id=$null},
 @{devices=@($v,$d);baseline=@('dock');action='baseline';id='dock'},
 @{devices=@($v,$i,$d);baseline=@('dock','internal');action='baseline';id='dock'},
 @{devices=@($v,(Device 'dock' $true $true $false),$i);baseline=@('internal');action='keep-physical';id='dock'},
 @{devices=@($v,$d);baseline=@('missing');action='single';id='dock'},
 @{devices=@($v,$i,$d);baseline=@();action='single';id='internal'},
 @{devices=@((Device 'internal' $true $true $true));baseline=@('dock');action='keep-physical';id='internal'}
)
foreach($case in $cases) {
 $choice=Get-RecoveryChoice $case.devices 'virtual' $case.baseline
 if ($choice.action -ne $case.action -or ($case.id -and $choice.ids[0] -ne $case.id)) {throw ('Recovery policy failed: '+($case|ConvertTo-Json -Compress -Depth 8))}
}
$stamp=Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'
$now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$start="[$stamp]: Info: New streaming session started [active sessions: 1]"
$stale="[$stamp]: Info: New streaming session started [active sessions: 2]"
$activityCases=@(
 @{lines=@('Sunshine version: test');expected=0},
 @{lines=@('Sunshine version: test',$start,'CLIENT CONNECTED');expected=1},
 @{lines=@('Sunshine version: test',$start);expected=1},
 @{lines=@('Sunshine version: test',$start,'CLIENT CONNECTED','CLIENT DISCONNECTED');expected=0},
 @{lines=@('Sunshine version: test',$start,'CLIENT CONNECTED','CLIENT DISCONNECTED',$stale,'CLIENT CONNECTED','CLIENT DISCONNECTED');expected=0},
 @{lines=@('Sunshine version: test',$start,'CLIENT CONNECTED',$stale,'CLIENT CONNECTED','CLIENT DISCONNECTED');expected=1},
 @{lines=@('Sunshine version: test',$start,'CLIENT CONNECTED','host: Ping Timeout');expected=0},
 @{lines=@('unrelated log after truncation');expected=$null}
)
foreach($case in $activityCases) {
 $value=Get-SunshineActivity $case.lines $now
 if ($value -ne $case.expected) {throw ('Connection observation failed: '+($case|ConvertTo-Json -Compress))}
}
Add-Type -Path (Join-Path $PSScriptRoot 'Display.cs')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Guard.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw $errors[0].Message}
$writer=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-Json'},$true)
. ([ScriptBlock]::Create($writer.Extent.Text))
$testPath=Join-Path $PSScriptRoot 'atomic-test.json'
try {
 Write-Json $testPath @{value=1}
 Write-Json $testPath @{value=2}
 if ((Get-Content $testPath -Raw | ConvertFrom-Json).value -ne 2) {throw 'Atomic journal replacement failed'}
} finally {Remove-Item $testPath -ErrorAction SilentlyContinue}
if ([Runtime.InteropServices.Marshal]::SizeOf([type][HypertileDisplay+DisplayPath]) -ne 72 -or [Runtime.InteropServices.Marshal]::SizeOf([type][HypertileDisplay+Mode]) -ne 64) {throw 'Native display layout mismatch'}
if ($PolicyOnly) {@{tests_passed=($cases.Count+$activityCases.Count+1)} | ConvertTo-Json;exit 0}
@{tests_passed=($cases.Count+$activityCases.Count+1);devices=@([HypertileDisplay]::Inspect());baseline=[HypertileDisplay]::Capture()} | ConvertTo-Json -Depth 12
