@echo off
rem ============================================================
rem  EKO.DOC - launcher grafichеskogo interfeisa (double-click)
rem  Otkryvaet brauzer s interfeisom. Zakryt' okno = ostanovit'.
rem
rem  VAZHNO: zapuskaem "python -m ecodoc" iz papki relisa, a ne
rem  ecodoc.exe. Exe beret kod iz editable-ustanovki venv, kotoraya
rem  posle perenosa .venv iz staroi versii ukazyvaet na STARUYU papku
rem  (tak polzovatel' na v0.59 rabotal s kodom v0.42/0.52). "-m" stavit
rem  tekushchuyu papku pervoi v sys.path - vsegda kod etogo relisa.
rem ============================================================
chcp 65001 >nul
title EKO.DOC
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m ecodoc gui
    goto :eof
)

echo.
echo [!] Okruzhenie ne naideno (.venv).
echo     Snachala zapustite  install.bat  - on postavit zavisimosti.
echo.
pause
