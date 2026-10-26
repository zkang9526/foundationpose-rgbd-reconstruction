$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$CameraPython = Join-Path $ProjectRoot '.windows-camera-venv\Scripts\python.exe'
$Logger = Join-Path $PSScriptRoot 'run_logged.py'
$Ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
$Scp = 'C:\Windows\System32\OpenSSH\scp.exe'
$RemoteRoot = 'USER@UBUNTU_HOST:/data/ZJC/foundationPos/'

function Invoke-CupLoggedStage {
    param([string]$Label, [string[]]$StageCommand)
    $StageArguments = @('-u', $Logger, '--root', $ProjectRoot, '--cwd', $ProjectRoot,
        '--label', $Label, '--note', 'Windows 杯子初检证据同步；保留失败、初步判断及更正结果，不覆盖 Ubuntu 总日志。', '--') + $StageCommand
    & $CameraPython @StageArguments
    if ($LASTEXITCODE -ne 0) { throw "Stage $Label failed with exit code $LASTEXITCODE" }
}

Invoke-CupLoggedStage 'cup_archive_destination_guard' @($Ssh, '-o', 'BatchMode=yes', '-o', 'UpdateHostKeys=no',
    'USER@UBUNTU_HOST', 'test ! -e /data/ZJC/foundationPos/foundationpose_data/windows_captures/cup_check_20261013_152557 && test ! -e /data/ZJC/foundationPos/foundationpose_data/windows_captures/cup_check_20261013_152355')
Invoke-CupLoggedStage 'cup_archive_camera_evidence' @($Scp, '-o', 'BatchMode=yes', '-o', 'UpdateHostKeys=no', '-r',
    (Join-Path $ProjectRoot 'foundationpose_data\windows_captures\cup_check_20261013_152355'),
    (Join-Path $ProjectRoot 'foundationpose_data\windows_captures\cup_check_20261013_152557'),
    ($RemoteRoot + 'foundationpose_data/windows_captures/'))
Invoke-CupLoggedStage 'cup_archive_reports' @($Scp, '-o', 'BatchMode=yes', '-o', 'UpdateHostKeys=no',
    (Join-Path $ProjectRoot 'reports\cup_snapshot_assessment_20261013_152557.json'),
    (Join-Path $ProjectRoot 'reports\cup_snapshot_assessment_corrected_20261013_152557.json'),
    (Join-Path $ProjectRoot 'reports\cup_check_experiment_notes_20261013.md'),
    (Join-Path $ProjectRoot 'reports\cup_check_issue_notes_20261013.md'),
    ($RemoteRoot + 'reports/'))
Invoke-CupLoggedStage 'cup_archive_guide' @($Scp, '-o', 'BatchMode=yes', '-o', 'UpdateHostKeys=no',
    (Join-Path $ProjectRoot 'CUP_CHECK_20261013.md'), $RemoteRoot)
Invoke-CupLoggedStage 'cup_archive_source_scripts' @($Scp, '-o', 'BatchMode=yes', '-o', 'UpdateHostKeys=no',
    (Join-Path $PSScriptRoot 'assess_cup_snapshot.py'),
    (Join-Path $PSScriptRoot 'archive_windows_cup_check_20261013.ps1'),
    (Join-Path $PSScriptRoot 'finalize_windows_cup_check_20261013.sh'),
    ($RemoteRoot + 'setup/'))

# Upload only finished run directories from this session, including preceding SCP stages.
# The upload itself is summarized by the session journal, avoiding a self-recursive run directory.
$CupRuns = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'foundationpose_data\runs') -Directory |
    Where-Object { $_.Name -like '20261013_15*' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'run.json')) } |
    ForEach-Object {
        $Record = Get-Content -LiteralPath (Join-Path $_.FullName 'run.json') -Raw | ConvertFrom-Json
        if ($null -ne $Record.end -and $null -ne $Record.exit_code) { $_.FullName }
    })
if ($CupRuns.Count -eq 0) { throw 'No finished cup session records found' }
$UploadArgs = @('-o', 'BatchMode=yes', '-o', 'UpdateHostKeys=no', '-r') + $CupRuns + @($RemoteRoot + 'foundationpose_data/runs/')
& $Scp @UploadArgs
if ($LASTEXITCODE -ne 0) { throw "Run-record upload failed with exit code $LASTEXITCODE" }
Write-Output "Uploaded $($CupRuns.Count) finished Windows run directories."
& $Ssh '-o' 'BatchMode=yes' '-o' 'UpdateHostKeys=no' 'USER@UBUNTU_HOST' 'bash /data/ZJC/foundationPos/setup/finalize_windows_cup_check_20261013.sh'
if ($LASTEXITCODE -ne 0) { throw "Ubuntu finalization failed with exit code $LASTEXITCODE" }

# Retrieve fresh indexes; never overwrite Ubuntu indexes with older Windows copies.
& $Scp '-o' 'BatchMode=yes' '-o' 'UpdateHostKeys=no' ($RemoteRoot + 'EXPERIMENT_LOG.md') ($RemoteRoot + 'ISSUES.md') $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "Fresh journal retrieval failed with exit code $LASTEXITCODE" }
