@echo off
rem ============================================================
rem  EKO.DOC - launcher grafichеskogo interfeisa (double-click)
rem  Otkryvaet brauzer s interfeisom. Zakryt' okno = ostanovit'.
rem ============================================================
chcp 65001 >nul
title EKO.DOC
cd /d "%~dp0"

if exist ".venv\Scripts\ecodoc.exe" (
    ".venv\Scripts\ecodoc.exe" gui
    goto :eof
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m ecodoc gui
    goto :eof
)

echo.
echo [!] Okruzhenie ne naideno (.venv).
echo     Snachala zapustite  install.bat  - on postavit zavisimosti.
echo.
pause
