param([switch]$UserShortcuts)
$ErrorActionPreference = 'Stop'
$ViewerProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ViewerSource = Join-Path $ViewerProjectRoot '.assets_download\Intel.RealSense.Viewer.2.55.1.exe'
$ViewerInstallDirectory = Join-Path $ViewerProjectRoot 'tools\realsense-viewer\2.55.1'
$ViewerExecutable = Join-Path $ViewerInstallDirectory 'realsense-viewer.exe'
$ViewerExpectedHash = 'ced0bd623f2df2e86f074ff8ee0fd89637c92f25f44fbf2d24262a325a8990c0'
$ViewerReportPath = Join-Path $ViewerProjectRoot ('reports\windows_viewer_setup_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.json')
$ViewerReport = [ordered]@{
    passed = $false
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    installation_mode = 'official_standalone_portable_viewer'
    version = '2.55.1'
    source = $ViewerSource
    executable = $ViewerExecutable
    report = $ViewerReportPath
    driver_or_firmware_installed = $false
    camera_settings_changed = $false
    shortcuts = @()
    gui_launch_validated = $false
}
try {
    if (-not (Test-Path -LiteralPath $ViewerSource -PathType Leaf)) { throw "Missing official cached Viewer: $ViewerSource" }
    $ViewerHash = (Get-FileHash -LiteralPath $ViewerSource -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ViewerHash -ne $ViewerExpectedHash) { throw 'Cached official Viewer SHA256 mismatch' }
    $ViewerSignature = Get-AuthenticodeSignature -LiteralPath $ViewerSource
    if ($ViewerSignature.Status -ne 'Valid') { throw "Viewer signature is not Valid: $($ViewerSignature.Status)" }
    $ViewerReport.sha256 = $ViewerHash
    $ViewerReport.signature_status = [string]$ViewerSignature.Status
    $ViewerReport.signed_publisher = $ViewerSignature.SignerCertificate.Subject
    $ViewerReport.file_version = (Get-Item -LiteralPath $ViewerSource).VersionInfo.FileVersion
    $ViewerReport.binary_action = 'already_present_identical'
    if (Test-Path -LiteralPath $ViewerExecutable) {
        if (-not (Test-Path -LiteralPath $ViewerExecutable -PathType Leaf)) { throw 'Viewer destination is not a file' }
        if ((Get-FileHash -LiteralPath $ViewerExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ViewerExpectedHash) {
            throw 'Existing Viewer differs; preserve it and choose a fresh installation directory'
        }
    } else {
        New-Item -ItemType Directory -Path $ViewerInstallDirectory -Force | Out-Null
        Copy-Item -LiteralPath $ViewerSource -Destination $ViewerExecutable -ErrorAction Stop
        $ViewerReport.binary_action = 'copied_verified_official_viewer'
    }
    if ((Get-FileHash -LiteralPath $ViewerExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ViewerExpectedHash) {
        throw 'Installed executable SHA256 mismatch'
    }
    if ($UserShortcuts) {
        $ViewerDesktopDirectory = [Environment]::GetFolderPath('Desktop')
        $ViewerProgramsDirectory = [Environment]::GetFolderPath('Programs')
        if (-not $ViewerDesktopDirectory -or -not $ViewerProgramsDirectory) { throw 'User Desktop/Programs paths are unavailable' }
        $ViewerShortcutPaths = @(
            (Join-Path $ViewerDesktopDirectory 'Intel RealSense Viewer 2.55.1.lnk'),
            (Join-Path $ViewerProgramsDirectory 'Intel RealSense Viewer 2.55.1.lnk')
        )
        $ViewerShortcutShell = New-Object -ComObject WScript.Shell
        foreach ($ViewerShortcutPath in $ViewerShortcutPaths) {
            $ViewerShortcut = $ViewerShortcutShell.CreateShortcut($ViewerShortcutPath)
            if ((Test-Path -LiteralPath $ViewerShortcutPath) -and $ViewerShortcut.TargetPath -ne $ViewerExecutable) {
                throw "An unrelated shortcut already exists: $ViewerShortcutPath"
            }
            $ViewerShortcut.TargetPath = $ViewerExecutable
            $ViewerShortcut.WorkingDirectory = $ViewerInstallDirectory
            $ViewerShortcut.IconLocation = $ViewerExecutable + ',0'
            $ViewerShortcut.Description = 'Official Intel RealSense Viewer 2.55.1; D435i RGB/depth inspection'
            $ViewerShortcut.Save()
            $ViewerSavedShortcut = $ViewerShortcutShell.CreateShortcut($ViewerShortcutPath)
            if ($ViewerSavedShortcut.TargetPath -ne $ViewerExecutable) { throw 'Shortcut target verification failed' }
            $ViewerReport.shortcuts += [ordered]@{path=$ViewerShortcutPath; verified_target=$ViewerSavedShortcut.TargetPath}
        }
    }
    $ViewerReport.passed = $true
} catch {
    $ViewerReport.error = $_.Exception.Message
    $ViewerReport.passed = $false
} finally {
    $ViewerReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ViewerReportPath -Encoding UTF8
    $ViewerReport | ConvertTo-Json -Depth 8 | Write-Output
}
if (-not $ViewerReport.passed) { exit 1 }
exit 0
