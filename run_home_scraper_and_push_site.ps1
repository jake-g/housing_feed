# run_home_scraper_and_push_site.ps1
$Host.UI.RawUI.WindowTitle = "home-scraper"
Set-Location "D:\Projects\_Projects_Synced\home-scraper"

Write-Host "Updating dependencies..." -ForegroundColor Cyan
pip install --upgrade -r requirements.txt

# Run unit tests
Write-Host "Running unit tests..." -ForegroundColor Cyan
python -m pytest tests/ | Tee-Object -FilePath "logs\unit_tests.log"

#Run pre-commit checks
Write-Host "Running pre-commit checks..." -ForegroundColor Cyan
pre-commit run --all-files

# Fetch latest emails
Write-Host "Fetching latest emails and generating HTML feed..." -ForegroundColor Cyan
python fetch_emails.py

# 4. Parse dataset and generate report
Write-Host "Parsing full HTML dataset to structured TSV..." -ForegroundColor Cyan
python parse_html.py

# 5. Your specific HTML generation script
Write-Host "Generating final HTML..." -ForegroundColor Cyan
python generate_html_from_housing_emails.py | Tee-Object -FilePath "generate_html_from_housing_emails.log"

# 6. Git Operations
Write-Host "Committing and pushing changes..." -ForegroundColor Yellow
git add listings/*.html index.html housing_database.tsv *.md plots/*.png
git commit -m "update site"
git push

Write-Host "Done." -ForegroundColor Green

pause
