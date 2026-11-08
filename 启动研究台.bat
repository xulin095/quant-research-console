@echo off
chcp 65001 >nul
cd /d D:\quant-agent
echo 正在启动量化研究控制台...
echo 浏览器打开： http://127.0.0.1:8765
echo 关闭本窗口即停止。
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe -m app.server
pause