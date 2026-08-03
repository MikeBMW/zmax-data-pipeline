#!/usr/bin/env python3
"""Orin 相机直读服务 · 15fps 发布到 ROS 话题
========================================
用 pyrealsense2 直读 D405 (15fps) 发布 /realsense/color/image_raw,
替代产线 realsense_source (1.5fps空转, 102% CPU)。
产线订阅者话题不变, 只是帧率提升10倍。

用法 (Orin):
  bash -c 'source /opt/ros/humble/setup.bash && python3 orin_cam15.py'
"""
import threading
import time

import cv2
import numpy as np
import pyrealsense2 as rs
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

FPS = 15
WIDTH, HEIGHT = 424, 240


def main():
    # 1. 打开相机
    ctx = rs.context()
    devs = list(ctx.query_devices())
    if not devs:
        print("❌ 无相机")
        return
    serial = devs[0].get_info(rs.camera_info.serial_number)
    print(f"📷 相机: {serial}")

    pipe = rs.pipeline()
    cfg = rs.config()
    cfg.enable_device(serial)
    cfg.enable_stream(rs.stream.color, WIDTH, HEIGHT, rs.format.bgr8, FPS)
    pipe.start(cfg)
    print(f"✅ 相机直读 {FPS}fps")

    # 2. 发布 ROS
    rclpy.init()
    node = Node("orin_cam15")
    pub = node.create_publisher(Image, "/realsense/color/image_raw", 10)
    pub_info = node.create_publisher(Image, "/realsense/color/camera_info", 10)

    def spin():
        rclpy.spin(node)
    threading.Thread(target=spin, daemon=True).start()

    # 3. 循环抓帧发布
    count = 0
    t0 = time.time()
    while rclpy.ok():
        try:
            frames = pipe.wait_for_frames(timeout_ms=2000)
            color = frames.get_color_frame()
            if not color:
                continue
            img = np.asanyarray(color.get_data())
            msg = Image()
            msg.height, msg.width = img.shape[:2]
            msg.encoding = "bgr8"
            msg.step = img.shape[1] * 3
            msg.data = img.tobytes()
            msg.header.stamp = node.get_clock().now().to_msg()
            msg.header.frame_id = "camera_link"
            pub.publish(msg)
            count += 1
            if count % FPS == 0:
                fps = FPS / (time.time() - t0)
                t0 = time.time()
                print(f"[{time.strftime('%H:%M:%S')}] 发布 {FPS}fps ({fps:.1f})", flush=True)
        except Exception as e:
            print(f"⚠️ {str(e)[:80]}", flush=True)
            time.sleep(0.5)

    pipe.stop()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
