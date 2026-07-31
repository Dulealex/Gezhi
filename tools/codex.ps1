$ErrorActionPreference = 'Stop'

$codexArguments = @($args)
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot 'runtimes\codex\node_modules\@openai'
$packageRoot = Join-Path $runtimeRoot 'codex'
$packageJson = Join-Path $packageRoot 'package.json'

if (-not (Test-Path -LiteralPath $packageJson)) {
    throw "Gezhi Codex CLI is not installed. Run: npm ci --prefix runtimes\codex"
}

$package = Get-Content -LiteralPath $packageJson -Raw | ConvertFrom-Json
if ($package.version -ne '0.146.0') {
    throw "Gezhi requires Codex CLI 0.146.0; found: $($package.version)"
}

$nativeRoot = Join-Path $runtimeRoot 'codex-win32-x64'
$nativePackageJson = Join-Path $nativeRoot 'package.json'
if (-not (Test-Path -LiteralPath $nativePackageJson)) {
    throw "Gezhi Codex Windows runtime is not installed: $nativePackageJson"
}

$nativePackage = Get-Content -LiteralPath $nativePackageJson -Raw | ConvertFrom-Json
if ($nativePackage.version -ne '0.146.0-win32-x64') {
    throw "Gezhi requires Codex Windows runtime 0.146.0-win32-x64; found: $($nativePackage.version)"
}

$native = @(Get-ChildItem -LiteralPath $nativeRoot -Recurse -File -Filter 'codex.exe' -ErrorAction Stop)
if ($native.Count -ne 1) {
    throw "Expected one native Codex CLI executable under $nativeRoot; found $($native.Count)"
}

$version = (& $native[0].FullName --version)
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^codex-cli 0\.146\.0$') {
    throw "Unexpected native Codex CLI version: $version"
}

& $native[0].FullName @codexArguments
exit $LASTEXITCODE
