param(
    [Parameter(Mandatory=$true)][string]$InputDirectory,
    [ValidatePattern('^[0-9]+$')][string]$Frame = '000000',
    [ValidateRange(0.1, 10000)][double]$JumpMm = 20
)
$ErrorActionPreference = 'Stop'
$AlignRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$AlignPython = Join-Path $AlignRoot '.windows-camera-venv\Scripts\python.exe'
$AlignInput = (Resolve-Path -LiteralPath $InputDirectory).Path
$AlignOutput = Join-Path $AlignRoot ('reports\rgbd_alignment_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
$AlignNote = 'Offline RGB/aligned raw-depth visual inspection; no physical calibration verdict. ' + [string]$env:FP_RUN_NOTE
& $AlignPython -B -u (Join-Path $PSScriptRoot 'run_logged.py') --root $AlignRoot --cwd $AlignRoot --label rgbd_alignment_visual_check --note $AlignNote -- $AlignPython -B -u (Join-Path $PSScriptRoot 'review_rgbd_alignment.py') --input $AlignInput --frame $Frame --output $AlignOutput --jump-mm $JumpMm.ToString([System.Globalization.CultureInfo]::InvariantCulture)
if ($LASTEXITCODE -eq 0) { Write-Output "Review PNGs and report in: $AlignOutput" }
exit $LASTEXITCODE
