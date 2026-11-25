# Construye el instalador de Windows: frontend, zip del plugin de Deck, PyInstaller e Inno Setup.
# Lo usan el job `windows-installer` de ci.yml y el job `windows` de release.yml (los dos corren en windows-latest).
# Requisitos del entorno: Python 3.12, Node, Git Bash (bash) e Inno Setup (iscc; se instala con choco si falta).
# Uso, desde la raíz del repositorio:  pwsh packaging/windows/build.ps1 [-Tag v2.5.0]
# Con -Tag comprueba que VERSION coincide con el tag. Salida (packaging\windows\Output):
#   Checkpoint-Setup-<versión>.exe  y  Checkpoint-Setup-<versión>.exe.sha256  («<hash>  <nombre>», sin BOM).
param([string]$Tag = "")
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$version = (Get-Content VERSION -Raw).Trim()
if ($Tag -ne "" -and $Tag -ne "v$version") { throw "VERSION ($version) no coincide con el tag $Tag" }
Write-Host "== Checkpoint $version =="

Write-Host "== 1/5 frontend =="
Push-Location frontend
npm ci --no-audit --no-fund
npm run build
Pop-Location

Write-Host "== 2/5 plugin de Steam Deck (con el manifiesto de rutas de guardado, igual que el Dockerfile) =="
python -m pip install --disable-pip-version-check -r backend/requirements.txt -r packaging/windows/requirements.txt
$commit = [regex]::Match((Get-Content Dockerfile -Raw), "ARG LUDUSAVI_MANIFEST_COMMIT=([0-9a-f]{40})").Groups[1].Value
if (-not $commit) { throw "No se encontró LUDUSAVI_MANIFEST_COMMIT en el Dockerfile" }
$work = Join-Path $env:TEMP "checkpoint-manifest"
New-Item -ItemType Directory -Force $work | Out-Null
Invoke-WebRequest "https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/$commit/data/manifest.yaml" -OutFile "$work\manifest.yaml"
python -I checkpoint-deck/scripts/gen_save_manifest.py "$work\manifest.yaml" "$work\save_manifest.json" --commit $commit
if (-not (Test-Path "$work\save_manifest.json") -or (Get-Item "$work\save_manifest.json").Length -eq 0) { throw "save_manifest.json vacío" }
npm install -g pnpm@9 --no-audit --no-fund
Push-Location checkpoint-deck
pnpm install --frozen-lockfile
$env:SAVE_MANIFEST = "$work\save_manifest.json"
pnpm run zip
Pop-Location
if (-not (Test-Path checkpoint-deck/out/Checkpoint.zip)) { throw "No se generó checkpoint-deck/out/Checkpoint.zip" }

Write-Host "== 3/5 PyInstaller =="
pyinstaller --noconfirm --distpath packaging/windows/dist --workpath packaging/windows/build packaging/windows/checkpoint.spec
if (-not (Test-Path packaging/windows/dist/checkpoint/checkpoint.exe)) { throw "PyInstaller no generó checkpoint.exe" }

Write-Host "== 4/5 Inno Setup =="
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
  foreach ($p in "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") { if (Test-Path $p) { $iscc = $p; break } }
}
if (-not $iscc) { choco install innosetup --no-progress -y; $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc "/DAppVersion=$version" packaging\windows\installer.iss

Write-Host "== 5/5 hash =="
$name = "Checkpoint-Setup-$version.exe"
$exe = Join-Path $root "packaging\windows\Output\$name"
if (-not (Test-Path $exe)) { throw "No existe $exe" }
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$exe.sha256", "$hash  $name`n", (New-Object Text.UTF8Encoding $false))
Write-Host "$name  sha256=$hash"
