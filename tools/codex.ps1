$ErrorActionPreference = 'Stop'

$codexArguments = @($args)
$projectRoot = Split-Path -Parent $PSScriptRoot
$identityPath = Join-Path $projectRoot 'runtimes\codex\runtime-identity-v1.json'
if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
    throw "Gezhi Codex runtime identity is missing: $identityPath"
}
$identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
if ($identity.identity_version -ne 1) {
    throw "Unsupported Gezhi Codex runtime identity generation"
}
$cliPackageName = [string]$identity.cli_package_name
$cliVersion = [string]$identity.cli_version
$nativePackageAlias = [string]$identity.native_package_alias
$nativePackageName = [string]$identity.native_package_name
$nativeVersion = [string]$identity.native_package_version
if (
    [string]::IsNullOrWhiteSpace($cliPackageName) -or
    [string]::IsNullOrWhiteSpace($cliVersion) -or
    [string]::IsNullOrWhiteSpace($nativePackageAlias) -or
    [string]::IsNullOrWhiteSpace($nativePackageName) -or
    [string]::IsNullOrWhiteSpace($nativeVersion)
) {
    throw "Gezhi Codex runtime identity is malformed"
}

$nodeModulesRoot = Join-Path $projectRoot 'runtimes\codex\node_modules'
$packageRoot = Join-Path $nodeModulesRoot $cliPackageName
$packageJson = Join-Path $packageRoot 'package.json'

if (-not (Test-Path -LiteralPath $packageJson -PathType Leaf)) {
    throw "Gezhi Codex CLI is not installed. Run: npm ci --prefix runtimes\codex"
}

$package = Get-Content -LiteralPath $packageJson -Raw | ConvertFrom-Json
if ($package.name -ne $cliPackageName -or $package.version -ne $cliVersion) {
    throw "Gezhi requires Codex CLI $cliVersion; found: $($package.version)"
}

$nativeRoot = Join-Path $nodeModulesRoot $nativePackageAlias
$nativePackageJson = Join-Path $nativeRoot 'package.json'
if (-not (Test-Path -LiteralPath $nativePackageJson -PathType Leaf)) {
    throw "Gezhi Codex Windows runtime is not installed: $nativePackageJson"
}

$nativePackage = Get-Content -LiteralPath $nativePackageJson -Raw | ConvertFrom-Json
if ($nativePackage.name -ne $nativePackageName -or $nativePackage.version -ne $nativeVersion) {
    throw "Gezhi requires Codex Windows runtime $nativeVersion; found: $($nativePackage.version)"
}

$expectedNative = $nativeRoot
foreach ($component in @($identity.executable_relative_parts)) {
    if ([string]::IsNullOrWhiteSpace([string]$component)) {
        throw "Gezhi Codex executable identity is malformed"
    }
    $expectedNative = Join-Path $expectedNative ([string]$component)
}

$native = @(Get-ChildItem -LiteralPath $nativeRoot -Recurse -File -Filter 'codex.exe' -ErrorAction Stop)
if (
    $native.Count -ne 1 -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath($native[0].FullName),
        [IO.Path]::GetFullPath($expectedNative),
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Expected one native Codex CLI executable under $nativeRoot; found $($native.Count)"
}

$version = (& $native[0].FullName --version)
$expectedVersion = '^codex-cli ' + [regex]::Escape($cliVersion) + '$'
if ($LASTEXITCODE -ne 0 -or $version -notmatch $expectedVersion) {
    throw "Unexpected native Codex CLI version: $version"
}

& $native[0].FullName @codexArguments
exit $LASTEXITCODE
