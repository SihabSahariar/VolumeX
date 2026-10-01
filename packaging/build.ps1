# Builds dist\VolumeX\ (PyInstaller + VB-Audio's VB-CABLE package), dist\installer\VolumeX-win64.zip and,
# if Inno Setup 6 is installed, dist\installer\VolumeX-Setup.exe - the two release assets the website links to.
# Usage:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-Dist dist]
#   -Dist: output folder name, e.g. "dist-next" while a copy of VolumeX is running from dist\
param([string]$Dist = "dist")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create the venv first: python -m venv .venv; .venv\Scripts\pip install -e .[dev]" }

& $python -m pip install --quiet pyinstaller
& $python (Join-Path $root "packaging\fetch_vbcable.py")  # VB-Audio's official package, signature-checked
if ($LASTEXITCODE -ne 0) { throw "Couldn't fetch VB-CABLE" }
& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $root $Dist) --workpath (Join-Path $root "build") `
    (Join-Path $root "packaging\volumex.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$cable = Join-Path $root "$Dist\VolumeX\vbcable"
if (Test-Path $cable) { Remove-Item -Recurse -Force $cable }
Copy-Item -Recurse (Join-Path $root "third_party\vbcable") $cable
Write-Host "Built $(Join-Path $root "$Dist\VolumeX\VolumeX.exe") (with VB-CABLE by VB-Audio)"

# portable build for the release page (VolumeX-win64.zip)
$zip = Join-Path $root "$Dist\installer\VolumeX-win64.zip"
New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $root "$Dist\VolumeX") -DestinationPath $zip
Write-Host "Portable zip: $zip"

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppDist=..\$Dist\VolumeX" "/DOutDir=..\$Dist\installer" (Join-Path $root "packaging\installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Host "Inno Setup 6 not found - skipped the installer (https://jrsoftware.org/isinfo.php)"
}
