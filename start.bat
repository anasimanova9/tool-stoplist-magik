@echo off
chcp 1251 >nul
cd /d "%~dp0"

echo ==========================================
echo   Stop-List Tool
echo ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found! Install from https://python.org
    pause
    exit /b 1
)

:: Create venv if needed
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment
        pause
        exit /b 1
    )
)

:: Install dependencies using venv python directly (no activate needed)
echo Checking dependencies...
venv\Scripts\python.exe -m pip install -r requirements.txt --quiet 2>nul

:: Run the app
echo.
echo Server starting at http://localhost:5555
echo Press Ctrl+C to stop
echo.
venv\Scripts\python.exe app.py
pause
