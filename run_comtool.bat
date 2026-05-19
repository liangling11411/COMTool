@echo off
setlocal

cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo Cannot find venv\Scripts\pythonw.exe.
    echo Please run dependency setup first.
    pause
    exit /b 1
)

set "APPDATA=%CD%\venv\appdata"
set "LOCALAPPDATA=%CD%\venv\localappdata"

start "" "%CD%\venv\Scripts\pythonw.exe" "%CD%\COMTool\Main.py"
