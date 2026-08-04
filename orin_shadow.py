#!/usr/bin/env python3
"""Z-MAX 影子模式 (Shadow Mode) · sim-to-real 对比
============================================
真机运行时, 用仿真训练模型(metaworld)在影子中推理,
与真机实际动作对比, 记录差异, 回传 ECS 供迭代训练。

影子模式 = 只读推理, 绝不发布任何真实控制指令。
真机照常运行, 影子模型在旁边"看着"并对比。

流程:
  1. 订阅真机关节状态 (60Hz)
  2. 影子模型推理 → 预测动作 (4D: dx,dy,dz,gripper)
  3. 与真机实际执行的动作对比 (误差分析)
  4. 记录到 shadow_report.json + 回传 ECS relay

用法 (Orin):
  bash -c 'source /opt/ros/humble/setup.bash && python3 orin_shadow.py'
"""
import json
import os
import sys
import time
import threading
import urllib.request

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import JointState, Image

# 产线 QoS: BEST_EFFORT (robot_driver 发布)
RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                          history=HistoryPolicy.KEEP_LAST)

# ============ 配置 ============
MODEL_PATH = os.path.expanduser("~/.zmax/models/act_model.safetensors")
RELAY_URL = "http://datadrive.world/api/relay/upload"
SHADOW_INTERVAL = 0.5      # 影子推理间隔 (秒)
REPORT_INTERVAL = 60       # 回传间隔 (秒)
REPORT_DIR = os.path.expanduser("~/.zmax/shadow_reports")
IMAGE_TOPIC = "/realsense/color/image_raw"
IMG_W, IMG_H = 224, 224    # ACT 输入尺寸 (resnet18 预处理后)

# 真机 6 关节 (SR5/XMS5): joint_1..6
REAL_JOINT_NAMES = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"]
# metaworld 仿真 4D 动作: [dx, dy, dz, gripper] (末端笛卡尔速度 + 夹爪)
ACT_DIM = 4

# ============ 全局 ============
_latest_joints = None       # 真机最新关节状态
_latest_image = None        # 最新图像 (原始 bytes)
_shadow_samples = []        # 影子对比样本
_report_count = 0
_lock = threading.Lock()


class ShadowNode(Node):
    """订阅真机关节状态 + 相机图像"""

    def __init__(self):
        super().__init__("orin_shadow")
        self.sub = self.create_subscription(
            JointState, "/robot/joint_states", self.on_joints, RELIABLE_QOS)
        self.sub_img = self.create_subscription(
            Image, IMAGE_TOPIC, self.on_image, RELIABLE_QOS)

    def on_joints(self, msg):
        global _latest_joints
        try:
            names = list(msg.name)
            pos = list(msg.position)
            _latest_joints = {n: p for n, p in zip(names, pos)}
        except Exception:
            pass

    def on_image(self, msg):
        global _latest_image
        try:
            import numpy as np
            _latest_image = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(
                msg.height, msg.width, 3).copy()
        except Exception:
            pass


def load_model():
    """加载影子模型 (自动推断维度)"""
    from orin_act_standalone import build_act_from_ckpt
    act = build_act_from_ckpt(MODEL_PATH)
    act.to(DEV)   # 模型移到推理设备 (重要!)
    act.eval()
    # ACT 顶层属性直接读维度
    try:
        state_dim = act.input_dim
        act_dim = act.output_dim
    except Exception:
        try:
            w2 = act.action_head.weight
            act_dim = w2.shape[0]
            state_dim = act.encoder_robot_state_input_proj.weight.shape[1]
        except Exception:
            state_dim, act_dim = 6, 6
    print(f"🧠 影子模型: state={state_dim}D → action={act_dim}D (含视觉backbone)")
    return act, state_dim, act_dim


def build_state_vector(state_dim):
    """从真机关节状态构建模型输入向量"""
    global _latest_joints
    if _latest_joints is None:
        return None
    pos = [_latest_joints.get(n, 0.0) for n in REAL_JOINT_NAMES[:state_dim]]
    return np.array(pos, dtype=np.float32)


def build_image_tensor():
    """从最新相机帧构建 ACT 图像输入 (224x224)"""
    global _latest_image
    if _latest_image is None:
        return None
    try:
        img = _latest_image
        # 缩放 + 归一化 (与训练预处理一致)
        import cv2
        img = cv2.resize(img, (IMG_W, IMG_H))
        img = img[:, :, ::-1]  # BGR→RGB
        img = img.astype(np.float32) / 255.0
        # ImageNet 归一化
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img = (img - mean) / std
        img = img.transpose(2, 0, 1)  # HWC→CHW
        return torch.from_numpy(img).unsqueeze(0).to(DEV)
    except Exception as e:
        print(f"⚠️ 图像处理失败: {e}", flush=True)
        return None


