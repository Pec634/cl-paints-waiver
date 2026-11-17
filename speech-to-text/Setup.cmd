@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3 -m venv .venv
if not errorlevel 1 goto install
python -m venv .venv
if not errorlevel 1 goto install
echo Install Python 3.11 or 3.12 from python.org, including Tcl/Tk and the Python launcher, then run this again.
pause
exit /b 1
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Setup failed. Check the error above and your internet connection.
    pause
    exit /b 1
)
rem Use prebuilt webrtcvad-wheels instead of Resemblyzer's legacy source-only dependency.
".venv\Scripts\python.exe" -m pip install --no-deps resemblyzer==0.1.4
if errorlevel 1 (
    echo Speaker package installation failed. Check the error above.
    pause
    exit /b 1
)
echo Ready. Double-click Start.cmd to open Local Speech to Text.
pause
