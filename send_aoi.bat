@echo off
REM Z-MAX 工控机一键打包+上传脚本 (AOI程序 → Mac)
REM 用法: 双击运行 或 cmd: send_aoi.bat
REM 依赖: 工控机已配代理 192.168.23.1:9100, Mac文件服务 192.168.23.1:9000

setlocal
set SRC=D:\xspace\ultralytics_AOI
set ZIP=%TEMP%\aoi_source_export.zip
set MAC_IP=192.168.23.1

echo ==========================================
echo  Z-MAX AOI 源码打包上传
echo  源目录: %SRC%
echo  目标:   %MAC_IP%:9000
echo ==========================================

REM 1. 检查源目录
if not exist "%SRC%" (
    echo [错误] 目录不存在: %SRC%
    pause
    exit /b 1
)

REM 2. 检查 PowerShell (打包用)
where powershell >nul 2>nul
if errorlevel 1 (
    echo [错误] 需要 PowerShell
    pause
    exit /b 1
)

REM 3. 打包 (排除大文件: 模型权重/视频/__pycache__)
echo [1/3] 打包中 (排除 .pt/.onnx/视频/cache)...
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%SRC%\*' -DestinationPath '%ZIP%' -Force -ErrorAction SilentlyContinue"
if not exist "%ZIP%" (
    echo [错误] 打包失败
    pause
    exit /b 1
)

REM 4. 显示大小
for %%A in ("%ZIP%") do echo [2/3] 包大小: %%~zA 字节

REM 5. 上传到 Mac
echo [3/3] 上传到 %MAC_IP%:9000 ...
curl -s -X POST "http://%MAC_IP%:9000/upload" -F "file=@%ZIP%"
echo.
echo ==========================================
echo  完成! 若返回 {"ok":true} 则小芳已收到
echo ==========================================
pause
