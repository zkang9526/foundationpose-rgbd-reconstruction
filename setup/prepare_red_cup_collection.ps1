param([string]$EvidenceDirectory)
$ErrorActionPreference = 'Stop'
$CaptureProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $EvidenceDirectory) {
    $EvidenceDirectory = Join-Path $CaptureProject ('reports\capture_preparation_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
}
$CaptureEvidence = [IO.Path]::GetFullPath($EvidenceDirectory)
if (-not $CaptureEvidence.StartsWith($CaptureProject + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence must stay in the E drive project'
}
if (Test-Path -LiteralPath $CaptureEvidence) { throw 'Use a new evidence directory' }
New-Item -ItemType Directory -Path $CaptureEvidence | Out-Null
$CaptureState = [ordered]@{
    created_utc = [DateTime]::UtcNow.ToString('o')
    decision = 'User explicitly pauses calibration and proceeds with new red-rim cup acquisition; calibration accuracy remains unaccepted'
    camera_calibration_written = $false
    viewer_processes = @()
    raw_data_deleted = $false
}
$CaptureClipboard = 'C:\Users\YOUR_USER\AppData\Local\Temp\codex-clipboard-a19e82e0-a248-4177-8646-a7bb63233f70.png'
if (Test-Path -LiteralPath $CaptureClipboard) {
    $CaptureCopy = Join-Path $CaptureEvidence 'viewer_calibration_failure_user_screenshot.png'
    Copy-Item -LiteralPath $CaptureClipboard -Destination $CaptureCopy
    $CaptureDigest = [Security.Cryptography.SHA256]::Create()
    try { $CaptureHash = [BitConverter]::ToString($CaptureDigest.ComputeHash([IO.File]::ReadAllBytes($CaptureCopy))).Replace('-', '').ToLowerInvariant() }
    finally { $CaptureDigest.Dispose() }
    $CaptureState.screenshot = @{path=$CaptureCopy; sha256=$CaptureHash; scope='User supplied cropped failure dialog; complete response code is unavailable'}
}
$CaptureViewer = @(Get-Process -Name realsense-viewer -ErrorAction SilentlyContinue)
foreach ($CaptureProcess in $CaptureViewer) {
    $CapturePath = $CaptureProcess.Path
    $CaptureExpectedE = Join-Path $CaptureProject 'tools\realsense-viewer\2.55.1\realsense-viewer.exe'
    $CaptureExpectedAlias = 'C:\Users\YOUR_USER\Desktop\foundationPos\tools\realsense-viewer\2.55.1\realsense-viewer.exe'
    if ($CapturePath -ine $CaptureExpectedE -and $CapturePath -ine $CaptureExpectedAlias) {
        throw ('Refusing to close unexpected viewer executable: ' + $CapturePath)
    }
    $CaptureProcessRecord = [ordered]@{id=$CaptureProcess.Id; path=$CapturePath; started=$CaptureProcess.StartTime.ToString('o'); responding=$CaptureProcess.Responding; calibration_result='failed dialog reported by user, no successful result confirmed'}
    $CaptureProcessRecord.close_main_window_requested = $CaptureProcess.CloseMainWindow()
    Start-Sleep -Milliseconds 1500
    $CaptureProcess.Refresh()
    if (-not $CaptureProcess.HasExited) {
        Stop-Process -Id $CaptureProcess.Id -ErrorAction Stop
        $CaptureProcessRecord.targeted_termination_required = $true
        $CaptureProcess.WaitForExit(5000) | Out-Null
    } else { $CaptureProcessRecord.targeted_termination_required = $false }
    $CaptureProcessRecord.exited = $CaptureProcess.HasExited
    $CaptureState.viewer_processes += $CaptureProcessRecord
}
$CaptureStorage = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'windows_capture_storage.json') -Raw | ConvertFrom-Json
$CaptureDrive = [IO.DriveInfo]::new('E')
$CaptureState.capture_root = [string]$CaptureStorage.capture_root
$CaptureState.e_free_gib = [Math]::Round($CaptureDrive.AvailableFreeSpace / 1GB, 2)
$CaptureState.viewer_closed = @(Get-Process -Name realsense-viewer -ErrorAction SilentlyContinue).Count -eq 0
$CaptureState.camera_session_started = $false
$CaptureReport = Join-Path $CaptureEvidence 'preparation.json'
$CaptureState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $CaptureReport -Encoding UTF8
$CaptureState | ConvertTo-Json -Depth 8
if (-not $CaptureState.viewer_closed) { throw 'Viewer still running; do not open another camera client' }
