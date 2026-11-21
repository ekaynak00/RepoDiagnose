@echo off
setlocal
chcp 65001 >nul
title RepoDiagnose
cd /d "%~dp0"

rem --- Find Python (py launcher or python) ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python was not found.
    echo  Install Python 3.10 or newer from https://www.python.org/downloads/
    echo  During setup, tick "Add python.exe to PATH".
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

rem --- First run: create a private environment (does not affect other Python work) ---
if not exist ".venv\Scripts\pythonw.exe" (
    echo  First run: installing the packages RepoDiagnose needs. This happens once and may take 1-2 minutes...
    %PY% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
)

rem --- Repair missing packages ---
".venv\Scripts\python.exe" -c "import tkinter, requests, numpy, matplotlib, openpyxl, sv_ttk" >nul 2>&1
if errorlevel 1 (
    echo  Completing missing packages...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
    ".venv\Scripts\python.exe" -c "import tkinter" >nul 2>&1 || (
        echo  Your Python installation has no tkinter. Reinstall Python from python.org and tick "tcl/tk and IDLE".
        pause
        exit /b 1
    )
)

rem --- Start the app without a console window ---
start "" ".venv\Scripts\pythonw.exe" "%~dp0repodiagnose.py"
exit /b 0

:fail
echo.
echo  Setup failed. Check your internet connection and try again.
echo  If it keeps failing, delete the .venv folder here and run run.bat again.
pause
exit /b 1
