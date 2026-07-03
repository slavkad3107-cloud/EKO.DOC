# ЭКО.DOC — автоустановщик (Windows PowerShell 5.1+)
# Запуск: двойной щелчок по install.bat (из любой папки, где распакован архив)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "=== Установка ЭКО.DOC ===" -ForegroundColor Cyan
Write-Host "Папка: $root"

# 1. Python >= 3.10
$python = ""
$pyArgs = @()
foreach ($cand in @("py", "python")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $a = @(); if ($cand -eq "py") { $a = @("-3") }
    try { $ver = (& $cand @a --version) 2>&1 } catch { continue }
    if ("$ver" -match "Python 3\.(1[0-9]|[2-9][0-9])") {
        $python = $cand; $pyArgs = $a; break
    }
}
if (-not $python) {
    Write-Host "Python 3.10+ не найден. Установите с https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "(при установке отметьте галочку 'Add python.exe to PATH')"
    exit 1
}
Write-Host "Python: $ver"

# 2. Виртуальное окружение
if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    Write-Host "Создаю виртуальное окружение .venv ..."
    & $python @pyArgs -m venv "$root\.venv"
}
$venvPy = "$root\.venv\Scripts\python.exe"

# 3. Зависимости + сам пакет (команда ecodoc)
Write-Host "Ставлю зависимости (1-3 минуты) ..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -e ".[ocr,pdf]" --quiet
if ($LASTEXITCODE -ne 0) {
    # OCR/pdf-экстры не критичны — ставим ядро
    & $venvPy -m pip install -e . --quiet
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ошибка установки зависимостей — проверьте интернет/прокси." -ForegroundColor Red
    exit 1
}

# 4. Команда ecodoc из ЛЮБОЙ папки: шим в %LOCALAPPDATA%\EcoDoc\bin + PATH
$bin = Join-Path $env:LOCALAPPDATA "EcoDoc\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
$shim = "@echo off`r`n`"$root\.venv\Scripts\ecodoc.exe`" %*`r`n"
# OEM-кодировка: cmd читает .bat в OEM, иначе кириллический путь ломается
Set-Content -Path "$bin\ecodoc.bat" -Value $shim -Encoding Oem
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*EcoDoc\bin*") {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(';') + ";" + $bin), "User")
    Write-Host "В PATH добавлено: $bin (откройте НОВУЮ консоль)"
}

# 5. Автообнаружение ИИ: Ollama (все модели), LM Studio, ключи внешних API
Write-Host ""
Write-Host "=== Поиск ИИ на этой машине ===" -ForegroundColor Cyan
& $venvPy -m ecodoc ai setup

# 6. Подсказки по необязательным компонентам
Write-Host ""
Write-Host "=== Дополнительно (по желанию) ===" -ForegroundColor Cyan
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "- Ollama не найдена. Для локального ИИ-анализа: https://ollama.com"
    Write-Host "  затем:  ollama pull qwen2.5:7b   и повторите  ecodoc ai setup"
}
if (-not (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    Write-Host "- Tesseract-OCR не найден: сканы/jpg распознаваться не будут."
    Write-Host "  https://github.com/UB-Mannheim/tesseract/wiki (+ пакет 'rus')"
}

Write-Host ""
Write-Host "=== Готово ===" -ForegroundColor Green
Write-Host "Откройте новую консоль (cmd) и выполните:  ecodoc list"
Write-Host "Быстрый старт: README.md (org add -> site add -> intake -> generate)"
