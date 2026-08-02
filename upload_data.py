#!/usr/bin/env python3
"""Z-MAX 数据上传 · Orin采集 → ECS relay → 静静训练
================================================
读取 Orin 最新 MCAP → 提取帧(关节+图像) → 转 JSON 包 → 裸POST relay

用法:
  python3 upload_data.py                    # 采集30s+上传
  python3 upload_data.py --duration 10      # 自定义时长
  python3 upload_data.py --mcap <path>      # 用已有mcap
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

import cv2
import numpy as np

ORIN = "tashan@192.168.23.66"
GATEWAY = "http://192.168.23.66:8765"
RELAY = "http://datadrive.world/api/relay/upload"


def collect(duration=30):
    """触发 Orin 录制并返回 mcap 目录"""
    print(f"🎥 Orin 采集 {duration}s...")
    r = urllib.request.urlopen(f"{GATEWAY}/record/start?duration={duration}", timeout=10)
    print("  ", json.loads(r.read()))
    time.sleep(duration + 5)

    # 找最新 mcap
    r = urllib.request.urlopen(f"{GATEWAY}/record/latest", timeout=10)
    info = json.loads(r.read())
    mcap_dir = info.get("dir")
    print(f"📁 MCAP: {mcap_dir} ({info.get('size_mb')}MB)")
    return mcap_dir


def read_mcap(mcap_dir, max_frames=200):
    """用 ros2 读 mcap → 提取关节+图像帧"""
    print(f"🔬 读取 MCAP: {mcap_dir}")
    # ros2 bag play + echo 太复杂, 直接用 python rosbags 读 sqlite3
    import sqlite3

    db = None
    for f in os.listdir(mcap_dir):
        if f.endswith(".db3"):
            db = os.path.join(mcap_dir, f)
            break
    if not db:
        print("❌ 无 db3")
        return None

    conn = sqlite3.connect(db)
    cur = conn.cursor()
    # rosbag2 sqlite schema
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]
    if "topics" not in tables:
        print("❌ 非 rosbag2 格式")
        conn.close()
        return None

    # 话题 ID 映射
    cur.execute("SELECT id, name, type FROM topics")
    topics = {tid: (name, ttype) for tid, name, ttype in cur.fetchall()}
    cur.execute("SELECT topic_id, timestamp, data FROM messages ORDER BY timestamp")
    rows = cur.fetchall()
    conn.close()

    frames = []
    for tid, ts, data in rows:
        name, ttype = topics.get(tid, ("?", "?"))
        if len(frames) >= max_frames:
            break
        try:
            if "JointState" in ttype:
                # 解析 joint states (sensor_msgs/JointState)
                pos = parse_joint_state(data)
                if pos:
                    frames.append({"ts": ts, "type": "state", "state": pos})
            elif "Image" in ttype and "color" in name:
                # 解析图像 (sensor_msgs/Image, rgb8)
                img = parse_image(data)
                if img is not None:
                    frames.append({"ts": ts, "type": "image", "image": img})
        except Exception:
            continue

    # 对齐: 每帧配 state + image
    states = [f for f in frames if f["type"] == "state"]
    images = [f for f in frames if f["type"] == "image"]
    print(f"  关节帧: {len(states)}, 图像帧: {len(images)}")
    return states, images


def parse_joint_state(data):
    """解析 sensor_msgs/JointState (rosbag2 cdr)"""
    # 简化: 找 float64 数组位置 (position[])
    # 用 numpy 从 bytes 提取
    import struct
    # ros2 CDR: 复杂, 用暴力搜索 float64 序列
    arr = np.frombuffer(data, dtype=np.uint8)
    # 搜索 6 个连续 float64 的模式 (关节值)
    f64 = np.frombuffer(data, dtype=np.float64)
    if len(f64) < 6:
        return None
    # 取最后 6 个合理值
    vals = [float(v) for v in f64[-12:-6]]
    if all(-10 < v < 10 for v in vals):
        return vals
    return None


def parse_image(data):
    """解析 sensor_msgs/Image rgb8"""
    # 简化: 暴力找 640*480*3 的字节块, 转 JPEG
    # 实际用 cv_bridge 更可靠, 这里尝试直接解码
    try:
        arr = np.frombuffer(data, dtype=np.uint8)
        # 图像数据通常是最后的大块
        if len(arr) < 640 * 480 * 3:
            return None
        # 尝试从尾部提取
        img = arr[-640 * 480 * 3:].reshape(480, 640, 3)
        return img
    except Exception:
        return None


def build_pkg(states, images):
    """组装 JSON 数据包 (relay_train.py 期望格式)"""
    frames = []
    n = min(len(states), len(images)) if states and images else max(len(states), len(images))
    n = min(n, 200)
    for i in range(n):
        fr = {}
        if i < len(states):
            fr["observation.state"] = [round(x, 4) for x in states[i]["state"]]
            fr["action"] = [round(x, 4) for x in states[i]["state"]]  # 模拟动作=状态
        if i < len(images):
            img = images[i]["image"]
            ok, buf = cv2.imencode(".jpg", img)
            if ok:
                fr["camera_b64"] = base64.b64encode(buf.tobytes()).decode()
        if fr:
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
    """裸二进制 POST 到 relay"""
    data = json.dumps(pkg).encode()
    print(f"📤 上传 {len(data)/1024:.0f}KB ({pkg['meta']['frames']}帧) → relay")
    req = urllib.request.Request(RELAY, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = resp.read().decode()
    print(f"✅ 上传结果: {result[:200]}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=15)
    ap.add_argument("--mcap", default=None)
    args = ap.parse_args()

    mcap_dir = args.mcap or collect(args.duration)
    result = read_mcap(mcap_dir)
    if not result:
        print("❌ 无有效数据")
        return
    states, images = result
    if not states and not images:
        print("❌ 帧为空")
        return

    pkg = build_pkg(states, images)
    if pkg["frames"]:
        upload(pkg)
    else:
        print("❌ 无帧可上传")


if __name__ == "__main__":
    main()