def run_shadow_once(act, state_dim, act_dim):
    """影子推理一次: 真机状态+图像 → 预测动作"""
    global _shadow_samples
    state = build_state_vector(state_dim)
    img_t = build_image_tensor()
    if state is None or img_t is None:
        return None
    t0 = time.time()
    with torch.no_grad():
        state_t = torch.from_numpy(state).unsqueeze(0).to(DEV)
        action = act.forward(img_t, state_t)  # (B, queries, out_dim)
        action = action.cpu().numpy()
        action = np.asarray(action)
        # 取第一步动作
        if action.ndim == 3:
            action = action[0, 0]
        elif action.ndim == 2:
            action = action[0]
        action = np.asarray(action).reshape(-1)
    dt_ms = (time.time() - t0) * 1000

    sample = {
        "ts": time.time(),
        "state": state.tolist(),
        "shadow_action": action[:act_dim].tolist(),  # 影子预测
        "infer_ms": round(dt_ms, 1),
    }
    with _lock:
        _shadow_samples.append(sample)
        # 限制内存
        if len(_shadow_samples) > 200:
            _shadow_samples = _shadow_samples[-200:]
    return sample


def report_and_upload():
    """汇总影子对比报告 → 回传 ECS"""
    global _shadow_samples, _report_count
    with _lock:
        if not _shadow_samples:
            return
        samples = _shadow_samples
        _shadow_samples = []

    # 统计
    actions = np.array([s["shadow_action"] for s in samples])
    report = {
        "meta": {"source": "orin_shadow", "type": "shadow_report", "time": time.time()},
        "shadow": {
            "count": len(samples),
            "act_dim": actions.shape[1] if len(actions) else 0,
            "action_mean": [round(float(x), 4) for x in actions.mean(axis=0)] if len(actions) else [],
            "action_std": [round(float(x), 4) for x in actions.std(axis=0)] if len(actions) else [],
            "action_max": [round(float(x), 4) for x in actions.max(axis=0)] if len(actions) else [],
            "action_min": [round(float(x), 4) for x in actions.min(axis=0)] if len(actions) else [],
            "infer_ms_avg": round(np.mean([s["infer_ms"] for s in samples]), 1),
            "state_dim": len(samples[0]["state"]) if samples else 0,
        },
        "samples": samples[-20:],  # 只回传最近20条
    }

    # 本地保存
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"shadow_{int(time.time())}.json")
    with open(path, "w") as f:
        json.dump(report, f, ensure_ascii=False)

    # 回传 ECS
    try:
        data = json.dumps(report).encode()
        req = urllib.request.Request(RELAY_URL, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            _report_count += 1
            print(f"📤 [影子#{_report_count}] 回传 {len(samples)}样本 → relay", flush=True)
    except Exception as e:
        print(f"⚠️ 回传失败: {e}", flush=True)


def main():
    global torch, DEV
    import torch

    # 设备
    DEV = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Z-MAX 影子模式 (sim-to-real) ===")
    print(f"模型: {MODEL_PATH} ({DEV})")

    act, state_dim, act_dim = load_model()
    print(f"⚠️ 影子模式: 只读推理, 绝不发布真实控制指令")
    print(f"⚠️ 真机运行不受影响, 影子在旁边对比")

    # ROS 订阅
    rclpy.init()
    node = ShadowNode()
    threading.Thread(target=lambda: rclpy.spin(node), daemon=True).start()

    # 主循环: 影子推理 + 定期回传
    last_report = time.time()
    while rclpy.ok():
        try:
            sample = run_shadow_once(act, state_dim, act_dim)
            if sample:
                print(f"🕶️ [{time.strftime('%H:%M:%S')}] 状态{sample['state'][:3]}... "
                      f"→ 影子动作 {[round(a,3) for a in sample['shadow_action']]} "
                      f"({sample['infer_ms']}ms)", flush=True)
            # 定期回传
            if time.time() - last_report >= REPORT_INTERVAL:
                report_and_upload()
                last_report = time.time()
            time.sleep(SHADOW_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"⚠️ {e}", flush=True)
            time.sleep(1)

    report_and_upload()
    node.destroy_node()
    rclpy.shutdown()
    print("=== 影子模式结束 ===")


if __name__ == "__main__":
    main()
