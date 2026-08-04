@echo off
REM ============================================================
REM  Z-MAX 工控机网络配置一键脚本 (管理员运行)
REM  效果: 系统代理 = Mac:9100 (上网用) + 内网192.168.23.x绕过(直连)
REM  运行: 右键 → 以管理员身份运行
REM ============================================================
echo.
echo [1/3] 设置系统代理 Mac:9100 + 内网绕过...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "192.168.23.1:9100" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "192.168.23.*;localhost;127.0.0.1;<local>" /f >nul
echo      ✅ 代理已设: 192.168.23.1:9100
echo      ✅ 内网绕过: 192.168.23.*;localhost;127.0.0.1

echo [2/3] 刷新系统代理生效...
powershell -Command "Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyEnable -Value 1; Start-Sleep -Milliseconds 500" >nul 2>&1
echo      ✅ 已生效

echo [3/3] 验证...
echo      - 内网(Orin网页):  应直连  http://192.168.23.66:8000
echo      - 外网(百度):      应走代理  http://www.baidu.com
echo.
echo 完成! 现在测试:
echo   curl http://192.168.23.66:8000    (Orin HMI, 应能打开)
echo   curl https://www.baidu.com        (外网, 应能打开)
echo.
pause
