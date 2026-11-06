$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    try { py -3 -m venv .venv }
    catch { python -m venv .venv }
}
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& $python district_extractor.py --html fixtures/ramayana_kolkata_2026-11-06.html --city kolkata --out output
if ($LASTEXITCODE -ne 0) { throw "Offline extraction failed" }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
Write-Host "`nCollection estimate:" -ForegroundColor Cyan
Get-Content output\unique_collection_summary.json
