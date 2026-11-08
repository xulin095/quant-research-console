@echo off
cd /d D:\quant-agent
title Quant Research Console - close this window to stop
echo Starting local research console...
echo URL: http://127.0.0.1:8765
echo Close this window to stop the server.
echo.
.venv\Scripts\python.exe -m app.server --open
echo.
echo Server stopped.
pause