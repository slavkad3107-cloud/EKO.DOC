# ЭКО.DOC — релиз: zip с номером версии в OneDrive + документация + пуш.
# Хранилище релизов и документации: C:\Users\veter\OneDrive\II\ЭКОДОК
# Запуск после изменения версии в ecodoc/__init__.py:
#   powershell -ExecutionPolicy Bypass -File release.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

$hub = "C:\Users\veter\OneDrive\II\ЭКОДОК"
New-Item -ItemType Directory -Force "$hub\releases", "$hub\docs" | Out-Null

# версия — из ecodoc/__init__.py (единственный источник правды)
$init = Get-Content "ecodoc\__init__.py" -Raw -Encoding UTF8
if ($init -notmatch '__version__\s*=\s*"([^"]+)"') { throw "версия не найдена" }
$v = $Matches[1]

# 1. коммит текущих изменений (если есть)
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit -m "v$v" }

# 2. zip с версией в имени — ТОЛЬКО в OneDrive (в репозиторий не кладём)
$zip = "$hub\releases\EKO.DOC-v$v.zip"
git archive --format=zip -o $zip HEAD
Write-Host "Zip: $zip"

# 3. вся документация — в OneDrive-хаб
Copy-Item README.md, CHANGELOG.md, LICENSE, requirements.txt, pyproject.toml "$hub\" -Force
Copy-Item docs\* "$hub\docs\" -Force

# 4. пуш на GitHub
git push -u origin main
Write-Host "Опубликовано: v$v -> https://github.com/slavkad3107-cloud/EKO.DOC" -ForegroundColor Green
