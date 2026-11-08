@echo off
cd /d "%~dp0"
title Quant Research Console - close this window to stop
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python venv not found in this folder.
  echo Run these first:
  echo     python -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo Starting local research console...
echo URL: http://127.0.0.1:8765
echo Close this window to stop the server.
echo.
.venv\Scripts\python.exe -m app.server --open
echo.
echo Server stopped.
pause