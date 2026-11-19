@echo off
rem CBC Designer - start the program on Windows.
rem First run: creates a private Python environment in the .venv folder and installs the libraries (needs internet once).
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from python.org and tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Preparing CBC Designer for first use, this takes a few minutes...
  py -3 -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)
if "%~1"=="" (
  if exist "CBC_EXPORT.txt" (
    start "" ".venv\Scripts\pythonw.exe" app.py --export "CBC_EXPORT.txt"
  ) else (
    start "" ".venv\Scripts\pythonw.exe" app.py
  )
) else (
  start "" ".venv\Scripts\pythonw.exe" app.py --export "%~1"
)
exit /b 0
:fail
echo Setup failed. Check the internet connection and run this file again.
pause
exit /b 1
