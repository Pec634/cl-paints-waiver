@echo off
setlocal
cd /d "%~dp0"
if exist "dist\LocalSpeechToText\data" goto preserve
if exist "dist\LocalSpeechToText\recordings" goto preserve
if not exist ".venv\Scripts\python.exe" (
    echo Run Setup.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.16,<7"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm LocalSpeechToText.spec
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" package_release.py
if errorlevel 1 exit /b 1
echo Ready to share: dist\LocalSpeechToText-Windows.zip
pause
exit /b 0
:preserve
echo Move the existing LocalSpeechToText folder out of dist before rebuilding.
echo It contains saved workspaces or recordings that must be preserved.
pause
exit /b 1
