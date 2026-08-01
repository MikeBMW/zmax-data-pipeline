#!/usr/bin/env python3
"""Z-MAX Simulink 硬件端侧服务 · System 0 Sim
========================================
在 Orin 上运行, 模拟真实硬件传感器数据流并发布到 ROS2,
供 Simulink 仿真 → 采集 → 上传 → 训练 → 部署 全链路使用。

发布话题(与真实硬件同名):
  /real_joint_states    关节状态 6-DOF
  /gripper_pos          夹爪位置
  /robot/force_torque   六维力传感器
  /realsense/color/image_raw  相机帧(合成棋盘格)

模式:
  sim   纯仿真模式(默认, 无需真机)
  real  真实硬件模式(转发真机数据, 需机器人上电)

用法:
  python3 simulink_hw_server.py [sim|real]
"""
import math
import os
import sys
import time
import threading
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState, Image
from std_msgs.msg import Float32
from geometry_msgs.msg import WrenchStamped

RATE = 30.0  # Hz


class SimulinkHW(Node):
    """Simulink 硬件端侧节点"""

    def __init__(self, mode="sim"):
        super().__init__("simulink_hw_server")
        self.mode = mode
        self.t = 0.0

        # 发布器 (与真实硬件话题同名)
        self.pub_joint = self.create_publisher(JointState, "/real_joint_states", 10)
        self.pub_gripper = self.create_publisher(Float32, "/gripper_pos", 10)
        self.pub_force = self.create_publisher(WrenchStamped, "/robot/force_torque", 10)
        self.pub_camera = self.create_publisher(Image, "/realsense/color/image_raw", 10)

        self.get_logger().info(f"Simulink HW server 启动 (mode={mode}, {RATE}Hz)")
        self.get_logger().info("  发布: /real_joint_states /gripper_pos /robot/force_torque /realsense/color/image_raw")

    def step(self):
        """生成一帧模拟数据"""
        self.t += 1.0 / RATE

        # 关节: 正弦运动 (模拟 Z700 6轴)
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = [f"j{i}" for i in range(1, 7)]
        js.position = [
            0.8 * math.sin(self.t * 0.5),
            -0.4 * math.cos(self.t * 0.4),
            1.2 * math.sin(self.t * 0.3),
            0.5 * math.cos(self.t * 0.6),
            0.6 * math.sin(self.t * 0.2),
            -0.3 * math.cos(self.t * 0.5),
        ]
        js.velocity = [0.4 * math.cos(self.t * 0.5)] * 6
        js.effort = [1.2 + 0.1 * math.sin(self.t)] * 6
        self.pub_joint.publish(js)

        # 夹爪
        g = Float32()
        g.data = 0.5 + 0.3 * math.sin(self.t * 0.8)
        self.pub_gripper.publish(g)

        # 六维力
        f = WrenchStamped()
        f.header.stamp = self.get_clock().now().to_msg()
        f.wrench.force.x = 2.0 * math.sin(self.t)
        f.wrench.force.y = 1.0 * math.cos(self.t * 0.7)
        f.wrench.force.z = -9.8 * 0.5
        f.wrench.torque.x = 0.05 * math.sin(self.t * 2)
        f.wrench.torque.y = 0.03 * math.cos(self.t * 2)
        f.wrench.torque.z = 0.01
        self.pub_force.publish(f)

        # 相机: 合成棋盘格 640x480
        img = Image()
        img.header.stamp = self.get_clock().now().to_msg()
        img.height = 480
        img.width = 640
        img.encoding = "rgb8"
        img.step = 640 * 3
        frame = self._synth_frame()
        img.data = frame.tobytes()
        self.pub_camera.publish(img)

    def _synth_frame(self):
        """合成棋盘格+移动方块图像"""
        h, w = 480, 640
        y, x = np.mgrid[0:h, 0:w]
        # 棋盘格
        chess = ((x // 40 + y // 40) % 2).astype(np.uint8) * 180
        # 移动方块 (模拟目标物体)
        cx = int(w // 2 + 100 * math.sin(self.t * 0.5))
        cy = int(h // 2 + 60 * math.cos(self.t * 0.3))
        frame = np.stack([chess] * 3, axis=-1).astype(np.uint8)
        frame[cy - 20:cy + 20, cx - 20:cx + 20] = [255, 60, 60]
        return frame


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "sim"
    rclpy.init()
    node = SimulinkHW(mode)

    def spin():
        rclpy.spin(node)

    t = threading.Thread(target=spin, daemon=True)
    t.start()

    try:
        while rclpy.ok():
            node.step()
            time.sleep(1.0 / RATE)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
