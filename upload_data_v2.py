#!/usr/bin/env python3
"""Z-MAX 数据上传 v3 · Stage-ACT 打标版
========================================
读取 Orin MCAP → 提取帧(关节+图像) + motion状态机标签 → 上传 relay

Stage ACT 支持:
  每帧带 label (motion 状态机当前状态, 如: 取料/扫码/插入)
  4060 训练 stage_act 时按 label 分阶段训练
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import urllib.request

from rosbags.highlevel import AnyReader
from rosbags.typesys import Stores, get_typestore

RELAY = "http://datadrive.world/api/relay/upload"
MCAP_ROOT = Path.home() / ".zmax" / "mcap"
MAX_FRAMES = 300

# motion 状态机话题 (Stage ACT 标签来源)
MOTION_TOPIC = "/motion/active_states"


def latest_mcap():
    dirs = sorted(MCAP_ROOT.glob("record_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    dirs = [d for d in dirs if d.is_dir()]
    return dirs[0] if dirs else None


def extract(mcap_dir):
    """提取关节+图像帧+motion标签, 过滤重复静态帧"""
    typestore = get_typestore(Stores.ROS2_HUMBLE)
    states = []
    images = []
    motion_log = []   # (ts, label) 状态机时间线
    JOINT_EPS = 0.01     # 关节变化阈值 (rad) — 0.02偏严, 慢动作帧被滤掉
    IMG_EPS = 8.0

    with AnyReader([Path(mcap_dir)], default_typestore=typestore) as reader:
        conns = list(reader.connections)
        joint_conns = [c for c in conns if "JointState" in c.msgtype and "sim" not in c.topic]
        img_conns = [c for c in conns if "Image" in c.msgtype and "color" in c.topic]
        motion_conns = [c for c in conns if MOTION_TOPIC in c.topic]

        # 0. motion 状态机时间线
        for conn, ts, raw in reader.messages(connections=motion_conns):
            try:
                msg = reader.deserialize(raw, conn.msgtype)
                d = json.loads(msg.data)
                # 取最后一个激活状态作为标签 (数组是累积的, 最后=最新)
                states_list = d.get("states", [])
                if states_list:
                    label = states_list[-1].split("::")[-1]
                    motion_log.append((ts, label))
            except Exception:
                pass

        # 1. 关节帧去重 (累计变化采样 + 时间窗口: 至少200ms一帧)
        last_pos = None
        last_sampled_ts = 0
        MIN_INTERVAL_NS = 200_000_000  # 200ms
        for conn, ts, raw in reader.messages(connections=joint_conns):
            msg = reader.deserialize(raw, conn.msgtype)
            pos = list(msg.position)
            if len(pos) < 6 or not all(-10 < v < 10 for v in pos):
                continue
            pos = [round(float(v), 4) for v in pos[:6]]
            changed = last_pos is None or max(abs(a - b) for a, b in zip(pos, last_pos)) > JOINT_EPS
            time_ok = ts - last_sampled_ts >= MIN_INTERVAL_NS
            if changed or time_ok:
                states.append({"ts": ts, "state": pos})
                last_pos = pos
                last_sampled_ts = ts
            if len(states) >= MAX_FRAMES:
                break

        # 2. 图像帧去重
        last_img = None
        for conn, ts, raw in reader.messages(connections=img_conns):
            msg = reader.deserialize(raw, conn.msgtype)
            try:
                if msg.encoding in ("rgb8", "bgr8"):
                    h, w = msg.height, msg.width
                    img = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, w, 3)
                    if msg.encoding == "bgr8":
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    small = cv2.resize(img, (64, 64))
                    if last_img is None or float(np.mean(np.abs(small.astype(float) - last_img.astype(float)))) > IMG_EPS:
                        images.append({"ts": ts, "image": small})
                        last_img = small
            except Exception:
                pass
            if len(images) >= MAX_FRAMES:
                break

    # 3. 标签对齐: 每帧找最近时间的 motion 状态
    motion_log.sort(key=lambda x: x[0])
    for s in states:
        s["label"] = nearest_label(s["ts"], motion_log)

    print(f"  关节帧: {len(states)}, 图像帧: {len(images)}, motion状态: {len(motion_log)}")
    return states, images


def nearest_label(ts, motion_log):
    """按时间戳找最近的 motion 状态标签"""
    if not motion_log:
        return "IDLE"
    # 二分找最后一个 <= ts 的标签
    lo, hi = 0, len(motion_log) - 1
    best = motion_log[0][1]
    while lo <= hi:
        mid = (lo + hi) // 2
        if motion_log[mid][0] <= ts:
            best = motion_log[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def build_pkg(states, images):
    """组装带 label 的 JSON 包 (Stage ACT 格式)"""
    frames = []
    n = min(len(states), 150)
    label_count = {}
    # 时间戳基准: 第一帧 ts (ns) → 秒
    t0 = states[0]["ts"] / 1e9 if states and states[0].get("ts") else 0
    for i in range(n):
        fr = {
            "observation.state": states[i]["state"],
            "action": states[i]["state"],
            "label": states[i].get("label", "IDLE"),   # Stage ACT 标签
            # LeRobot 必需字段 (静静 build 脚本依赖):
            "timestamp": (states[i]["ts"] / 1e9 - t0) if states[i].get("ts") else i / 30.0,
            "frame_index": i,
            "episode_index": 0,
        }
        label_count[fr["label"]] = label_count.get(fr["label"], 0) + 1
        img = images[i]["image"] if i < len(images) else None
        if img is not None:
            ok, buf = cv2.imencode(".jpg", img)
            if ok:
                fr["camera_b64"] = base64.b64encode(buf.tobytes()).decode()
        frames.append(fr)

    pkg = {
        "meta": {
            "source": "orin",
            "frames": len(frames),
            "n_joint": len(states[0]["state"]) if states else 6,
            "n_action": len(states[0]["state"]) if states else 6,
            "fps": 30,
            "stage_act": True,
            "labels": label_count,      # 标签分布
            "time": time.time(),
        },
        "frames": frames,
    }
    return pkg


def upload(pkg):
    data = json.dumps(pkg).encode()
    print(f"📤 上传 {len(data)/1024:.0f}KB / {pkg['meta']['frames']}帧 → relay")
    req = urllib.request.Request(RELAY, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = resp.read().decode()
        print(f"✅ 结果: {result[:200]}")
    except Exception as e:
        print(f"❌ 上传失败: {e}")


def main():
    mcap_dir = sys.argv[1] if len(sys.argv) > 1 else str(latest_mcap())
    if not mcap_dir or not os.path.isdir(mcap_dir):
        print("❌ 无 mcap")
        return
    print(f"📁 MCAP: {mcap_dir}")

    states, images = extract(mcap_dir)
    if not states:
        print("❌ 无关节数据")
        return

    pkg = build_pkg(states, images)
    print(f"🏷️  标签分布: {pkg['meta'].get('labels')}")
    upload(pkg)


if __name__ == "__main__":
    main()
