# ЭКО.DOC — автоустановщик (Windows PowerShell 5.1+)
# Запуск: правой кнопкой -> "Выполнить с помощью PowerShell", либо install.bat
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "=== Установка ЭКО.DOC ===" -ForegroundColor Cyan

# 1. Python >= 3.10
$py = $null
foreach ($cand in @("py -3", "python")) {
    try {
        $v = & $cand.Split()[0] $cand.Split()[1..99] --version 2>$null
        if ($v -match "Python 3\.(1[0-9]|[2-9][0-9])") { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.10+ не найден. Установите с https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "(при установке отметьте галочку 'Add python.exe to PATH')"
    exit 1
}
Write-Host "Python: $py ($(& $py.Split()[0] $py.Split()[1..99] --version))"

# 2. Виртуальное окружение
if (-not (Test-Path "$root\.venv")) {
    Write-Host "Создаю виртуальное окружение .venv ..."
    & $py.Split()[0] $py.Split()[1..99] -m venv "$root\.venv"
}
$venvPy = "$root\.venv\Scripts\python.exe"

# 3. Зависимости + сам пакет (команда `ecodoc` появится в .venv\Scripts)
Write-Host "Ставлю зависимости ..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -e ".[ocr,pdf]" --quiet
if ($LASTEXITCODE -ne 0) {
    # OCR/pdf-экстры не критичны — ставим ядро
    & $venvPy -m pip install -e . --quiet
}

# 4. Автообнаружение ИИ: Ollama (все модели), LM Studio, ключи внешних API
Write-Host ""
Write-Host "=== Поиск ИИ на этой машине ===" -ForegroundColor Cyan
& $venvPy -m ecodoc ai setup

# 5. Подсказки по необязательным компонентам
Write-Host ""
Write-Host "=== Дополнительно (по желанию) ===" -ForegroundColor Cyan
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "• Ollama не найдена — для локального ИИ-анализа: https://ollama.com"
    Write-Host "  затем:  ollama pull qwen2.5:7b   и повторите  ecodoc ai setup"
}
if (-not (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    Write-Host "• Tesseract-OCR не найден — сканы/jpg распознаваться не будут."
    Write-Host "  https://github.com/UB-Mannheim/tesseract/wiki (+ пакет 'rus')"
}

Write-Host ""
Write-Host "=== Готово ===" -ForegroundColor Green
Write-Host "Запуск:      .venv\Scripts\ecodoc list"
Write-Host "Быстрый старт: см. README.md (org add -> site add -> intake -> generate)"
