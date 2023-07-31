CD /D D:\Projects\_Projects_Synced\home-scraper
echo "Scraping emails to html"
python generate_html_from_housing_emails.py
echo "Pushing new html"
git add index.html
git commit -m "update site"
git push
pause
