#!/usr/bin/env python3
"""Z-MAX 全局数据空间 DDS 聚合器 · 水流式刷写
========================================
在 Orin 运行: 订阅 ROS2 topics + 采集各服务状态 → 组装 DDS 快照
→ POST 到 ECS 全局数据空间 (/api/dds), 像水流一样持续刷写。

数据模型:
  nodes:   各服务节点状态 (gateway/infer/camera/snapshot/motion/vision/aoi/relay)
  topics:  关键 ROS2 话题最新值 (关节/相机/力/状态机/位姿/扫码/急停)
  skills:  原子技能 (取料/扫码/插入/AOI检测...) + 当前条件
  flow:    状态机流转历史 (水流轨迹)

用法:
  python3 dds_writer.py                 # 正常刷写 (1s周期)
  python3 dds_writer.py --once          # 单次快照测试
"""
import argparse
import json
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import JointState, Image
from std_msgs.msg import Float32, String, Bool
from geometry_msgs.msg import PoseStamped, WrenchStamped
import urllib.request

DDS_URL = "http://datadrive.world/api/dds/write"
LOCAL_URL = "http://localhost:8765"
LOCAL_DDS_FILE = "/tmp/dds_snapshot.json"   # 本地原型存储 (无ECS端点时)

# 产线话题 QoS: BEST_EFFORT (robot_driver 发布实测 BEST_EFFORT+VOLATILE)
RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                          history=HistoryPolicy.KEEP_LAST)

# 原子技能定义 (对应 motion 状态机 27 态, 按阶段分组)
ATOMIC_SKILLS = {
    "识别阶段": ["料盘识别", "工件识别", "call_tray_reference_vision"],
    "取放阶段": ["取料", "扫码", "抓取失败判定", "抓取失败开爪", "连续抓取失败报错"],
    "插入阶段": ["尝试插入第一次", "尝试插入第二次", "插入失败报错", "插入完成"],
    "检测阶段": ["AOI_1", "AOI_2", "AOI_3", "AOI_4", "AOI_5", "AOI_6", "AOI_PD", "AOING"],
    "完成阶段": ["暂时松开", "移动到治具插槽", "等待测试结果", "拔出", "OK", "NG", "循环守卫", "初始化循环"],
}


