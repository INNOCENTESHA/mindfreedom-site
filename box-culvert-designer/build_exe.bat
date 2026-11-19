@echo off
rem Builds a stand-alone CBC_Designer.exe (no Python needed on the user's computer). Run once on a Windows machine.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call CBC_Designer.bat
".venv\Scripts\python.exe" -m pip install pyinstaller || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --name CBC_Designer --collect-submodules cbcdraw --collect-submodules detailing --collect-data ezdxf app.py
echo.
echo The program is in dist\CBC_Designer\CBC_Designer.exe  - copy the generator folder next to it for the drawing sheets.
pause
