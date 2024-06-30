$Host.UI.RawUI.WindowTitle = "home-scraper"
Set-Location "D:\Projects\_Projects_Synced\home-scraper"
python generate_html_from_housing_emails.py | Tee-Object -FilePath "generate_html_from_housing_emails.log"
git commit -am "update site"
#git push
pause