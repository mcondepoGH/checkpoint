# Smoke test del instalador: instalación silenciosa SIN login, consulta al puerto 8088 y desinstalación.
# Uso, desde la raíz del repositorio (tras build.ps1):  pwsh packaging/windows/smoke.ps1
# Comprueba: el hub responde, /api/session dice noLogin, la web (frontend) se sirve y el zip del plugin de Deck existe.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$version = (Get-Content (Join-Path $root VERSION) -Raw).Trim()
$exe = Join-Path $root "packaging\windows\Output\Checkpoint-Setup-$version.exe"
if (-not (Test-Path $exe)) { throw "No existe ${exe}: ejecuta antes build.ps1" }
# Join-Path con $null lanza un error (y con $ErrorActionPreference Stop aborta): se elige la base antes.
$base = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$dir = Join-Path $base "checkpoint-smoke"

$p = Start-Process $exe -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOLOGIN=1", "/DIR=`"$dir`"", "/LOG=`"$dir.log`"" -PassThru
# WaitForExit y no `-Wait`: Start-Process -Wait también espera a los procesos hijos, y el instalador deja el hub en marcha.
$p.WaitForExit()
if ($p.ExitCode -ne 0) { if (Test-Path "$dir.log") { Get-Content "$dir.log" -Tail 40 }; throw "El instalador salió con código $($p.ExitCode)" }

try {
  $session = $null
  for ($i = 0; $i -lt 60 -and -not $session; $i++) {
    try { $session = Invoke-RestMethod "http://127.0.0.1:8088/api/session" -TimeoutSec 3 } catch { Start-Sleep -Seconds 2 }
  }
  if (-not $session) {
    $log = Join-Path $env:APPDATA "checkpoint\logs\checkpoint.log"
    if (Test-Path $log) { Get-Content $log -Tail 60 }
    throw "El hub no responde en 127.0.0.1:8088 tras 120 s"
  }
  if ($session.noLogin -ne $true) { throw "Se esperaba noLogin=true: $($session | ConvertTo-Json -Compress)" }
  $page = Invoke-WebRequest "http://127.0.0.1:8088/" -UseBasicParsing -TimeoutSec 10
  if ($page.StatusCode -ne 200 -or $page.Content -notmatch "<div id=`"root`"") { throw "La web no se sirve (frontend no incluido)" }
  $zip = Invoke-WebRequest "http://127.0.0.1:8088/api/deck/plugin" -UseBasicParsing -TimeoutSec 10
  if ($zip.StatusCode -ne 200 -or $zip.Content.Length -lt 1000) { throw "El zip del plugin de Deck no se sirve" }
  Write-Host "OK: hub $version en 8088, noLogin, web y plugin de Deck servidos"
}
finally {
  Get-Process checkpoint -ErrorAction SilentlyContinue | Stop-Process -Force
  $unins = Join-Path $dir "unins000.exe"
  if (Test-Path $unins) {
    $u = Start-Process $unins -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -PassThru
    $u.WaitForExit()
    # El desinstalador de Inno se relanza desde %TEMP% y el proceso original sale antes de acabar: se espera a que desaparezca.
    for ($i = 0; $i -lt 30 -and (Test-Path $unins); $i++) { Start-Sleep -Seconds 1 }
    if (Test-Path $unins) { Write-Warning "La desinstalación no terminó en 30 s" }
  }
}
