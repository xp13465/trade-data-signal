@echo off
chcp 65001 >nul
REM sensenova-proxy-start.bat - 双击启动商汤轮换代理(Windows 便利入口)
REM 推荐主入口用 sensenova-proxy-ctl.py(python sensenova-proxy-ctl.py start)
set TTP_PORT=8899
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 python,请先装 Python 3.9+ 并加入 PATH:https://www.python.org/downloads/
    pause
    exit /b 1
)
echo 代理监听 http://127.0.0.1:%TTP_PORT%,按 Ctrl+C 停
echo 首次使用请先把 keys.txt.example 复制为 keys.txt 并填入商汤 key
python sensenova-rotate-proxy.py
pause
