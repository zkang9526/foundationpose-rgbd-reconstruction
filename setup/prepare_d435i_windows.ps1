$ErrorActionPreference = 'Stop'
$TaskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Launcher = (Get-Command py.exe -ErrorAction Stop).Source
$TaskPython = (& $Launcher -3.11 -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $TaskPython -PathType Leaf)) {
    throw 'Python 3.11 x64 is required. The current machine has it installed.'
}
$TaskEnv = Join-Path $TaskRoot '.windows-camera-venv'
$Marker = Join-Path $TaskEnv '.foundationpose-windows-camera-env'
$CameraPython = Join-Path $TaskEnv 'Scripts\python.exe'
$Logger = Join-Path $PSScriptRoot 'run_logged.py'
$Wheels = @(
    @{Name='pyrealsense2-2.55.1.6486-cp311-cp311-win_amd64.whl'; SHA256='e01939a63bac3e1a4da742f7e1dbc618a4ec03ee0f7b3690ae5d1ad0c983aca8'},
    @{Name='numpy-1.26.4-cp311-cp311-win_amd64.whl'; SHA256='cd25bcecc4974d09257ffcd1f098ee778f7834c3ad767fe5db785be9a4aa9cb2'},
    @{Name='pillow-12.3.0-cp311-cp311-win_amd64.whl'; SHA256='8e95e1385e4998ae9694eeaa4730ba5457ff61185b3a55e2e7bea0880aef452a'},
    @{Name='opencv_python-4.11.0.86-cp37-abi3-win_amd64.whl'; SHA256='085ad9b77c18853ea66283e98affefe2de8cc4c1f43eda4c100cf9b2721142ec'}
)
$WheelPaths = @()
foreach ($Wheel in $Wheels) {
    $Path = Join-Path (Join-Path $TaskRoot '.assets_download') $Wheel.Name
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing cached official wheel: $Path" }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Wheel.SHA256) {
        throw "Wheel SHA256 mismatch: $Path"
    }
    $WheelPaths += $Path
}
if ((Test-Path -LiteralPath $TaskEnv) -and -not (Test-Path -LiteralPath $Marker -PathType Leaf)) {
    throw "Existing environment is not managed by this script: $TaskEnv"
}
if (-not (Test-Path -LiteralPath $CameraPython -PathType Leaf)) {
    & $TaskPython -u $Logger --root $TaskRoot --cwd $TaskRoot --label windows_camera_venv_create --note 'Create an isolated Windows D435i capture environment' -- $TaskPython -m venv $TaskEnv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Set-Content -LiteralPath $Marker -Value 'Dedicated Windows D435i camera environment' -Encoding ASCII
}
$PipArgs = @('-m', 'pip', 'install', '--no-index', '--no-deps') + $WheelPaths
& $TaskPython -u $Logger --root $TaskRoot --cwd $TaskRoot --label windows_camera_sdk_install --note 'Install SHA256-verified cached RealSense, NumPy, Pillow and OpenCV wheels' -- $CameraPython @PipArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $TaskPython -u $Logger --root $TaskRoot --cwd $TaskRoot --label windows_camera_pip_check --note 'Validate Windows capture dependencies' -- $CameraPython -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$SetupDir = Join-Path $TaskRoot 'foundationpose_data\windows_camera_setup'
New-Item -ItemType Directory -Path $SetupDir -Force | Out-Null
& $CameraPython -m pip freeze | Set-Content -LiteralPath (Join-Path $SetupDir 'requirements.lock.txt') -Encoding UTF8
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $TaskPython -u $Logger --root $TaskRoot --cwd $TaskRoot --label windows_camera_sdk_probe --note 'Import Windows SDK and enumerate devices; no streaming or pose inference' -- $CameraPython (Join-Path $PSScriptRoot 'probe_camera_environment.py')
exit $LASTEXITCODE
