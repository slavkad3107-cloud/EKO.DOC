# ЭКО.DOC — сборка релиза: zip с номером версии + пуш на GitHub.
# Запуск после каждого изменения версии в ecodoc/__init__.py:
#   powershell -ExecutionPolicy Bypass -File release.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

# версия — из ecodoc/__init__.py (единственный источник правды)
$init = Get-Content "ecodoc\__init__.py" -Raw -Encoding UTF8
if ($init -notmatch '__version__\s*=\s*"([^"]+)"') { throw "версия не найдена" }
$v = $Matches[1]

git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "v$v"
}

# zip только из отслеживаемых файлов (без .venv/out/локальных данных)
New-Item -ItemType Directory -Force releases | Out-Null
$zip = "releases\EKO.DOC-v$v.zip"
git archive --format=zip -o $zip HEAD
git add $zip
git commit -m "release: EKO.DOC-v$v.zip"

git push -u origin main
Write-Host "Опубликовано: v$v -> https://github.com/slavkad3107-cloud/EKO.DOC" -ForegroundColor Green
Write-Host "Zip: $zip"
