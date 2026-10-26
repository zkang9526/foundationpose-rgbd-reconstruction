param(
    [ValidateRange(1, 3600)][int]$Views = 36,
    [ValidateRange(0.01, 360)][double]$AngleStep = 10,
    [string]$CaptureRoot = '',
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
if ($Help) {
    Write-Output 'Cup photos: fixed D435i, rotate the cup, STOP, remove your hand, then press Enter to save one synchronized RGB/depth PNG pair.'
    Write-Output 'Defaults: 36 views, planned 10-degree rotation per photo, 90 warmup pairs, 1 second settle after Enter. Planned angles are not measured poses.'
    Write-Output 'Press q + Enter to stop early; partial data and logs are retained with passed=false.'
    Write-Output 'Each run uses a new directory under setup/windows_capture_storage.json capture_root (currently E drive); -CaptureRoot overrides it.'
    Write-Output 'Usage: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_cup_photos.ps1 [-Views 36] [-AngleStep 10]'
    exit 0
}

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$CameraPython = Join-Path $ProjectRoot '.windows-camera-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $CameraPython -PathType Leaf)) {
    throw 'Windows camera environment is missing; run setup\prepare_d435i_windows.ps1 first.'
}
$SceneDirectory = & (Join-Path $PSScriptRoot 'get_windows_capture_directory.ps1') -ProjectRoot $ProjectRoot -Prefix 'cup_photos' -CaptureRoot $CaptureRoot
if (Test-Path -LiteralPath $SceneDirectory) { throw "Output already exists: $SceneDirectory" }
$OriginalNote = $env:FP_RUN_NOTE
$PhotoNote = "杯子静止逐张RGB-D采集；计划固定D435i、旋转杯子停稳后手退出画面再按Enter；$Views 个视角，计划每次旋转 $AngleStep 度，预热90对，按键后排空新帧1秒。计划角度不是实测角度或6D位姿真值；实际光照/材质/摆放以人工记录为准。"
if (-not [string]::IsNullOrWhiteSpace($OriginalNote)) { $PhotoNote += ' 用户备注：' + $OriginalNote }
$PhotoExitCode = 1
try {
    $env:FP_RUN_NOTE = $PhotoNote
    Write-Output "Photo output: $SceneDirectory"
    Write-Output 'Fix the camera. Rotate the cup, STOP, remove your hand, and press Enter for each photo. Keep still until Saved appears.'
    $LoggedArgs = @('-u', (Join-Path $PSScriptRoot 'run_logged.py'), '--root', $ProjectRoot, '--cwd', $ProjectRoot,
                    '--label', 'windows_d435i_photos', '--note', $PhotoNote, '--', $CameraPython, '-u',
                    (Join-Path $PSScriptRoot 'capture_d435i_photos.py'), '--output', $SceneDirectory,
                    '--views', $Views, '--planned-angle-step', $AngleStep.ToString([System.Globalization.CultureInfo]::InvariantCulture),
                    '--warmup', '90', '--settle-seconds', '1')
    & $CameraPython @LoggedArgs
    $PhotoExitCode = $LASTEXITCODE
    if ($PhotoExitCode -eq 0) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run_d435i_format_check.ps1') $SceneDirectory
        $PhotoExitCode = $LASTEXITCODE
    }
    if ($PhotoExitCode -eq 0) {
        Write-Output "Photo and file-format checks passed. Review RGB/depth and view coverage next: $SceneDirectory"
    } else {
        Write-Output "Photo collection incomplete or failed (exit $PhotoExitCode). Partial evidence is preserved; use a new directory for a retry: $SceneDirectory"
    }
} finally {
    $env:FP_RUN_NOTE = $OriginalNote
}
exit $PhotoExitCode
