param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$Prefix,
    [string]$CaptureRoot = ''
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($CaptureRoot)) {
    $StorageConfigPath = Join-Path $PSScriptRoot 'windows_capture_storage.json'
    if (Test-Path -LiteralPath $StorageConfigPath -PathType Leaf) {
        $StorageConfig = Get-Content -LiteralPath $StorageConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $CaptureRoot = [string]$StorageConfig.capture_root
    } else {
        $CaptureRoot = Join-Path $ProjectRoot 'foundationpose_data\windows_captures'
    }
}
if ([string]::IsNullOrWhiteSpace($CaptureRoot) -or -not [IO.Path]::IsPathRooted($CaptureRoot)) { throw 'CaptureRoot must be an absolute directory' }
$CaptureRoot = [IO.Path]::GetFullPath($CaptureRoot)
if (-not (Test-Path -LiteralPath ([IO.Path]::GetPathRoot($CaptureRoot)) -PathType Container)) { throw "Capture drive is unavailable: $CaptureRoot" }
if ($Prefix -notmatch '^[a-zA-Z0-9_]+$') { throw 'Invalid capture name prefix' }
Join-Path $CaptureRoot ($Prefix + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
