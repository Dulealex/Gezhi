$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$localUvRoot = Join-Path $projectRoot '.local\uv'
$uvArguments = @($args)

# Isolate Gezhi from machine-wide UV_* variables owned by other projects.
$env:UV_CACHE_DIR = Join-Path $localUvRoot 'cache'
$env:UV_CREDENTIALS_DIR = Join-Path $localUvRoot 'credentials'
$env:UV_PYTHON_BIN_DIR = Join-Path $localUvRoot 'python-bin'
$env:UV_PYTHON_CACHE_DIR = Join-Path $localUvRoot 'python-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $localUvRoot 'python'
$env:UV_TOOL_BIN_DIR = Join-Path $localUvRoot 'tool-bin'
$env:UV_TOOL_DIR = Join-Path $localUvRoot 'tools'
$env:UV_MANAGED_PYTHON = '1'
$env:UV_NO_MODIFY_PATH = '1'

Remove-Item Env:UV_INSTALL_DIR -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue

$uv = (Get-Command 'uv.exe' -ErrorAction Stop).Source
$version = (& $uv --version)
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^uv 0\.11\.32\b') {
    throw "Gezhi requires uv 0.11.32; found: $version"
}

& $uv @uvArguments
exit $LASTEXITCODE
