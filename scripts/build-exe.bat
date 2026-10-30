@echo off
chcp 65001 >nul
REM build-exe.bat - 在 Windows 上把 sensenova-rotate-proxy.py 打成 exe
REM 注意:mac/linux 不能交叉编译 PyInstaller,必须在 Windows 机器跑本脚本。
cd /d %~dp0
echo 需先装 Python 3.9+ 与 pyinstaller(pip install pyinstaller)
where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 python,请先装 Python 3.9+ 并加入 PATH。
    pause
    exit /b 1
)
pip install pyinstaller
pyinstaller --clean sensenova-proxy.spec
echo.
echo 产物在 dist\sensenova-proxy.exe
echo 使用:把 exe 与 keys.txt 放同目录,双击 exe 即用(首次从 keys.txt.example 复制 keys.txt 填 key)
pause
