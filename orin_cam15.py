#!/usr/bin/env python3
"""Orin 相机直读服务 · 控制台心跳门控版
========================================
用 pyrealsense2 直读 D405 发布 /realsense/color/image_raw (15fps)。

心跳门控 (控制台决定):
  - 控制台(cicd.html)在访问快照 → /api/relay/cam/status age_s 很小 → 相机开
  - 控制台关闭/无人看 → age_s 变大(>15s) → 相机自动关 (省CPU)
  - 相机开关自动循环, 不用人工

心跳来源: ECS /api/relay/cam/status 的 age_s 字段 (快照实时度)
用法 (Orin):
  bash -c 'source /opt/ros/humble/setup.bash && python3 orin_cam15.py'
"""
import threading
import time
import urllib.request
import json

import cv2
import numpy as np
import pyrealsense2 as rs
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

FPS = 15
WIDTH, HEIGHT = 424, 240

# 心跳检测 (ECS 快照实时度)
CAM_STATUS_URL = "http://datadrive.world/api/relay/cam/status"
HEARTBEAT_OK_SEC = 10.0    # age_s < 10s = 控制台在看, 相机开
CHECK_INTERVAL = 5.0       # 每5秒检查一次心跳

_cam_lock = threading.Lock()
_cam_active = False         # 相机当前是否开启
_pipe = None
_pub = None
_node = None


def check_heartbeat() -> bool:
    """控制台心跳: cam/status age_s 小 = 控制台在看"""
    try:
        with urllib.request.urlopen(CAM_STATUS_URL, timeout=5) as r:
            d = json.loads(r.read())
        age = d.get("age_s", 999)
        return age < HEARTBEAT_OK_SEC
    except Exception:
        return False


def camera_start():
    """开启相机"""
    global _cam_active, _pipe
    with _cam_lock:
        if _cam_active:
            return True
        try:
            ctx = rs.context()
            devs = list(ctx.query_devices())
            if not devs:
                print("❌ 无相机", flush=True)
                return False
            serial = devs[0].get_info(rs.camera_info.serial_number)
            _pipe = rs.pipeline()
            cfg = rs.config()
            cfg.enable_device(serial)
            cfg.enable_stream(rs.stream.color, WIDTH, HEIGHT, rs.format.bgr8, FPS)
            _pipe.start(cfg)
            _cam_active = True
            print(f"📷 相机已开 ({serial}) {FPS}fps — 控制台在看", flush=True)
            return True
        except Exception as e:
            print(f"❌ 相机开启失败: {str(e)[:80]}", flush=True)
            return False


def camera_stop():
    """关闭相机 (省CPU)"""
    global _cam_active, _pipe
    with _cam_lock:
        if not _cam_active:
            return
        try:
            _pipe.stop()
        except Exception:
            pass
        _pipe = None
        _cam_active = False
        print("💤 相机已关 — 控制台无心跳(无人看), 省CPU", flush=True)


def main():
    global _pub, _node
    # 启动 ROS 节点 (相机发布用, 相机未开时节点在但不占资源)
    rclpy.init()
    _node = Node("orin_cam15")
    _pub = _node.create_publisher(Image, "/realsense/color/image_raw", 10)
    _pub_info = _node.create_publisher(Image, "/realsense/color/camera_info", 10)
    threading.Thread(target=lambda: rclpy.spin(_node), daemon=True).start()

    print(f"🖥️ 相机心跳门控启动: 控制台心跳<{HEARTBEAT_OK_SEC}s才开相机, 每{CHECK_INTERVAL}s检查")
    count = 0
    t0 = time.time()
    last_hb = None

    while rclpy.ok():
        hb = check_heartbeat()

        if hb and not _cam_active:
            camera_start()          # 控制台在看 → 开相机
        elif not hb and _cam_active:
            camera_stop()           # 控制台关了 → 关相机

        if _cam_active:
            # 抓帧发布
            try:
                frames = _pipe.wait_for_frames(timeout_ms=1000)
                color = frames.get_color_frame()
                if color:
                    img = np.asanyarray(color.get_data())
                    msg = Image()
                    msg.height, msg.width = img.shape[:2]
                    msg.encoding = "bgr8"
                    msg.step = img.shape[1] * 3
                    msg.data = img.tobytes()
                    msg.header.stamp = _node.get_clock().now().to_msg()
                    msg.header.frame_id = "camera_link"
                    _pub.publish(msg)
                    count += 1
                    if count % FPS == 0:
                        fps = FPS / (time.time() - t0)
                        t0 = time.time()
                        print(f"[{time.strftime('%H:%M:%S')}] 发布 {FPS}fps ({fps:.1f}) hb={hb}", flush=True)
            except Exception as e:
                print(f"⚠️ {str(e)[:60]}", flush=True)
                time.sleep(0.5)
        else:
            time.sleep(CHECK_INTERVAL)   # 相机关着, 慢查心跳

    _node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
