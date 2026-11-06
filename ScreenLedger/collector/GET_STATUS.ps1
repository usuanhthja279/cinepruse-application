param([string]$Date='2026-11-07',[string]$City='kolkata',[string]$MovieId='176276')
Set-Location $PSScriptRoot
& '.\.venv\Scripts\python.exe' collector_status.py --date $Date --city $City --movie-id $MovieId --out "collector_data\status_$Date`_$City.json"
