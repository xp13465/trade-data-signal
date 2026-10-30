@echo off
chcp 65001 >nul
REM sensenova-proxy-install-autostart.bat - 开机自启(往启动文件夹放快捷方式)
setlocal
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%~dp0sensenova-proxy-start.bat"
set "LNK=%STARTUP%\sensenova-proxy.lnk"
if not exist "%TARGET%" (
    echo 找不到 %TARGET%
    pause
    exit /b 1
)
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$sc = $ws.CreateShortcut('%LNK%'); " ^
  "$sc.TargetPath = '%TARGET%'; " ^
  "$sc.WorkingDirectory = '%~dp0'; " ^
  "$sc.WindowStyle = 7; " ^
  "$sc.Save(); " ^
  "Write-Host ('已创建快捷方式: ' + '%LNK%')"
if errorlevel 1 (
    echo 创建快捷方式失败。
    pause
    exit /b 1
)
echo 开机自启已安装到: %LNK%
echo 如需取消:删除该快捷方式即可。
pause
