#!/usr/bin/env python3
"""Z-MAX 动作级指标采集上报 (P3 端侧落地)
========================================
订阅 状态机(8阶段) + 力觉 + 关节 → 每阶段量测指标
→ POST /api/action-log (大屏监督留痕)

8 状态机: 接近APPROACH/对位ALIGN/下降DESCEND/抓取GRASP/抬起LIFT/转移TRANSFER/插入INSERT/完成DONE
监督指标: d_hp(收敛距离) e_xy(对位误差) e_z(到位) contact(接触) grip_f(夹持力)
          dz(抬升) t_xfer(转移时间) d_ins(插入深度) f_ins(插入力)
"""
import json
import time
import urllib.request
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from geometry_msgs.msg import WrenchStamped
from sensor_msgs.msg import JointState

API_URL = "https://datadrive.world/api/action-log"
RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                          history=HistoryPolicy.KEEP_LAST)

# 状态机阶段映射 (中文名 → 阶段)
STAGE_MAP = {
    "接近": "APPROACH", "对位": "ALIGN", "下降": "DESCEND",
    "抓取": "GRASP", "抬起": "LIFT", "转移": "TRANSFER",
    "插入": "INSERT", "完成": "DONE",
}

class ActionMetricsNode(Node):
    def __init__(self):
        super().__init__("orin_action_metrics")
        self.stage = "IDLE"
        self.stage_ts = time.time()
        self.force = [0.0, 0.0, 0.0]
        self.joints = None
        self.metrics = {}
        self.log = []

        # 订阅: 状态机 / 力觉 / 关节
        self.sub_states = self.create_subscription(
            String, "/motion/active_states", self.on_states, RELIABLE_QOS)
        self.sub_trans = self.create_subscription(
            String, "/motion/active_transition", self.on_trans, RELIABLE_QOS)
        self.sub_force = self.create_subscription(
            WrenchStamped, "/robot/force_torque", self.on_force, RELIABLE_QOS)
        self.sub_joints = self.create_subscription(
            JointState, "/robot/joint_states", self.on_joints, RELIABLE_QOS)

        # 每 2s 上报一次当前阶段指标
        self.timer = self.create_timer(2.0, self.report)
        self.get_logger().info("✅ 动作指标采集启动 (8状态机监督)")

    def on_states(self, msg):
        try:
            d = json.loads(msg.data)
            states = d.get("states", [])
            if states:
                name = states[-1].split("/")[-1]
                self.stage = STAGE_MAP.get(name, name)
                self.stage_ts = time.time()
        except Exception:
            pass

    def on_trans(self, msg):
        try:
            d = json.loads(msg.data)
            to = d.get("to", "")
            name = to.split("/")[-1]
            self.stage = STAGE_MAP.get(name, name)
            self.stage_ts = time.time()
        except Exception:
            pass

    def on_force(self, msg):
        self.force = [msg.wrench.force.x, msg.wrench.force.y, msg.wrench.force.z]

    def on_joints(self, msg):
        self.joints = list(msg.position)

    def measure(self):
        """阶段量测 → 指标 dict"""
        m = {"stage": self.stage, "ts": time.time(),
             "stage_dur": round(time.time() - self.stage_ts, 3),
             "force_z": round(abs(self.force[2]), 3)}
        # 按阶段附加指标 (仿真/真机可扩展)
        if self.stage == "GRASP":
            m["contact"] = 1.0 if abs(self.force[2]) > 0.5 else 0.0
            m["grip_f"] = round(abs(self.force[2]), 3)
        if self.stage == "INSERT":
            m["f_ins"] = round(abs(self.force[2]), 3)
            m["d_ins"] = round(self.joints[5] if self.joints else 0.0, 4)
        return m

    def report(self):
        m = self.measure()
        self.metrics = m
        self.log.append(m)
        # 上报 (失败静默, 不阻塞)
        try:
            req = urllib.request.Request(
                API_URL, data=json.dumps(m).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    self.get_logger().info(f"📤 [{m['stage']}] force_z={m['force_z']}N")
        except Exception:
            pass

def main():
    rclpy.init()
    node = ActionMetricsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
