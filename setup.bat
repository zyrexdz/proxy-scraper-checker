@echo off
setlocal

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found in PATH.
    pause
    exit /b 1
)

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

echo Starting scraper...
python main.py
pause
