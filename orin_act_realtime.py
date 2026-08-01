#!/usr/bin/env python3
"""Orin 真实传感器 → ACT 推理
读 RealSense 相机帧 + 关节状态 → ACT 推理 → 报告
只读不写, 不发任何 topic
"""
import json, os, sys, time
sys.path.insert(0, os.path.expanduser("~/.zmax"))

import numpy as np
import torch
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from sensor_msgs.msg import JointState
from cv_bridge import CvBridge

from orin_act_standalone import build_act_from_ckpt

DEV = "cuda" if torch.cuda.is_available() else "cpu"


class SensorNode(Node):
    def __init__(self):
        super().__init__("act_sensor_reader")
        self.bridge = CvBridge()
        self.image = None
        self.image_ts = 0
        self.joints = None
        self.joints_ts = 0
        self.sub_img = self.create_subscription(
            Image, "/realsense/color/image_raw", self.on_image, 10)
        self.sub_joint = self.create_subscription(
            JointState, "/real_joint_states", self.on_joint, 10)

    def on_image(self, msg):
        self.image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="rgb8")
        self.image_ts = time.time()

    def on_joint(self, msg):
        self.joints = np.array(msg.position[:6], dtype=np.float32)
        self.joints_ts = time.time()

    def has_data(self):
        return self.image is not None and self.joints is not None


def main():
    print("=== Orin 真实传感器 → ACT 推理 ===")
    print(f"device: {DEV}")

    # 1. 加载 ACT
    t0 = time.time()
    act = build_act_from_ckpt()
    act.to(DEV).eval()
    print(f"✅ ACT 加载: {time.time()-t0:.1f}s")

    # 2. 连接 ROS2 读传感器
    rclpy.init()
    node = SensorNode()
    print("⏳ 等待传感器数据 (相机+关节)...")
    deadline = time.time() + 30
    while not node.has_data() and time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.5)
    if not node.has_data():
        print("❌ 30秒内未收到传感器数据")
        return

    img = node.image
    joints = node.joints
    print(f"✅ 传感器数据: 图像 {img.shape}, 关节 {joints.tolist()}")

    # 3. 预处理（与训练一致）
    from PIL import Image as PILImage
    img_pil = PILImage.fromarray(img)
    img_resized = img_pil.resize((480, 640))
    img_arr = np.array(img_resized, dtype=np.float32) / 255.0
    img_tensor = torch.from_numpy(img_arr).permute(2, 0, 1).unsqueeze(0).to(DEV)  # (1,3,480,640)

    # 关节 6→14 (ALOHA 双臂格式, 补0)
    state_14 = np.zeros(14, dtype=np.float32)
    state_14[:6] = joints
    state_tensor = torch.from_numpy(state_14).unsqueeze(0).to(DEV)

    # 4. 推理
    with torch.no_grad():
        actions = act(img_tensor, state_tensor)

    # 5. 报告
    acts = actions[0].cpu().numpy()  # (100, 14)
    print("\n══════════ ACT 推理报告 ══════════")
    print(f"输入图像: {tuple(img.shape)} → resize (480,640)")
    print(f"输入关节: {[round(j,4) for j in joints.tolist()]}")
    print(f"输出动作块: {tuple(actions.shape)} (100步 × 14维)")
    print(f"推理耗时: 平均每步 {(time.time()-t0)*1000:.0f}ms 含加载")

    # 动作统计
    for i in range(5):
        j = i * 20
        print(f"  step {j:3d}: " + " ".join(f"{a:+.3f}" for a in acts[j, :6]))

    # 动作范围
    print(f"动作范围 J1-J6: min={acts[:, :6].min():.3f}, max={acts[:, :6].max():.3f}")
    print("\n✅ 推理完成 — 仅读取传感器, 未发送任何动作")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
