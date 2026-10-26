$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$CameraPython = Join-Path $ProjectRoot '.windows-camera-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $CameraPython -PathType Leaf)) {
    throw "Windows camera environment is missing. Run: powershell.exe -ExecutionPolicy Bypass -File `"$ProjectRoot\setup\prepare_d435i_windows.ps1`""
}
$Logger = Join-Path $PSScriptRoot 'run_logged.py'
$CameraScript = Join-Path $PSScriptRoot 'check_capture_files.py'
$RunNote = [string]$env:FP_RUN_NOTE
$LoggedArgs = @('-u', $Logger, '--root', $ProjectRoot, '--cwd', $ProjectRoot, '--label', 'windows_d435i_format')
if (-not [string]::IsNullOrEmpty($RunNote)) {
    $LoggedArgs += @('--note', $RunNote)
}
$LoggedArgs += @('--', $CameraPython, '-u', $CameraScript)
& $CameraPython @LoggedArgs @args
exit $LASTEXITCODE
