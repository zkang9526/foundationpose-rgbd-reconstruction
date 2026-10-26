param(
    [Parameter(Mandatory=$true)][string]$Scene,
    [string]$Output = '',
    [ValidateRange(1024,65535)][int]$Port = 8767
)
$ErrorActionPreference = 'Stop'
$MaskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$MaskPython = Join-Path $MaskRoot '.windows-camera-venv\Scripts\python.exe'
$MaskScene = (Resolve-Path -LiteralPath $Scene).Path
if ([string]::IsNullOrWhiteSpace($Output)) {
    $MaskStoragePath = Join-Path $PSScriptRoot 'windows_storage_policy.json'
    $MaskStorage = Get-Content -LiteralPath $MaskStoragePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $MaskDataRoot = [IO.Path]::GetFullPath([string]$MaskStorage.data_root)
    if (-not $MaskDataRoot.StartsWith('E:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Expected E drive data root' }
    $Output = Join-Path $MaskDataRoot ('manual_masks\' + (Split-Path -Leaf $MaskScene) + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
}
$MaskOutput = [IO.Path]::GetFullPath($Output)
if (-not $MaskOutput.StartsWith('E:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Mask output must be on E drive' }
$MaskNote = 'Offline human mask annotation; source RGB/depth read-only; original-resolution masks 0/255; immutable revisions, no SAM or pose ground truth. ' + [string]$env:FP_RUN_NOTE
Write-Output "Manual mask page: http://127.0.0.1:$Port"
Write-Output "Annotations: $MaskOutput"
Write-Output 'To resume, rerun with the same -Scene and -Output. Ctrl+C stops the editor after saving.'
& $MaskPython -B -u (Join-Path $PSScriptRoot 'run_logged.py') --root $MaskRoot --cwd $MaskRoot --label manual_cup_mask_editor --note $MaskNote -- $MaskPython -B -u (Join-Path $PSScriptRoot 'manual_mask_editor.py') --scene $MaskScene --output $MaskOutput --port $Port
exit $LASTEXITCODE
