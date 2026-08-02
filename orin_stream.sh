#!/bin/bash
# Orin 现场直播流 · 每秒抓帧推送到 ECS /orin_realtime.jpg
# 页面: https://datadrive.world/cicd.html (每2秒刷新图片)
# 用法: bash orin_stream.sh   (需source ROS环境)

ECS_HOST="root@39.102.211.79"          # ECS 服务器
ECS_PATH="/www/wwwroot/datadrive.world/orin_realtime.jpg"
INTERVAL=1                              # 秒/帧
QUALITY=50                              # JPEG质量(压缩)

echo "=== Orin 直播流启动 ==="
echo "目标: ${ECS_HOST}:${ECS_PATH}"

while true; do
    TS=$(date +%s)
    # 1. 抓一帧 ROS2 相机图像存临时文件
    timeout 5 ros2 topic echo /realsense/color/image_raw --once > /tmp/frame.txt 2>/dev/null

    # 2. 用 python 从 echo 输出提取图像存 JPEG
    python3 - "$TS" << 'PYEOF'
import sys, re, struct
import numpy as np
import cv2

raw = open('/tmp/frame.txt', 'rb').read().decode('utf-8', errors='ignore')

# 从 ros2 topic echo 输出中提取 data: [bytes...]
# 格式: data: [13, 47, ...]  (uint8 数组)
m = re.search(r'data:\s*\[(.*?)\]', raw, re.DOTALL)
if not m:
    sys.exit(0)
nums = [int(x) for x in m.group(1).split(',') if x.strip().isdigit()]
if len(nums) < 640*480*3:
    sys.exit(0)

img = np.array(nums[:640*480*3], dtype=np.uint8).reshape(480, 640, 3)
ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 50])
if ok:
    with open('/tmp/orin_frame.jpg', 'wb') as f:
        f.write(buf.tobytes())
    print(f'帧 {len(buf)/1024:.0f}KB')
PYEOF

    # 3. SCP 推送到 ECS
    if [ -f /tmp/orin_frame.jpg ]; then
        scp -q -o StrictHostKeyChecking=no /tmp/orin_frame.jpg "${ECS_HOST}:${ECS_PATH}" 2>/dev/null
        echo "[$(date '+%H:%M:%S')] 📤 已推送"
    fi

    sleep $INTERVAL
done
