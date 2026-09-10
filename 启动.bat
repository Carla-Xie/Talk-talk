@echo off
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python not found. Install Python 3 and check "Add python.exe to PATH".
  echo https://www.python.org/downloads/
  pause
  exit /b 1
)

echo Installing packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  pause
  exit /b 1
)

echo Starting. Keep this window open. Use Chrome or Edge.
python server.py
pause
