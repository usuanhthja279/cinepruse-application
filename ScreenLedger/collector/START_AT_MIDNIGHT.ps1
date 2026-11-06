# ScreenLedger 2026-11-07 IST run; District source only.
# Live mode requires independent provider authorization and -AuthorizedLive.
param(
  [string]$Date = '2026-11-07',
  [string]$City = 'kolkata',
  [string]$MovieId = '176276',
  [string]$MovieSlug = 'ramayana',
  [switch]$AuthorizedLive
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.\.venv\Scripts\python.exe')) { py -3 -m venv .venv }
$Python = '.\.venv\Scripts\python.exe'
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependencies could not be installed.' }
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed. Refusing to launch.' }
Write-Host 'Unit tests passed. Offline fixture schedule is available with:'
Write-Host "$Python smart_collector.py --plan-fixture fixtures/ramayana_kolkata_2026-11-06.html --date 2026-11-06 --observed-at '2026-11-06T20:26:56+05:30'"
if (-not $AuthorizedLive) {
  Write-Warning 'No live collection started. -AuthorizedLive is required AND provider permission must be obtained first.'
  exit 0
}
Write-Host "Arming collector for midnight IST: $Date / $City / $MovieSlug"
& $Python smart_collector.py --live-authorized --acknowledge-permission --date $Date --city $City --movie-id $MovieId --movie-slug $MovieSlug --final-minutes 5 --store collector_data
exit $LASTEXITCODE
