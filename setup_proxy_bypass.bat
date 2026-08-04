@echo off
chcp 65001 >nul
REM ============================================================
REM  Z-MAX proxy setup (run as administrator)
REM  Proxy: 192.168.23.1:9100  Bypass: 192.168.23.*;localhost
REM ============================================================
echo.
echo [1/3] Setting system proxy...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "192.168.23.1:9100" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "192.168.23.*;localhost;127.0.0.1;<local>" /f >nul
echo      [OK] Proxy=192.168.23.1:9100
echo      [OK] Bypass=192.168.23.*;localhost;127.0.0.1

echo [2/3] Refreshing...
powershell -Command "& { Start-Sleep -Milliseconds 500 }" >nul 2>&1
echo      [OK]

echo [3/3] Verify:
echo      - LAN:  curl http://192.168.23.66:8000
echo      - WAN:  curl https://www.baidu.com
echo.
echo DONE!
pause
