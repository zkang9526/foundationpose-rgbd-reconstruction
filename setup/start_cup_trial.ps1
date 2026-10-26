param(
    [ValidateRange(1, 600)][int]$Seconds = 30,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
if ($Help) {
    Write-Output 'Cup trial: 90 warmup pairs, 10-second countdown, configurable duration (default 30 seconds), save up to 10 FPS, then format validation.'
    Write-Output 'Keep the cup fixed; wait for Capturing before slowly moving the camera around it.'
    Write-Output 'Each run uses setup/windows_capture_storage.json capture_root (currently E drive).'
    Write-Output 'Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_cup_trial.ps1 [-Seconds 50]'
    exit 0
}

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$CameraPython = Join-Path $ProjectRoot '.windows-camera-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $CameraPython -PathType Leaf)) {
    throw 'Windows camera environment is missing; run setup\prepare_d435i_windows.ps1 first.'
}
$SceneDirectory = & (Join-Path $PSScriptRoot 'get_windows_capture_directory.ps1') -ProjectRoot $ProjectRoot -Prefix 'cup_trial'
if (Test-Path -LiteralPath $SceneDirectory) { throw "Output already exists: $SceneDirectory" }
$OriginalNote = $env:FP_RUN_NOTE
$TrialNote = "杯子多视角试采；计划固定杯子、相机绕拍；$Seconds 秒、保存10FPS、预热90对、倒计时10秒。实际移动与光照以人工验收为准。"
if (-not [string]::IsNullOrWhiteSpace($OriginalNote)) { $TrialNote += ' 用户备注：' + $OriginalNote }
$TrialExitCode = 1
try {
    $env:FP_RUN_NOTE = $TrialNote
    Write-Output "Trial output: $SceneDirectory"
    Write-Output 'Keep the cup fixed. Wait for Capturing; then slowly circle it with the camera.'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run_d435i_capture.ps1') --output $SceneDirectory --seconds $Seconds --save-fps 10 --countdown 10 --warmup 90
    $TrialExitCode = $LASTEXITCODE
    if ($TrialExitCode -eq 0) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run_d435i_format_check.ps1') $SceneDirectory
        $TrialExitCode = $LASTEXITCODE
    }
    if ($TrialExitCode -eq 0) {
        Write-Output "Capture and file-format checks passed. Review cup RGB/depth and view coverage next: $SceneDirectory"
    } else {
        Write-Output "Trial failed with exit code $TrialExitCode. Evidence is preserved; use a new directory for a retry."
    }
} finally {
    $env:FP_RUN_NOTE = $OriginalNote
}
exit $TrialExitCode
