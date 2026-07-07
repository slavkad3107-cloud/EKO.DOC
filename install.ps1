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

# 6. Автоустановка внешних компонентов (Tesseract-OCR, LibreOffice) через winget
Write-Host ""
Write-Host "=== Дополнительные компоненты ===" -ForegroundColor Cyan

function Find-Tesseract {
    $c = (Get-Command tesseract -ErrorAction SilentlyContinue).Source
    if ($c) { return $c }
    foreach ($p in @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                     "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
                     "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$winget = (Get-Command winget -ErrorAction SilentlyContinue) -ne $null

# --- Tesseract-OCR (распознавание сканов и фото) ---
$tess = Find-Tesseract
if (-not $tess) {
    if ($winget) {
        Write-Host "Ставлю Tesseract-OCR (winget)..."
        winget install --id UB-Mannheim.TesseractOCR -e --silent `
            --accept-source-agreements --accept-package-agreements
        $tess = Find-Tesseract
    } else {
        Write-Host "- winget не найден. Tesseract-OCR поставьте вручную:" -ForegroundColor Yellow
        Write-Host "  https://github.com/UB-Mannheim/tesseract/wiki"
    }
}
if ($tess) {
    Write-Host "Tesseract: $tess"
    # Русский язык. Папка Program Files требует прав админа, поэтому держим
    # языки в пользовательской папке (приложение её находит по TESSDATA_PREFIX).
    $sysTd = Join-Path (Split-Path $tess -Parent) "tessdata"
    $userTd = "$env:LOCALAPPDATA\EcoDoc\tessdata"
    New-Item -ItemType Directory -Force $userTd | Out-Null
    foreach ($l in @("eng.traineddata", "osd.traineddata")) {
        if ((Test-Path (Join-Path $sysTd $l)) -and -not (Test-Path (Join-Path $userTd $l))) {
            Copy-Item (Join-Path $sysTd $l) (Join-Path $userTd $l) -Force
        }
    }
    if (-not (Test-Path "$userTd\rus.traineddata")) {
        Write-Host "Догружаю русский языковой пакет (~19 МБ)..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing `
                "https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata" `
                -OutFile "$userTd\rus.traineddata"
            Write-Host "  Русский язык установлен."
        } catch {
            Write-Host "  Не удалось скачать rus.traineddata — проверьте интернет." -ForegroundColor Yellow
        }
    }
}

# --- LibreOffice (запасное чтение старых .doc/.rtf) ---
$soffice = (Get-Command soffice -ErrorAction SilentlyContinue).Source
if (-not $soffice) { $soffice = "$env:ProgramFiles\LibreOffice\program\soffice.exe" }
if (-not (Test-Path $soffice)) {
    if ($winget) {
        Write-Host "Ставлю LibreOffice (winget, для старых .doc)..."
        winget install --id TheDocumentFoundation.LibreOffice -e --silent `
            --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "- LibreOffice не установлен (нужен для части старых .doc)." -ForegroundColor Yellow
    }
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "- Ollama (локальный ИИ) — по желанию: https://ollama.com, затем ollama pull qwen2.5:7b"
}

Write-Host ""
Write-Host "=== Готово ===" -ForegroundColor Green
Write-Host "Графический интерфейс: двойной щелчок по файлу  ЭКО.DOC.bat"
Write-Host "Или в консоли:  ecodoc gui   (список форм:  ecodoc list)"
Write-Host "Быстрый старт: README.md (org add -> site add -> intake -> generate)"
