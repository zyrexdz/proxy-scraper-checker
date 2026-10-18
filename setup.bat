@echo off
REM Zyre Proxy Scraper & Checker — Windows setup
setlocal

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found in PATH.
    echo Install Python 3.9+ from https://python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Upgrading pip...
python -m pip install -q --upgrade pip

echo Installing dependencies...
pip install -q -r requirements.txt

echo.
echo Setup complete. Run the scraper with:
echo   python main.py
echo.
echo Press any key to launch the wizard, or close this window.
pause >nul
python main.py
