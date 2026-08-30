$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name FlashTrombi `
  --add-data "app.py;." `
  --collect-all streamlit `
  --collect-all altair `
  --collect-all rapidocr `
  --collect-all onnxruntime `
  launcher.py

$IsccCandidates = @(
  "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
  throw "Inno Setup 6 n'est pas installé. Installe-le puis relance ce script."
}

& $Iscc "installer\FlashTrombi.iss"
Write-Host "Installateur créé dans installer-output\FlashTrombi-Setup.exe"
