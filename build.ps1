<#
Builds dist\TrueStretch.exe - a single file you can share.

  .\build.ps1              PyInstaller build (fast, ~1-2 minutes)
  .\build.ps1 -Protected   Nuitka build (the release build): compiles the Python code to native C - faster start
                           and fewer antivirus false positives (slower to build, first run downloads a C compiler)
#>
param([switch]$Protected)
$ErrorActionPreference = "Stop"

$root  = $PSScriptRoot
# GitHub Actions (CI=true): a fresh environment inside the checkout; locally: a venv outside OneDrive
$venv  = if ($env:CI) { Join-Path $root ".venv-ci" } else { Join-Path $env:USERPROFILE ".venvs\truestretch" }
$py    = Join-Path $venv "Scripts\python.exe"
$work  = Join-Path $env:LOCALAPPDATA "TrueStretch-build"   # outside OneDrive so it doesn't sync build junk
$dist  = Join-Path $root "dist"
# One source of truth for the version: truestretch/__init__.py (VERSION = "X.Y.Z")
$version = [regex]::Match((Get-Content (Join-Path $root "truestretch\__init__.py") -Raw), 'VERSION = "(\d+\.\d+\.\d+)"').Groups[1].Value
if (-not $version) { throw "VERSION not found in truestretch\__init__.py" }

if (-not (Test-Path $py)) {
    Write-Host "Creating build environment in $venv ..."
    python -m venv $venv
}
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r (Join-Path $root "requirements.txt")
if ($Protected) {
    & $py -m pip install --quiet "nuitka==2.8.10" ordered-set zstandard
    # Keep Nuitka's downloaded compiler in a short folder: gcc builds include paths like
    # ...\lib\gcc\x86_64-w64-mingw32\14.2.0\..\..\..\..\include\... and in a deep folder they pass Windows'
    # 260-character limit, so headers "go missing" (fatal error: ...h: No such file or directory).
    $env:NUITKA_CACHE_DIR = Join-Path $env:USERPROFILE ".nuitka"
}

Write-Host "Rendering app icon ..."
& $py (Join-Path $root "tools\make_icon.py")

New-Item -ItemType Directory -Force $dist | Out-Null
$assets = Join-Path $root "assets"
$icon   = Join-Path $assets "app.ico"
$main   = Join-Path $root "main.py"

if ($Protected) {
    Write-Host "Compiling with Nuitka (this takes a while) ..."
    & $py -m nuitka $main `
        --onefile --onefile-no-dll --windows-console-mode=disable --enable-plugin=pyside6 --mingw64 `
        --onefile-tempdir-spec="{CACHE_DIR}/{COMPANY}/{VERSION}" `
        --copyright="Copyright (c) 2026 candyqueenjr" `
        --include-data-dir="$assets=assets" `
        --windows-icon-from-ico="$icon" `
        --company-name="TrueStretch" --product-name="TrueStretch" `
        --file-version="$version.0" --product-version="$version.0" `
        --file-description="TrueStretch - true stretched resolution for games" `
        --output-dir="$work\nuitka" --output-filename="TrueStretch.exe" `
        --assume-yes-for-downloads --remove-output
    Copy-Item "$work\nuitka\TrueStretch.exe" (Join-Path $dist "TrueStretch.exe") -Force
} else {
    Write-Host "Packaging with PyInstaller ..."
    & $py -m PyInstaller $main `
        --noconfirm --clean --onefile --windowed `
        --name TrueStretch `
        --icon "$icon" `
        --version-file (Join-Path $root "tools\version_info.txt") `
        --add-data "$assets;assets" `
        --exclude-module tkinter `
        --distpath $dist --workpath "$work\pyinstaller" --specpath $work
}
if ($LASTEXITCODE -ne 0) { throw "Build failed (exit code $LASTEXITCODE)." }

$exe = Get-Item (Join-Path $dist "TrueStretch.exe")
$hash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash
"{0}  TrueStretch.exe" -f $hash | Set-Content (Join-Path $dist "TrueStretch.exe.sha256") -Encoding ascii
Write-Host ""
Write-Host ("Built {0}  ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB))
Write-Host "SHA-256: $hash"
