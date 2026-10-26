$ErrorActionPreference = 'Stop'
$TaskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ReviewRoot = 'E:\foundationPos_data\reviews\new72_20261014_164948'
foreach ($Entry in @(
    @('CUP_NEW72_UBUNTU_RESULT_20261014.md', 'UBUNTU_RECONSTRUCTION_RESULT.md'),
    @('CUP_NEW72_UBUNTU_ISSUES_20261014.md', 'UBUNTU_RECONSTRUCTION_ISSUES.md')
)) {
    $Source = Join-Path $TaskRoot ('reports\' + $Entry[0])
    $Target = Join-Path $ReviewRoot $Entry[1]
    if (Test-Path -LiteralPath $Target) { throw 'Result note already exists; preserve it' }
    Copy-Item -LiteralPath $Source -Destination $Target
    if ((Get-FileHash -LiteralPath $Source).Hash -ne (Get-FileHash -LiteralPath $Target).Hash) { throw 'Copied note hash differs' }
}
& (Join-Path $TaskRoot '.windows-camera-venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'append_manual_records.py') --root $TaskRoot --event-id 'CUP-E-NEW72-UBUNTU-RECON-20261014' --experiment (Join-Path $ReviewRoot 'UBUNTU_RECONSTRUCTION_RESULT.md') --issues (Join-Path $ReviewRoot 'UBUNTU_RECONSTRUCTION_ISSUES.md')
exit $LASTEXITCODE
