$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $PSScriptRoot

Write-Host "Running unit tests..."
python -m pytest parse_html_test.py fetch_emails_test.py | Tee-Object -FilePath "logs/unit_tests.log"

Write-Host "Running pre-commit checks..."
pre-commit run --all-files

Write-Host "Fetching latest emails and generating HTML feed..."
python fetch_emails.py

Write-Host "Parsing full HTML dataset to structured TSV..."
python parse_html.py

Write-Host "Committing and pushing changes..."
git add *.html *.tsv *.md; git commit -am "update site"; git push
pause
