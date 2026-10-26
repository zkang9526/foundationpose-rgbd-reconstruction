param(
    [ValidateRange(1, 3600)][int]$Views = 72,
    [ValidateRange(0.01, 360)][double]$AngleStep = 5,
    [ValidateSet('side', 'top', 'low', 'test')][string]$Ring = 'side',
    [string]$OperatorNote = 'Cup orientation and lighting await operator confirmation',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$RedCupProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$RedCupStorage = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'windows_capture_storage.json') -Raw | ConvertFrom-Json
$RedCupRoot = [IO.Path]::GetFullPath([string]$RedCupStorage.capture_root)
if (-not $RedCupRoot.StartsWith('E:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Expected E drive capture root' }
$RedCupScript = Join-Path $PSScriptRoot 'start_obj_photos.ps1'
$RedCupArgs = @('-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $RedCupScript + '"'),
    '-Ring', $Ring, '-Views', "$Views", '-AngleStep', $AngleStep.ToString([Globalization.CultureInfo]::InvariantCulture),
    '-DepthPreset', 'high-density', '-DepthAutoExposure', '-RecordBag')
$RedCupNote = '2026-10-17 NEW red-painted cup-rim acquisition; user explicitly defers camera calibration and plans manual per-frame mask annotation after capture; no geometric calibration acceptance; do not mix with prior black-rim data; fixed camera/manual object rotation; SDK aligned raw millimeter depth retained; native bag retained; planned angles are not GT. ' + $OperatorNote
if ($DryRun) {
    @{arguments=$RedCupArgs; note=$RedCupNote; root=$RedCupRoot; camera_opened=$false} | ConvertTo-Json -Depth 5
    exit 0
}
if (@(Get-Process -Name realsense-viewer -ErrorAction SilentlyContinue).Count) { throw 'Close Viewer before starting cup capture' }
$RedCupExisting = @(Get-ChildItem -LiteralPath $RedCupRoot -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$RedCupOriginalNote = $env:FP_RUN_NOTE
try {
    $env:FP_RUN_NOTE = $RedCupNote
    # This terminal requires the operator's Enter requests while rotating the cup.
    $RedCupProcess = Start-Process -FilePath powershell.exe -ArgumentList $RedCupArgs -WorkingDirectory $RedCupProject -WindowStyle Normal -PassThru
} finally { $env:FP_RUN_NOTE = $RedCupOriginalNote }
$RedCupReport = [ordered]@{created_utc=[DateTime]::UtcNow.ToString('o'); process_id=$RedCupProcess.Id;
    note=$RedCupNote; capture_root=$RedCupRoot; arguments=$RedCupArgs; existing_directories=$RedCupExisting;
    scope='Interactive launch only; frames are saved only after operator requests'; camera_capture_complete=$false}
$RedCupReportPath = Join-Path $RedCupProject ('reports\RED_CUP_CAPTURE_LAUNCH_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.json')
$RedCupReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $RedCupReportPath -Encoding UTF8
Write-Output ('Capture window PID: ' + $RedCupProcess.Id)
Write-Output ('Capture root: ' + $RedCupRoot)
Write-Output ('Launch evidence: ' + $RedCupReportPath)
