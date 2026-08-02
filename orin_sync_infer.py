#!/usr/bin/env python3
"""Orin 同步推理 · 真实位姿 vs 模型输出对比
========================================
读 /robot/tcp_pose (真实末端位姿) + /robot/joint_states (真实关节)
→ 喂给 ACT 模型 → 输出动作 → 对比

用法 (Orin, 需source ROS):
  python3 orin_sync_infer.py --frames 20
"""
import argparse
import json
import sys
import time

import numpy as np
import rclpy
import torch
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import JointState

sys.path.insert(0, "/home/tashan/.zmax")
from orin_act_standalone import build_act_from_ckpt

MODEL = "/home/tashan/.zmax/models/act_model.safetensors"


class RealRobot(Node):
    def __init__(self):
        super().__init__("sync_infer")
        self.tcp = None
        self.joints = None
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.on_tcp, 10)
        self.create_subscription(JointState, "/robot/joint_states", self.on_joints, 10)

    def on_tcp(self, msg):
        p = msg.pose.position
        self.tcp = [p.x, p.y, p.z]

    def on_joints(self, msg):
        self.joints = list(msg.position[:6])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=20)
    args = ap.parse_args()

    # 加载模型
    print(f"🤖 加载模型: {MODEL}")
    act = build_act_from_ckpt(MODEL)
    act.eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    act.to(dev)
    print(f"✅ 模型就绪 ({dev})")

    # 读真实数据
    rclpy.init()
    node = RealRobot()
    import threading
    threading.Thread(target=lambda: rclpy.spin(node), daemon=True).start()

    print("⏳ 等待真实数据...")
    while node.tcp is None or node.joints is None:
        time.sleep(0.5)
    print(f"📡 真实位姿: tcp={[round(x,3) for x in node.tcp]}")
    print(f"📡 真实关节: {[round(x,2) for x in node.joints]}")

    # 推理 N 次
    print(f"\n═══ 同步推理 {args.frames} 帧 ═══")
    for i in range(args.frames):
        # state = 关节 (6D) 或 tcp (3D)? 模型 state 维度自动推断
        state_dim = act.encoder_robot_state_input_proj.weight.shape[1]
        if state_dim == 3:
            state = node.tcp  # 笛卡尔位姿
        elif state_dim == 6:
            state = node.joints
        else:
            state = node.joints[:state_dim]

        st = torch.tensor([state], dtype=torch.float32, device=dev)
        img = torch.randn(1, 3, 480, 640, device=dev)
        with torch.no_grad():
            t0 = time.time()
            action = act(img, st)
            dt = (time.time() - t0) * 1000
        a = action[0, 0].cpu().numpy()  # 第一个动作步

        # 对比
        print(f"[{i+1:2d}] state={[round(x,3) for x in state[:4]]}... "
              f"→ action={[round(x,3) for x in a[:4]]}... ({dt:.0f}ms)")
        time.sleep(0.5)

    node.destroy_node()
    rclpy.shutdown()
    print("\n✅ 完成 (只读推理, 未发任何topic)")


if __name__ == "__main__":
    main()
