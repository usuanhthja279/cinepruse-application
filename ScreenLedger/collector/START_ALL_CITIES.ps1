param(
  [string]$Date = '2026-11-07',
  [string]$CityList = '.\data\cities\district_movies_cities_2026-11-07.json',
  [switch]$AuthorizedLive
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:TEMP = Join-Path $PSScriptRoot '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$Python = '.\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Collector environment is missing; run START_AT_MIDNIGHT.ps1 setup first.' }
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Offline tests failed. Refusing to launch live collection.' }
& $Python multi_city_scheduler.py --cities $CityList --date $Date --plan-only
if ($LASTEXITCODE -ne 0) { throw 'City roster planning failed.' }
if (-not $AuthorizedLive) {
  Write-Warning 'Planning only. Add -AuthorizedLive only when approved District collection is intended.'
  exit 0
}
Write-Host 'Starting District multi-city live collection. The first sweep checks the selector roster; later hourly sweeps use only cities with successful validated captures. Transient errors get one retry; 404 and unrecognized pages are recorded without retry. One worker is reserved for T-5 pre-show scans.'
& $Python multi_city_scheduler.py --cities $CityList --date $Date --workers 5 --acknowledge-permission --store collector_data
exit $LASTEXITCODE
