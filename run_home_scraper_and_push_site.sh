#!/bin/bash
# run_home_scraper_and_push_site.sh

cd "$(dirname "$0")"

source .venv/bin/activate

echo "Running unit tests..."
python3 -m pytest tests/ | tee logs/unit_tests.log

echo "Running pre-commit checks..."
pre-commit run --all-files

echo "Fetching latest emails and generating HTML feed..."
python3 fetch_emails.py

echo "Parsing full HTML dataset to structured TSV and generating statistics report..."
python3 parse_html.py

echo "Committing and pushing changes..."
git add listings/*.html index.html housing_database.tsv *.md plots/*.png
git commit -am "update site"
git push

echo "Done."
