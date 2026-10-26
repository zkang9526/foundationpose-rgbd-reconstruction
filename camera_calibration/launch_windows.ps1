param(
    [ValidateRange(10, 7200)][int]$DurationSeconds = 3600,
    [ValidateRange(1, 65535)][int]$Port = 8766,
    [ValidateRange(0, 10)][int]$CaptureDelaySeconds = 3,
    [ValidateSet('preserve', 'off', 'on')][string]$EmitterMode = 'preserve',
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
$CalibrationRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$CalibrationProject = (Resolve-Path -LiteralPath (Join-Path $CalibrationRoot '..')).Path
if (-not $CalibrationProject.StartsWith('E:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use the real E: project path for calibration storage'
}
$CalibrationEntry = Join-Path $CalibrationRoot 'run_windows.ps1'
$CalibrationHasher = [System.Security.Cryptography.SHA256]::Create()
try {
    $CalibrationEntrySha = [BitConverter]::ToString($CalibrationHasher.ComputeHash([IO.File]::ReadAllBytes($CalibrationEntry))).Replace('-', '').ToLowerInvariant()
} finally {
    $CalibrationHasher.Dispose()
}
if ($ValidateOnly) {
    Write-Output ($CalibrationEntrySha)
    exit 0
}
$CalibrationUrl = "http://127.0.0.1:$Port/status"
try {
    $CalibrationExisting = Invoke-RestMethod -Uri $CalibrationUrl -TimeoutSec 2
} catch {
    $CalibrationExisting = $null
}
if ($CalibrationExisting) {
    throw "Port $Port already has a live service. Inspect it before starting another camera session."
}
$CalibrationStamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$CalibrationLaunch = Join-Path $CalibrationRoot ('launches\windows_' + $CalibrationStamp)
New-Item -ItemType Directory -Path $CalibrationLaunch | Out-Null
$CalibrationOut = Join-Path $CalibrationLaunch 'stdout.txt'
$CalibrationErr = Join-Path $CalibrationLaunch 'stderr.txt'
$CalibrationChildArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $CalibrationEntry,
    '-DurationSeconds', "$DurationSeconds", '-Port', "$Port", '-CaptureDelaySeconds', "$CaptureDelaySeconds", '-EmitterMode', $EmitterMode)
$CalibrationProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList $CalibrationChildArgs `
    -WorkingDirectory $CalibrationProject -WindowStyle Hidden -RedirectStandardOutput $CalibrationOut `
    -RedirectStandardError $CalibrationErr -PassThru
$CalibrationLaunchInfo = [ordered]@{
    created_utc = [DateTime]::UtcNow.ToString('o')
    pid = $CalibrationProcess.Id
    entry = $CalibrationEntry
    entry_sha256 = $CalibrationEntrySha
    stdout = $CalibrationOut
    stderr = $CalibrationErr
    url = "http://127.0.0.1:$Port"
    duration_seconds = $DurationSeconds
    capture_delay_seconds = $CaptureDelaySeconds
    requested_emitter_mode = $EmitterMode
}
$CalibrationLaunchInfo | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $CalibrationLaunch 'launch.json') -Encoding UTF8
$CalibrationDeadline = [DateTime]::UtcNow.AddSeconds(30)
while ([DateTime]::UtcNow -lt $CalibrationDeadline) {
    $CalibrationProcess.Refresh()
    if ($CalibrationProcess.HasExited) { throw "Capture exited; see $CalibrationErr and $CalibrationOut" }
    try {
        $CalibrationReady = Invoke-RestMethod -Uri $CalibrationUrl -TimeoutSec 2
        if ($CalibrationReady.frames_received -gt 0) {
            $CalibrationReady | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $CalibrationLaunch 'ready.json') -Encoding UTF8
            Write-Output "Calibration ready: http://127.0.0.1:$Port"
            Write-Output "Session: $($CalibrationReady.output)"
            Write-Output "Launch evidence: $CalibrationLaunch"
            exit 0
        }
    } catch {
        # The service starts after stream warm-up; continue until the bounded deadline.
    }
    Start-Sleep -Milliseconds 400
}
throw "Capture readiness timeout; preserve launch evidence at $CalibrationLaunch"
