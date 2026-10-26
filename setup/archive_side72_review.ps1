$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ReviewRoot = 'E:\foundationPos_data\reviews\side72_20261014_161656'
if (-not (Test-Path -LiteralPath $ReviewRoot -PathType Container)) { throw 'E drive review directory missing' }
foreach ($Entry in @(
    @('CUP_SIDE72_REVIEW_SESSION_20261014_161656.md', 'REVIEW.md'),
    @('CUP_SIDE72_REVIEW_ISSUES_20261014_161656.md', 'ISSUES.md')
)) {
    $Source = Join-Path $ProjectRoot ('reports\' + $Entry[0])
    $Destination = Join-Path $ReviewRoot $Entry[1]
    if (Test-Path -LiteralPath $Destination) { throw "Review document already exists: $Destination" }
    Copy-Item -LiteralPath $Source -Destination $Destination
    if ((Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash) { throw 'Review copy hash differs' }
}
$CameraPython = Join-Path $ProjectRoot '.windows-camera-venv\Scripts\python.exe'
& $CameraPython -B (Join-Path $PSScriptRoot 'append_manual_records.py') --root $ProjectRoot --event-id 'CUP-E-SIDE72-REVIEW-20261014-161656' --experiment (Join-Path $ReviewRoot 'REVIEW.md') --issues (Join-Path $ReviewRoot 'ISSUES.md')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Review saved and archived: $ReviewRoot"
