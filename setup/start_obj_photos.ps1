param(
    [ValidateRange(1, 3600)][int]$Views = 72,
    [ValidateRange(0.01, 360)][double]$AngleStep = 5,
    [ValidateSet('side', 'top', 'low', 'test')][string]$Ring = 'side',
    [ValidateSet('device-default', 'high-accuracy', 'high-density')][string]$DepthPreset = 'device-default',
    [switch]$DepthAutoExposure,
    [switch]$RecordBag,
    [switch]$FilteredDepth,
    [string]$CaptureRoot = '',
    [switch]$DryRun,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
if ($Help) {
    Write-Output 'OBJ capture: fixed D435i, turn object, let it settle, remove hand, then Enter.'
    Write-Output 'Default: 72 views, planned 5 degrees, preserve current camera settings, 640x480@30, raw millimeter PNGs.'
    Write-Output '-DepthPreset device-default|high-accuracy|high-density; device-default does not reset the camera.'
    Write-Output '-DepthAutoExposure enables depth auto-exposure for this run and restores actual settings afterward.'
    Write-Output '-Ring side|top|low|test creates a separate sequence; planned angles are not measured poses.'
    Write-Output '-RecordBag adds native SDK stream recording including waiting/motion; PNGs select stationary pairs.'
    Write-Output '-FilteredDepth adds derived depth_filtered/ without altering raw depth/.'
    Write-Output 'Storage uses setup/windows_capture_storage.json (currently E drive); -CaptureRoot overrides it.'
    Write-Output '-DryRun prints destination and capture arguments without accessing the camera or creating data.'
    exit 0
}
$ObjRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ObjPython = Join-Path $ObjRoot '.windows-camera-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ObjPython -PathType Leaf)) { throw 'Run setup\prepare_d435i_windows.ps1 first.' }
$ObjOutput = & (Join-Path $PSScriptRoot 'get_windows_capture_directory.ps1') -ProjectRoot $ObjRoot -Prefix ('obj_' + $Ring) -CaptureRoot $CaptureRoot
if (Test-Path -LiteralPath $ObjOutput) { throw 'Capture directory already exists; use a new run.' }
$ObjNote = "OBJ reference capture; fixed camera, turn object, settle and remove hand; ring=$Ring; depth_preset=$DepthPreset; depth_auto_exposure=$DepthAutoExposure; planned angle is not ground truth. " + [string]$env:FP_RUN_NOTE
$ObjArgs = @('-u', (Join-Path $PSScriptRoot 'run_logged.py'), '--root', $ObjRoot, '--cwd', $ObjRoot,
    '--label', 'windows_obj_photos', '--note', $ObjNote, '--', $ObjPython, '-B', '-u',
    (Join-Path $PSScriptRoot 'capture_d435i_photos.py'), '--output', $ObjOutput,
    '--views', $Views, '--planned-angle-step', $AngleStep.ToString([System.Globalization.CultureInfo]::InvariantCulture),
    '--depth-preset', $DepthPreset, '--warmup', '90', '--settle-seconds', '1')
Write-Output "Depth preset: $DepthPreset (device-default preserves current settings; other presets change them for this run)."
if ($RecordBag) { $ObjArgs += '--record-bag' }
if ($FilteredDepth) { $ObjArgs += '--save-filtered-depth' }
if ($DepthAutoExposure) { $ObjArgs += '--depth-auto-exposure' }
Write-Output "Output: $ObjOutput"
if ($DryRun) {
    Write-Output ('Capture arguments: ' + ($ObjArgs -join ' '))
    exit 0
}
& $ObjPython @ObjArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run_d435i_format_check.ps1') $ObjOutput
exit $LASTEXITCODE
