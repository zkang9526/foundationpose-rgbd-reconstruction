param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$TaskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$CaptureRoot = (Resolve-Path -LiteralPath (Join-Path $TaskRoot 'foundationpose_data\windows_captures')).Path
$Names = @('obj_side_20261014_154627_286', 'obj_side_20261014_154706_548', 'obj_side_20261014_160527_974')
$EvidenceRoot = Join-Path $TaskRoot ('reports\deleted_capture_evidence_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
if (Test-Path -LiteralPath $EvidenceRoot) { throw 'Evidence directory already exists' }
$Targets = @()
foreach ($Name in $Names) {
    $Expected = [IO.Path]::GetFullPath((Join-Path $CaptureRoot $Name))
    if (-not $Expected.StartsWith($CaptureRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Target outside capture directory' }
    if (-not (Test-Path -LiteralPath $Expected -PathType Container)) { continue }
    $Resolved = (Resolve-Path -LiteralPath $Expected).Path
    if (-not [string]::Equals($Resolved, $Expected, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected resolved target' }
    $Entries = @(Get-Item -LiteralPath $Resolved) + @(Get-ChildItem -LiteralPath $Resolved -Recurse -Force)
    if (@($Entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'Refusing reparse points in deletion tree' }
    $Busy = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like ('*' + $Name + '*') })
    if ($Busy.Count) { throw "Capture process still running for $Name; no deletion performed" }
    $Files = @($Entries | Where-Object { -not $_.PSIsContainer })
    $Bytes = ($Files | Measure-Object Length -Sum).Sum
    $Targets += [pscustomobject]@{name=$Name; path=$Resolved; bytes=$Bytes; files=$Files}
}
New-Item -ItemType Directory -Path $EvidenceRoot | Out-Null
$Manifest = [ordered]@{scope='User-requested deletion of three explicitly named recent OBJ capture directories; prior reference data and all run logs retained'; apply=[bool]$Apply; created_utc=[DateTime]::UtcNow.ToString('o'); targets=@(); total_bytes=0; completed=$false}
foreach ($Target in $Targets) {
    $Archive = Join-Path $EvidenceRoot $Target.name
    New-Item -ItemType Directory -Path $Archive | Out-Null
    $FileRows = @()
    foreach ($File in $Target.files) {
        $Relative = $File.FullName.Substring($Target.path.Length + 1)
        $Row = [ordered]@{relative_path=$Relative; bytes=$File.Length; last_write_utc=$File.LastWriteTimeUtc.ToString('o')}
        if ($File.Extension -ne '.bag') { $Row.sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
        else { $Row.sha256 = $null; $Row.hash_note = 'Not hashed before explicitly requested deletion; retain file size and original run evidence' }
        $FileRows += [pscustomobject]$Row
        if ($File.DirectoryName -eq $Target.path -and $File.Extension -in @('.json', '.csv', '.txt')) {
            Copy-Item -LiteralPath $File.FullName -Destination (Join-Path $Archive $File.Name)
        }
    }
    $Manifest.targets += [pscustomobject]@{name=$Target.name; resolved_absolute_path=$Target.path; bytes=$Target.bytes; files=$FileRows; removed=$false}
    $Manifest.total_bytes += $Target.bytes
}
$ReportPath = Join-Path $EvidenceRoot 'deletion_manifest.json'
$Manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
if ($Apply) {
    foreach ($Target in $Targets) {
        # Verify absolute target again immediately before native PowerShell delete.
        $Checked = (Resolve-Path -LiteralPath $Target.path).Path
        if (-not $Checked.StartsWith($CaptureRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not [string]::Equals($Checked, (Join-Path $CaptureRoot $Target.name), [StringComparison]::OrdinalIgnoreCase) -or
            $Target.name -notin $Names) { throw 'Deletion target verification failed' }
        Remove-Item -LiteralPath $Checked -Recurse -Force
        if (Test-Path -LiteralPath $Checked) { throw 'Target still exists after deletion' }
        ($Manifest.targets | Where-Object { $_.name -eq $Target.name }).removed = $true
        $Manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
        Write-Output "Removed: $Checked"
    }
}
$Manifest.completed = $true
$Manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Output "Evidence: $EvidenceRoot"
Write-Output ("Target size: {0:N2} GiB" -f ($Manifest.total_bytes / 1GB))
Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:' OR DeviceID='E:'" | Select-Object DeviceID,Size,FreeSpace
