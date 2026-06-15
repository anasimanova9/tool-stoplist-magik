@echo off
chcp 1251 >nul
cd /d "%~dp0"

echo ==========================================
echo   Scan Brands (TitleKW)
echo ==========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo ERROR: Run start.bat first to create venv
    pause
    exit /b 1
)

venv\Scripts\python.exe scan_brands.py
pause
