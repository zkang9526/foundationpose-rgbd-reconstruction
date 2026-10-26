param(
    [ValidateSet('capture', 'snapshot', 'analyze')][string]$Action = 'capture',
    [string]$InputDirectory,
    [ValidateRange(1, 65535)][int]$Port = 8766,
    [ValidateRange(10, 7200)][int]$DurationSeconds = 1800,
    [ValidateRange(0, 10)][int]$CaptureDelaySeconds = 3,
    [ValidateSet('preserve', 'off', 'on')][string]$EmitterMode = 'preserve'
)
$ErrorActionPreference = 'Stop'
$CalibrationRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$CalibrationProject = (Resolve-Path -LiteralPath (Join-Path $CalibrationRoot '..')).Path
$CalibrationPython = Join-Path $CalibrationProject '.windows-camera-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $CalibrationPython)) { throw 'Missing existing Windows camera environment' }
$CalibrationStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$CalibrationBoard = Get-Content -LiteralPath (Join-Path $CalibrationRoot 'board.json') -Raw | ConvertFrom-Json
$CalibrationNote = 'Separate checkerboard verification; inner corners ' + $CalibrationBoard.cols + 'x' + $CalibrationBoard.rows + '; square ' + $CalibrationBoard.square_mm + 'mm; temporary emitter mode ' + $EmitterMode + '; factory calibration read only. ' + [string]$env:FP_RUN_NOTE
if ($Action -eq 'analyze') {
    if (-not $InputDirectory) { throw 'Analyze requires -InputDirectory' }
    $CalibrationNote = 'Offline checkerboard analysis; emitter state comes from input factory.json; no camera settings changed. ' + [string]$env:FP_RUN_NOTE
    $CalibrationOutput = Join-Path $CalibrationRoot ('results\analysis_' + $CalibrationStamp)
    $CalibrationArgs = @((Join-Path $CalibrationRoot 'analyze.py'), '--input', (Resolve-Path -LiteralPath $InputDirectory).Path, '--output', $CalibrationOutput)
} else {
    $CalibrationOutput = Join-Path $CalibrationRoot ('sessions\windows_' + $CalibrationStamp)
    $CalibrationArgs = @((Join-Path $CalibrationRoot 'capture.py'), '--output', $CalibrationOutput, '--host', '127.0.0.1', '--port', "$Port", '--duration-seconds', "$DurationSeconds", '--capture-delay-seconds', "$CaptureDelaySeconds", '--emitter-mode', $EmitterMode)
    if ($Action -eq 'snapshot') { $CalibrationArgs += '--snapshot' }
    Write-Output "Camera capture: http://127.0.0.1:$Port ; results: $CalibrationOutput"
}
& $CalibrationPython -B -u (Join-Path $CalibrationProject 'setup\run_logged.py') --root $CalibrationProject --cwd $CalibrationProject --label ('checkerboard_' + $Action) --note $CalibrationNote -- $CalibrationPython -B -u @CalibrationArgs
$CalibrationExit = $LASTEXITCODE
if ($CalibrationExit -eq 0 -and $Action -eq 'capture') {
    $CalibrationAnalysis = Join-Path $CalibrationRoot ('results\windows_' + $CalibrationStamp)
    & $CalibrationPython -B -u (Join-Path $CalibrationProject 'setup\run_logged.py') --root $CalibrationProject --cwd $CalibrationProject --label checkerboard_analysis --note $CalibrationNote -- $CalibrationPython -B -u (Join-Path $CalibrationRoot 'analyze.py') --input $CalibrationOutput --output $CalibrationAnalysis
    $CalibrationExit = $LASTEXITCODE
    Write-Output "Analysis: $CalibrationAnalysis\REPORT.md"
}
exit $CalibrationExit
