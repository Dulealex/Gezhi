[CmdletBinding()]
param(
    [string]$OutputPath = "",
    [switch]$TestHooks
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $repositoryRoot "native\knowledge_cancellation\gezhi_cancel_v1.c"
$productionOutput = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot "src\gezhi\_native\gezhi_cancel_v1.dll")
)
if ($TestHooks -and [string]::IsNullOrEmpty($OutputPath)) {
    throw "TestHooks requires an explicit OutputPath outside the production package"
}
if ([string]::IsNullOrEmpty($OutputPath)) {
    $OutputPath = $productionOutput
}
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
if (
    $TestHooks -and
    [string]::Equals(
        $resolvedOutput,
        $productionOutput,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "TestHooks refuses the production DLL OutputPath"
}
$outputDirectory = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw "Required vswhere.exe is unavailable"
}
$instances = @(
    & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json |
        ConvertFrom-Json
)
if ($instances.Count -ne 1) {
    throw "Expected exactly one compatible Visual Studio instance"
}
$instance = $instances[0]
if ($instance.catalog.productDisplayVersion -notlike "17.14.13*") {
    throw "Visual Studio Build Tools version drifted"
}
$installationPath = [string]$instance.installationPath
$toolsetVersionPath = Join-Path $installationPath "VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt"
$toolsetVersion = (Get-Content -LiteralPath $toolsetVersionPath -Encoding ASCII).Trim()
if ($toolsetVersion -ne "14.44.35207") {
    throw "MSVC toolset version drifted"
}
$cl = Join-Path $installationPath "VC\Tools\MSVC\$toolsetVersion\bin\Hostx64\x64\cl.exe"
if (-not (Test-Path -LiteralPath $cl -PathType Leaf)) {
    throw "Required x64 cl.exe is unavailable"
}
$msvcRoot = Join-Path $installationPath "VC\Tools\MSVC\$toolsetVersion"
$msvcInclude = Join-Path $msvcRoot "include"
$msvcLib = Join-Path $msvcRoot "lib\x64"

$kitsRoot = (Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots").KitsRoot10
$sdkVersion = "10.0.26100.0"
$sdkInclude = Join-Path $kitsRoot "Include\$sdkVersion"
$sdkLib = Join-Path $kitsRoot "Lib\$sdkVersion"
$requiredSdkPaths = @(
    (Join-Path $sdkInclude "um\Windows.h"),
    (Join-Path $sdkInclude "shared\winerror.h"),
    (Join-Path $sdkInclude "ucrt\corecrt.h"),
    (Join-Path $sdkLib "um\x64\kernel32.lib"),
    (Join-Path $sdkLib "ucrt\x64\ucrt.lib"),
    (Join-Path $msvcInclude "stdint.h"),
    (Join-Path $msvcLib "libcmt.lib")
)
foreach ($requiredPath in $requiredSdkPaths) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Windows SDK 10.0.26100.0 is incomplete"
    }
}

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gezhi-cancel-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    $objectPath = Join-Path $temporaryRoot "gezhi_cancel_v1.obj"
    $importLibrary = Join-Path $temporaryRoot "gezhi_cancel_v1.lib"
    $pdbPath = Join-Path $temporaryRoot "gezhi_cancel_v1.pdb"
    $arguments = @(
        "/nologo", "/LD", "/O2", "/MT", "/W4", "/WX", "/GS", "/guard:cf", "/Brepro",
        "/Fo$objectPath", "/Fd$pdbPath",
        "/I$msvcInclude",
        "/I$(Join-Path $sdkInclude 'ucrt')",
        "/I$(Join-Path $sdkInclude 'shared')",
        "/I$(Join-Path $sdkInclude 'um')",
        $sourcePath
    )
    if ($TestHooks) {
        $arguments += "/DGEZHI_CANCEL_TESTING"
    }
    $arguments += @(
        "/link", "/NOLOGO", "/MACHINE:X64", "/DYNAMICBASE", "/NXCOMPAT",
        "/INCREMENTAL:NO", "/OPT:REF", "/OPT:ICF", "/Brepro",
        "/OUT:$resolvedOutput", "/IMPLIB:$importLibrary", "/PDB:$pdbPath",
        "/LIBPATH:$msvcLib",
        "/LIBPATH:$(Join-Path $sdkLib 'ucrt\x64')",
        "/LIBPATH:$(Join-Path $sdkLib 'um\x64')", "kernel32.lib"
    )
    & $cl @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native cancellation bridge compilation failed"
    }
    $hash = (Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{
        output = $resolvedOutput
        sha256 = $hash
        test_hooks = [bool]$TestHooks
        toolset = $toolsetVersion
        windows_sdk = $sdkVersion
    } | ConvertTo-Json -Compress
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporaryRoot = (Resolve-Path -LiteralPath $temporaryRoot).Path
        $resolvedTemporaryParent = (Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath())).Path.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        if (
            -not $resolvedTemporaryRoot.StartsWith(
                $resolvedTemporaryParent + [System.IO.Path]::DirectorySeparatorChar,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            -not (Split-Path -Leaf $resolvedTemporaryRoot).StartsWith(
                "gezhi-cancel-build-",
                [System.StringComparison]::Ordinal
            )
        ) {
            throw "Refusing to remove an unexpected native build directory"
        }
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