class DDSNode(Node):
    def __init__(self):
        super().__init__("dds_writer")
        # 状态缓存
        self.data = {
            "nodes": {}, "topics": {}, "skills": {}, "flow": [],
            "meta": {"writer": "orin_dds", "ts": 0, "cycle": 0},
        }
        # 订阅
        self.create_subscription(JointState, "/real_joint_states", self.on_joints, RELIABLE_QOS)
        self.create_subscription(JointState, "/robot/joint_states", self.on_robot_joints, RELIABLE_QOS)
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.on_tcp, RELIABLE_QOS)
        self.create_subscription(WrenchStamped, "/robot/force_torque", self.on_force, RELIABLE_QOS)
        self.create_subscription(Float32, "/gripper_pos", self.on_gripper, RELIABLE_QOS)
        self.create_subscription(String, "/motion/active_states", self.on_states, RELIABLE_QOS)
        self.create_subscription(String, "/motion/active_transition", self.on_transition, RELIABLE_QOS)
        self.create_subscription(String, "/motion/execution_result", self.on_exec_result, RELIABLE_QOS)
        self.create_subscription(Bool, "/motion/initialization_complete", self.on_init, RELIABLE_QOS)
        self.create_subscription(String, "/barcode_scanner/status", self.on_scanner, RELIABLE_QOS)
        self.create_subscription(Bool, "/physical_estop", self.on_estop, RELIABLE_QOS)
        self.create_subscription(Bool, "/execution_mode_real", self.on_mode, RELIABLE_QOS)
        self.cycle = 0
        self._last_states = []

    # ---- 回调 ----
    def on_joints(self, msg):
        self.data["topics"]["real_joint_states"] = {
            "name": list(msg.name), "position": list(msg.position),
            "ts": time.time(), "hz": self._hz("/real_joint_states")}

    def on_robot_joints(self, msg):
        self.data["topics"]["robot_joint_states"] = {"position": list(msg.position)[:6], "ts": time.time()}

    def on_tcp(self, msg):
        p = msg.pose.position
        self.data["topics"]["tcp_pose"] = {
            "position": [round(p.x, 4), round(p.y, 4), round(p.z, 4)],
            "ts": time.time()}

    def on_force(self, msg):
        self.data["topics"]["force_torque"] = {
            "force": [msg.wrench.force.x, msg.wrench.force.y, msg.wrench.force.z],
            "torque": [msg.wrench.torque.x, msg.wrench.torque.y, msg.wrench.torque.z],
            "ts": time.time()}

    def on_gripper(self, msg):
        self.data["topics"]["gripper_pos"] = {"pos": msg.data, "ts": time.time()}

    def on_states(self, msg):
        try:
            d = json.loads(msg.data)
            states = d.get("states", [])
            names = [s.split("::")[-1] for s in states]
            self.data["topics"]["active_states"] = {"states": names, "ts": time.time()}
            if names and names != self._last_states:
                self._last_states = names
                # 水流: 记录状态流转
                self.data["flow"].append({"time": time.time(), "states": names, "current": names[-1]})
                self.data["flow"] = self.data["flow"][-50:]  # 保留最近50条
                # 更新技能状态
                cur = names[-1]
                for stage, skills in ATOMIC_SKILLS.items():
                    if cur in skills:
                        self.data["skills"][cur] = {"stage": stage, "active": True, "ts": time.time()}
        except Exception:
            pass

    def on_transition(self, msg):
        try:
            d = json.loads(msg.data)
            self.data["topics"]["active_transition"] = {
                "from": d.get("from", ""), "to": d.get("to", ""), "ts": time.time()}
        except Exception:
            pass

    def on_exec_result(self, msg):
        try:
            d = json.loads(msg.data)
            self.data["topics"]["execution_result"] = {"success": d.get("success"), "ts": time.time()}
        except Exception:
            pass

    def on_init(self, msg):
        self.data["topics"]["initialization_complete"] = {"value": bool(msg.data), "ts": time.time()}

    def on_scanner(self, msg):
        self.data["topics"]["barcode_scanner"] = {"status": msg.data, "ts": time.time()}

    def on_estop(self, msg):
        self.data["topics"]["physical_estop"] = {"active": bool(msg.data), "ts": time.time()}

    def on_mode(self, msg):
        self.data["topics"]["execution_mode"] = {"real": bool(msg.data), "ts": time.time()}

    # ---- 节点状态 ----
    def collect_nodes(self):
        import subprocess
        nodes = {}
        # 本机服务进程
        procs = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5).stdout
        for name, key in [("orin_gateway.py", "gateway"), ("orin_infer_service.py", "infer"),
                          ("orin_cam15.py", "camera"), ("orin_snapshot.py", "snapshot"),
                          ("simulink_hw_server.py", "simulink"), ("dds_writer.py", "dds")]:
            nodes[key] = {"running": f"python3 {name}" in procs, "ts": time.time()}
        # 网关健康
        try:
            with urllib.request.urlopen(f"{LOCAL_URL}/health", timeout=3) as r:
                nodes["gateway"]["health"] = json.loads(r.read()).get("online")
        except Exception:
            nodes["gateway"]["health"] = False
        # 推理服务
        try:
            with urllib.request.urlopen(f"{LOCAL_URL}/status", timeout=3) as r:
                s = json.loads(r.read())
                nodes["infer"]["model_size"] = s.get("model_size")
                nodes["infer"]["infer_count"] = s.get("infer_count")
        except Exception:
            pass
        return nodes

    def _hz(self, topic):
        """粗略频率(基于时间差, 简化)"""
        return None

    def snapshot(self):
        self.data["nodes"] = self.collect_nodes()
        self.data["meta"]["ts"] = time.time()
        self.data["meta"]["cycle"] = self.cycle
        # 技能汇总: 未激活的技能标 false
        all_skills = {}
        for stage, skills in ATOMIC_SKILLS.items():
            for s in skills:
                all_skills[s] = self.data["skills"].get(s, {"stage": stage, "active": False})
        self.data["skills"] = all_skills
        return self.data


def push_snapshot(data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(DDS_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="单次快照")
    ap.add_argument("--interval", type=float, default=5.0, help="刷写周期(秒)")
    args = ap.parse_args()

    rclpy.init()
    node = DDSNode()
    threading.Thread(target=lambda: rclpy.spin(node), daemon=True).start()
    time.sleep(2)  # 等话题数据

    if args.once:
        snap = node.snapshot()
        print(json.dumps(snap, ensure_ascii=False, indent=1)[:800])
        r = push_snapshot(snap)
        print(f"📤 DDS写: {r}")
        return

    print(f"💧 DDS 水流刷写启动 (周期{args.interval}s)")
    while True:
        node.cycle += 1
        snap = node.snapshot()
        r = push_snapshot(snap)
        if node.cycle % 10 == 0:
            print(f"[{time.strftime('%H:%M:%S')}] 周期{node.cycle} 状态={r.get('ok')} 技能激活={sum(1 for v in snap['skills'].values() if v['active'])}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
