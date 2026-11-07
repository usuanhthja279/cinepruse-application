param(
    [string]$ServiceDate = (Get-Date).ToString('yyyy-MM-dd'),
    [int]$Workers = 5
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' 'multi_city_scheduler.py' `
    --cities '.\data\cities\district_movies_cities_2026-11-07.json' `
    --date $ServiceDate --workers $Workers --acknowledge-permission --store '.\collector_data'
if ($LASTEXITCODE -ne 0) {
    Write-Host "Scheduler exited with code $LASTEXITCODE. Press Enter to close this monitor."
    [void](Read-Host)
}
