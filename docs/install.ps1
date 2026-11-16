# TrueStretch - one-command install, for PCs where Windows "Smart App Control" blocks TrueStretch.exe.
#
#   Open PowerShell (Start menu -> type "PowerShell" -> Enter) and paste:
#       irm https://candyqueenjr.github.io/TrueStretch/install.ps1 | iex
#
# What it does (nothing else):
#   1. Uses Python 3.12 if it's installed, otherwise downloads the official installer from python.org (signed by the
#      Python Software Foundation) and installs it for your Windows user only.
#   2. Creates a private Python environment in %LOCALAPPDATA%\TrueStretch-src\venv and installs PySide6 (signed by
#      The Qt Company) into it from pypi.org.
#   3. Downloads the source code of the latest TrueStretch release from GitHub into %LOCALAPPDATA%\TrueStretch-src\app.
#   4. Puts a "TrueStretch" launcher on your Desktop and in the Start menu, and starts TrueStretch.
#
# It doesn't change any Windows security setting. Every program that runs is signed by its maker, which is why
# Smart App Control allows it. TrueStretch then updates itself like the normal version. To remove it: delete the
# %LOCALAPPDATA%\TrueStretch-src folder and the two TrueStretch shortcuts.
#
# Written to work in PowerShell's Constrained Language mode (which Smart App Control turns on): cmdlets only.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # makes Invoke-WebRequest much faster
$Repo = 'candyqueenjr/TrueStretch'
$PyVersion = '3.12.10'
$Root = if ($env:TS_ROOT) { $env:TS_ROOT } else { Join-Path $env:LOCALAPPDATA 'TrueStretch-src' }

function Say($text) { Write-Host "  $text" }
function Step($text) { Write-Host ""; Write-Host "> $text" -ForegroundColor Cyan }
function Fail($text) {
    Write-Host ""; Write-Host "  $text" -ForegroundColor Red
    Write-Host "  Need help? https://github.com/$Repo/issues/new/choose" -ForegroundColor Red
    throw $text
}

Write-Host ""
Write-Host "  TRUESTRETCH - install without TrueStretch.exe" -ForegroundColor White
Write-Host "  Installs into $Root" -ForegroundColor DarkGray

# ---- 1. Python ----------------------------------------------------------------------------------------------------
Step "Looking for Python 3.12"
$Python = $null
$candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:ProgramFiles 'Python312\python.exe')
)
if ($env:TS_PYTHON) { $candidates = @($env:TS_PYTHON) + $candidates }
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $Python = $c; break } }
if (-not $Python) {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $found = & $py.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found -and (Test-Path $found)) { $Python = "$found".Trim() }
    }
}
if (-not $Python) {
    Say "Python 3.12 isn't installed. Downloading the official installer from python.org ..."
    $setup = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe" -OutFile $setup -UseBasicParsing
    Say "Installing Python $PyVersion for your user (about a minute) ..."
    $p = Start-Process $setup -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=1',
        'InstallLauncherAllUsers=0', 'Include_test=0', 'Include_doc=0' -Wait -PassThru
    Remove-Item $setup -ErrorAction SilentlyContinue
    $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if ($p.ExitCode -ne 0 -or -not (Test-Path $Python)) { Fail "Python didn't install (code $($p.ExitCode))." }
}
Say "Python: $Python"

# ---- 2. Environment with PySide6 ----------------------------------------------------------------------------------
Step "Preparing TrueStretch's Python environment"
New-Item -ItemType Directory -Force $Root | Out-Null
$Venv = Join-Path $Root 'venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) { Fail "Couldn't create the Python environment." }
}

# ---- 3. TrueStretch source ----------------------------------------------------------------------------------------
Step "Downloading TrueStretch"
if ($env:TS_SOURCE_ZIP) {
    $Tag = if ($env:TS_TAG) { $env:TS_TAG } else { 'local' }
    $zip = $env:TS_SOURCE_ZIP
} else {
    $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ 'User-Agent' = 'TrueStretch-Installer' }
    $Tag = $rel.tag_name
    $zip = Join-Path $env:TEMP "TrueStretch-$Tag.zip"
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/tags/$Tag.zip" -OutFile $zip -UseBasicParsing
}
Say "Version: $Tag"
$staging = Join-Path $Root 'app.staging'
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
# Python's own unzip: PowerShell's Expand-Archive module can't always load in Constrained Language mode.
& $VenvPy -m zipfile -e $zip $staging
if ($LASTEXITCODE -ne 0) { Fail "Couldn't unpack the download." }
if (-not $env:TS_SOURCE_ZIP) { Remove-Item $zip -ErrorAction SilentlyContinue }
$top = Get-ChildItem $staging -Directory | Select-Object -First 1
if (-not $top -or -not (Test-Path (Join-Path $top.FullName 'main.py'))) { Fail "The download doesn't look like TrueStretch." }
if (-not (Test-Path (Join-Path $top.FullName 'tools\launcher.pyw'))) {
    Fail "This TrueStretch version ($Tag) can't be installed this way yet - try again after the next update."
}

$App = Join-Path $Root 'app'
$New = Join-Path $Root 'app.new'
if (Test-Path $New) { Remove-Item $New -Recurse -Force }
Move-Item $top.FullName $New
Remove-Item $staging -Recurse -Force
# Put it in place now; if TrueStretch is running from it, the launcher swaps it in at the next start instead.
try {
    if (Test-Path $App) { Remove-Item $App -Recurse -Force }
    Move-Item $New $App
} catch {
    Say "TrueStretch is open, so the new version starts the next time you open it."
}
$Src = if (Test-Path (Join-Path $App 'main.py')) { $App } else { $New }

Step "Installing PySide6 (the window toolkit, about 80 MB)"
$req = Get-Content (Join-Path $Src 'requirements.txt') -Raw
$QtVersion = if ($req -match '(?m)^PySide6(?:-Essentials)?==([\w.]+)') { $Matches[1] } else { '6.12.0' }
& $VenvPy -m pip install --quiet --disable-pip-version-check --upgrade pip
& $VenvPy -m pip install --quiet --disable-pip-version-check "PySide6-Essentials==$QtVersion"
if ($LASTEXITCODE -ne 0) { Fail "Couldn't install PySide6 (check your internet connection and run the command again)." }

# ---- 4. Shortcuts + start -----------------------------------------------------------------------------------------
Step "Adding TrueStretch to your Desktop and Start menu"
$finish = @((Join-Path $Src 'tools\source_install.py'), $Tag)
if ($env:TS_NO_SHORTCUTS) { $finish += '--no-shortcuts' }
& $VenvPy @finish
if ($LASTEXITCODE -ne 0) { Fail "Couldn't finish the install." }

if (-not $env:TS_NO_START) {
    Step "Starting TrueStretch"
    Start-Process (Join-Path $Venv 'Scripts\pythonw.exe') -ArgumentList ('"' + (Join-Path $Root 'launcher.pyw') + '"')
}
Write-Host ""
Write-Host "  Done. Next time, open TrueStretch from your Desktop or the Start menu." -ForegroundColor Green
Write-Host ""
