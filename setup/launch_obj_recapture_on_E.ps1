$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Storage = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'windows_capture_storage.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$CaptureRoot = [IO.Path]::GetFullPath([string]$Storage.capture_root)
if (-not $CaptureRoot.StartsWith('E:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Expected E drive storage' }
$CaptureScript = Join-Path $PSScriptRoot 'start_obj_photos.ps1'
$CaptureArguments = @('-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $CaptureScript + '"'),
    '-Ring', 'side', '-Views', '72', '-AngleStep', '5', '-DepthPreset', 'high-density', '-DepthAutoExposure',
    '-RecordBag', '-FilteredDepth')
# This is a foreground interactive photo terminal: the user must rotate the
# object and enter requests in this window. Background services remain hidden.
$CaptureProcess = Start-Process -FilePath powershell.exe -ArgumentList $CaptureArguments -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
$Report = [ordered]@{launched=$true; scope='interactive_manual_photo_session_launch_only'; camera_capture_complete=$false;
    process_id=$CaptureProcess.Id; capture_root=$CaptureRoot; arguments=$CaptureArguments;
    planned_angles_are_measured=$false; created_utc=[DateTime]::UtcNow.ToString('o')}
$ReportPath = Join-Path $ProjectRoot ('reports\E_DRIVE_RECAPTURE_LAUNCH_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.json')
$Report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Output "Interactive capture window PID: $($CaptureProcess.Id)"
Write-Output "Capture root: $CaptureRoot"
Write-Output "Launch record: $ReportPath"
