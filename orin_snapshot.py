#!/usr/bin/env python3
"""Orin 现场快照服务 · 每10秒拍一帧上传ECS供cicd.html直播
====================================================
从 ROS2 /realsense/color/image_raw 读帧 → JPEG压缩 → 上传ECS
cicd.html 轮询显示最新照片 (10秒刷新 = 现场直播)

用法 (Orin, 需source ROS):
  python3 orin_snapshot.py
"""
import base64
import io
import json
import time
import urllib.request

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

SNAP_URL = "http://datadrive.world/api/relay/upload"   # 上传通道
INTERVAL = 10   # 秒/张
JPEG_QUALITY = 60  # 压缩质量 (0-100, 越小越省流量)


class SnapshotNode(Node):
    def __init__(self):
        super().__init__("snapshot_service")
        self.latest = None
        self.latest_ts = 0
        self.sub = self.create_subscription(Image, "/realsense/color/image_raw", self.on_img, 10)

    def on_img(self, msg):
        self.latest = msg
        self.latest_ts = time.time()

    def grab_jpeg(self):
        """取最新帧 → JPEG bytes"""
        if self.latest is None:
            return None
        m = self.latest
        try:
            if m.encoding in ("bgr8", "rgb8"):
                img = np.frombuffer(m.data, dtype=np.uint8).reshape(m.height, m.width, 3)
                if m.encoding == "rgb8":
                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                # 压缩
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    return buf.tobytes()
        except Exception as e:
            print(f"⚠️ 图像处理失败: {e}")
        return None


def upload_snapshot(jpeg_bytes, ts):
    """上传快照到 ECS (JSON包格式)"""
    pkg = {
        "meta": {"source": "orin_snapshot", "time": ts, "type": "camera_snapshot"},
        "snapshot_b64": base64.b64encode(jpeg_bytes).decode(),
        "timestamp": ts,
    }
    data = json.dumps(pkg).encode()
    req = urllib.request.Request(SNAP_URL, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode()[:100]
    except Exception as e:
        return f"ERR: {e}"


def main():
    print("=== Orin 现场快照服务 ===")
    print(f"间隔: {INTERVAL}s · JPEG质量: {JPEG_QUALITY}")

    rclpy.init()
    node = SnapshotNode()

    import threading
    def spin():
        rclpy.spin(node)
    threading.Thread(target=spin, daemon=True).start()

    print("⏳ 等待相机帧...")
    while node.latest is None:
        time.sleep(1)
    print("✅ 相机已连接, 开始快照")

    while rclpy.ok():
        ts = time.time()
        jpeg = node.grab_jpeg()
        if jpeg:
            result = upload_snapshot(jpeg, ts)
            print(f"[{time.strftime('%H:%M:%S')}] 📸 {len(jpeg)/1024:.0f}KB → {result}", flush=True)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 无帧", flush=True)
        time.sleep(INTERVAL)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
