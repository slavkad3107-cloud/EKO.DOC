@echo off
rem ЭКО.DOC — автоустановщик: двойной щелчок по этому файлу
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
