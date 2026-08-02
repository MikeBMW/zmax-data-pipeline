#!/usr/bin/env python3
"""Z-MAX 数据上传 v2 · Orin侧
MCAP → rosbags解析 → JSON包(关节+图像) → 裸POST ECS relay → 静静训练

用法 (Orin):
  python3 upload_data_v2.py [mcap_dir]
  python3 upload_data_v2.py            # 自动用最新mcap
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


def latest_mcap():
    dirs = sorted(MCAP_ROOT.glob("record_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    dirs = [d for d in dirs if d.is_dir()]
    return dirs[0] if dirs else None


def extract(mcap_dir):
    """提取关节+图像帧, 过滤重复静态帧"""
    typestore = get_typestore(Stores.ROS2_HUMBLE)
    states = []
    images = []
    JOINT_EPS = 0.02      # 关节变化阈值 (rad)
    IMG_EPS = 8.0         # 图像均差阈值 (像素)
    with AnyReader([Path(mcap_dir)], default_typestore=typestore) as reader:
        conns = list(reader.connections)
        joint_conns = [c for c in conns if "JointState" in c.msgtype and "sim" not in c.topic]
        img_conns = [c for c in conns if "Image" in c.msgtype and "color" in c.topic]

        # 第一遍: 关节帧去重 (相邻帧变化 < 阈值 → 丢弃)
        last_pos = None
        for conn, ts, raw in reader.messages(connections=joint_conns):
            msg = reader.deserialize(raw, conn.msgtype)
            pos = list(msg.position)
            if len(pos) < 6 or not all(-10 < v < 10 for v in pos):
                continue
            pos = [round(float(v), 4) for v in pos[:6]]
            if last_pos is None or max(abs(a - b) for a, b in zip(pos, last_pos)) > JOINT_EPS:
                states.append({"ts": ts, "state": pos})
                last_pos = pos
            if len(states) >= MAX_FRAMES:
                break

        # 第二遍: 图像帧去重 (与上一张均差 < 阈值 → 丢弃)
        last_img = None
        last_ts = None
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

    # 统计
    print(f"  关节帧去重后: {len(states)}, 图像帧去重后: {len(images)}")
    return states, images


def build_pkg(states, images):
    """组装 relay_train.py 期望的 JSON 包"""
    frames = []
    n = min(len(states), 150)
    for i in range(n):
        fr = {"observation.state": states[i]["state"],
              "action": states[i]["state"]}  # 闭环: 动作=当前状态(演示数据)
        # 匹配最近的图像
        img = images[i]["image"] if i < len(images) else None
        if img is not None:
            small = cv2.resize(img, (64, 64))
            ok, buf = cv2.imencode(".jpg", small)
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
    print(f"🔬 关节帧: {len(states)}, 图像帧: {len(images)}")
    if not states:
        print("❌ 无关节数据")
        return

    pkg = build_pkg(states, images)
    upload(pkg)


if __name__ == "__main__":
    main()
