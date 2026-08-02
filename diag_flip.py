#!/usr/bin/env python3
"""翻转诊断: 抓原始帧 + flip后 对比"""
import cv2, numpy as np, rclpy, time
from rclpy.node import Node
from sensor_msgs.msg import Image

rclpy.init()
node = Node('flip_diag')
got = []
def cb(msg):
    if len(got) < 1: got.append(msg)
node.create_subscription(Image, '/realsense/color/image_raw', cb, 10)
deadline = time.time() + 6
while time.time() < deadline and not got:
    rclpy.spin_once(node, timeout_sec=0.3)
if got:
    m = got[0]
    img = np.frombuffer(m.data, dtype=np.uint8).reshape(m.height, m.width, 3)
    if m.encoding == 'rgb8':
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    cv2.imwrite('/tmp/raw_frame.jpg', img)
    flipped = cv2.flip(img, -1)
    cv2.imwrite('/tmp/flipped_frame.jpg', flipped)
    print(f'encoding={m.encoding} raw={img.shape} 已保存两张')
else:
    print('无帧')
node.destroy_node()
rclpy.shutdown()
