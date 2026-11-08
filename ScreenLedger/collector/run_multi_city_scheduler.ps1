param(
    [string]$ServiceDate = (Get-Date).ToString('yyyy-MM-dd'),
    [int]$Workers = 5,
    [string]$StartAt = '',
    [int]$FirstDayHour = 0
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$schedulerArgs = @('multi_city_scheduler.py', '--cities', '.\data\cities\district_movies_cities_2026-11-07.json',
    '--date', $ServiceDate, '--workers', $Workers, '--first-day-hour', $FirstDayHour,
    '--acknowledge-permission', '--store', '.\collector_data')
if ($StartAt) { $schedulerArgs += @('--start-at', $StartAt) }
& '.\.venv\Scripts\python.exe' @schedulerArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Scheduler exited with code $LASTEXITCODE. Press Enter to close this monitor."
    [void](Read-Host)
}
