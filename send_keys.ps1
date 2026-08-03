# Z-MAX AOI 关键文件批量上传 (工控机 PowerShell 运行)
# 保存为 send_keys.ps1, 在 D:\xspace\ultralytics_AOI 下执行: .\send_keys.ps1
$files = @(
    "cam_finger_10082_work.py",      # 金手指10082工作版
    "cam_finger_10082_test.py",      # 金手指测试版
    "cam_surface_10083_work.py",     # 表面10083工作版
    "SciCam_class.py",               # 相机SDK
    "SciCamInfo_header.py",
    "SciCamPayload_header.py",
    "SciCamErrorDefine_const.py",
    "readme_AOI.md",                 # 说明文档
    "detect_plain_pt_split.py"
)
$mac = "http://192.168.23.1:9000/upload"
foreach ($f in $files) {
    if (Test-Path $f) {
        Write-Host "上传 $f ..." -NoNewline
        $r = curl -s -X POST $mac -F "file=@$f"
        Write-Host " $r"
    } else {
        Write-Host "跳过 $f (不存在)"
    }
}
# yolo_detector 目录 (加密检测器)
if (Test-Path "yolo_detector") {
    Write-Host "打包 yolo_detector/ ..." -NoNewline
    Compress-Archive -Path "yolo_detector\*" -DestinationPath "$env:TEMP\yolo_detector.zip" -Force
    $r = curl -s -X POST $mac -F "file=@$env:TEMP\yolo_detector.zip"
    Write-Host " $r"
}
Write-Host "=== 完成 ==="
