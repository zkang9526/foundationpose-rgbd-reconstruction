$ErrorActionPreference = 'Stop'
$projectRoot = 'E:\foundationPos'
$pairs = @(
    @('foundationpose_data\git_validation\windows_20261015_v1\report.json', 'reports\GIT_WINDOWS_VERIFICATION_20261015.json'),
    @('foundationpose_data\exports\report.json', 'reports\GIT_UBUNTU_VERIFICATION_20261015.json')
)
foreach ($pair in $pairs) {
    $sourcePath = Join-Path $projectRoot $pair[0]
    $targetPath = Join-Path $projectRoot $pair[1]
    if (Test-Path -LiteralPath $targetPath) { throw "Evidence target already exists: $targetPath" }
    $content = Get-Content -LiteralPath $sourcePath -Raw | ConvertFrom-Json
    if (-not $content.passed) { throw 'Source verification did not pass' }
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath
    if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash) { throw 'Evidence copy SHA mismatch' }
}
$expected = 'B7AE423ADA73142BAD673DC1940C19FE87EC5E6C8662BFDBF448C7376ABAAE43'
$actual = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'foundationpose_data\exports\git_ubuntu_baseline_20261015.bundle') -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw 'Ubuntu bundle SHA mismatch after transfer' }
Write-Output 'Both platform proofs copied exactly; Ubuntu bundle SHA256 verified.'
