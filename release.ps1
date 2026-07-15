# ЭКО.DOC — релиз: zip + РАСПАКОВАННАЯ папка с номером версии + тег + пуш.
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

# 3. РАСПАКОВАННАЯ рабочая папка с номером версии (правило: новая версия =
#    новая папка EKO.DOC-v<номер>, готовая к запуску). .venv переносится из
#    предыдущей распакованной установки — переустановка не нужна.
$dst = "$hub\releases\EKO.DOC-v$v"
if (-not (Test-Path $dst)) {
    Expand-Archive -Path $zip -DestinationPath $dst
    $prev = Get-ChildItem "$hub\releases" -Directory |
        Where-Object { $_.Name -match '^EKO\.DOC-v[\d.]+$' -and $_.Name -ne "EKO.DOC-v$v" } |
        Sort-Object { [version]($_.Name -replace '^EKO\.DOC-v','') } | Select-Object -Last 1
    if ($prev -and (Test-Path "$($prev.FullName)\.venv") -and -not (Test-Path "$dst\.venv")) {
        Write-Host "Переношу .venv из $($prev.Name)…"
        robocopy "$($prev.FullName)\.venv" "$dst\.venv" /E /NFL /NDL /NJH /NJS | Out-Null
    }
    Write-Host "Распакована: $dst"
} else {
    Write-Host "Папка $dst уже существует — код обновите zip'ом вручную."
}

# 4. вся документация — в OneDrive-хаб
Copy-Item README.md, CHANGELOG.md, LICENSE, requirements.txt, pyproject.toml "$hub\" -Force
Copy-Item docs\* "$hub\docs\" -Force

# 5. тег версии + пуш на GitHub (тег виден на странице Releases/Tags)
git tag -a "v$v" -m "v$v" 2>$null
git push -u origin main
git push origin --tags
Write-Host "Опубликовано: v$v -> https://github.com/slavkad3107-cloud/EKO.DOC" -ForegroundColor Green
