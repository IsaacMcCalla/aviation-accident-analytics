# Export the web snapshot and publish it: commits web/data/accidents.db and pushes to GitHub.
# Streamlit Community Cloud redeploys the public site within a minute or two of the push.
# Run after the monthly update:  .\publish_web.ps1
param([string]$Message = "Update web data")

Set-Location $PSScriptRoot

& .\.venv\Scripts\python.exe src\export_web_data.py
if ($LASTEXITCODE -ne 0) { Write-Error "Export failed; nothing published. See logs\export_web_data.log"; exit 1 }

git add web/data/accidents.db
git diff --cached --quiet -- web/data/accidents.db
if ($LASTEXITCODE -eq 0) { "No data changes to publish."; exit 0 }

git commit -m "$Message ($(Get-Date -Format yyyy-MM-dd))" -- web/data/accidents.db
if ($LASTEXITCODE -ne 0) { Write-Error "Commit failed; nothing published."; exit 1 }

git push
if ($LASTEXITCODE -ne 0) { Write-Error "Push failed. The commit is saved locally; run 'git push' once the problem is fixed."; exit 1 }

"Published. The site updates in a minute or two."
