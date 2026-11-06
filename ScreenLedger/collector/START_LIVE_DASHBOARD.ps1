$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Collector Python environment is missing.' }
$base = Join-Path $PSScriptRoot 'collector_data\logs'
New-Item -ItemType Directory -Force -Path $base | Out-Null
$out = Join-Path $base 'live_dashboard_stdout.log'
$err = Join-Path $base 'live_dashboard_stderr.log'
$url = 'http://127.0.0.1:8765/api/live/summary'
try {
  $existing = Invoke-RestMethod -Uri $url -TimeoutSec 2
  Write-Host 'ScreenLedger live dashboard is already running at http://127.0.0.1:8765/dashboard/live.html'
  exit 0
} catch { }
$process = Start-Process -FilePath $Python -ArgumentList @('live_dashboard_server.py','--host','127.0.0.1','--port','8765') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
Start-Sleep -Seconds 2
try {
  $health = Invoke-RestMethod -Uri $url -TimeoutSec 5
  Write-Host "ScreenLedger live dashboard is ready at http://127.0.0.1:8765/dashboard/live.html"
  Write-Host "Captured city feeds: $($health.captured_city_feeds) of $($health.target_city_feeds); unique sessions: $($health.unique_sessions)."
} catch {
  throw "Dashboard server did not become ready. See $out and $err. Process ID: $($process.Id)"
}
