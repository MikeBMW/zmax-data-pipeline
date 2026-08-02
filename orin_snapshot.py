#!/usr/bin/env python3
"""Orin 现场快照服务 v3 · 动作联动
========================================
- 监听 motion 状态机 (active_states / active_transition)
- 动作开始时立即拍照
- 平时 1fps 刷新
- 把当前动作文本写到图像上
- JPEG 压缩上传 ECS (relay peek 供 cicd.html 显示)

用法 (Orin, 需source ROS):
  python3 orin_snapshot.py
"""
import base64
import json
import time
import urllib.request

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

SNAP_URL = "http://datadrive.world/api/relay/upload"
INTERVAL = 0.25       # 4fps (相机已提速到16fps, 快照抓4fps足够流畅)
JPEG_QUALITY = 55     # 清晰度
IMG_SCALE = 0.75      # 424x240 → 318x180 (适中)


class SnapshotNode(Node):
    def __init__(self):
        super().__init__("snapshot_service_v3")
        self.latest = None
        self.latest_ts = 0
        self.motion_states = []        # 当前激活状态机
        self.last_transition = None    # 最近一次转移
        self.last_transition_ts = 0
        self.current_state = None      # 当前状态 (从transition.to提取)
        self.infer_count = 0

        self.sub = self.create_subscription(Image, "/realsense/color/image_raw", self.on_img, 10)
        self.sub_states = self.create_subscription(String, "/motion/active_states", self.on_states, 10)
        self.sub_trans = self.create_subscription(String, "/motion/active_transition", self.on_trans, 10)

    def on_img(self, msg):
        self.latest = msg
        self.latest_ts = time.time()

    def on_states(self, msg):
        try:
            d = json.loads(msg.data)
            self.motion_states = d.get("states", [])
        except Exception:
            pass

    def on_trans(self, msg):
        try:
            d = json.loads(msg.data)
            self.last_transition = d
            self.last_transition_ts = time.time()
            # 当前状态 = 转移的 to 字段 (中文/英文名)
            to_full = d.get("to", "")
            self.current_state = to_full.split("::")[-1] if "::" in to_full else to_full
        except Exception:
            pass

    def current_action(self):
        """提取当前动作名 (状态机路径最后一段, 取最新激活)"""
        if self.motion_states:
            # states 数组是累积的, 最后一个是当前状态
            s = self.motion_states[-1]
            return s.split("::")[-1] if "::" in s else s.split("/")[-1]
        return "IDLE"

    def all_state_names(self):
        """全量状态名列表 (去重)"""
        seen = []
        for s in self.motion_states:
            name = s.split("::")[-1] if "::" in s else s.split("/")[-1]
            if name not in seen:
                seen.append(name)
        return seen

    def transition_text(self):
        """最近的转移描述"""
        if self.last_transition and time.time() - self.last_transition_ts < 5:
            frm = self.last_transition.get("from", "").split("::")[-1]
            to = self.last_transition.get("to", "").split("::")[-1]
            return f"{frm} → {to}"
        return None

    def grab_jpeg(self):
        """取最新帧 → 画动作文本 → JPEG"""
        if self.latest is None:
            return None, None
        m = self.latest
        try:
            if m.encoding in ("bgr8", "rgb8"):
                img = np.frombuffer(m.data, dtype=np.uint8).reshape(m.height, m.width, 3)
                if m.encoding == "rgb8":
                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                # 相机安装方向修正: 图像翻转 180° (flip -1 = 水平+垂直)
                img = cv2.flip(img, -1)
                # 缩小 (文字不叠加, 图片可稍大)
                small = cv2.resize(img, None, fx=IMG_SCALE, fy=IMG_SCALE,
                                   interpolation=cv2.INTER_AREA)

                ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    return buf.tobytes(), self.current_action()
        except Exception as e:
            print(f"⚠️ 图像处理失败: {e}")
        return None, None


def upload_snapshot(jpeg_bytes, action, ts, node):
    pkg = {
        "meta": {"source": "orin_snapshot", "time": ts, "type": "camera_snapshot",
                 "action": action},
        "snapshot_b64": base64.b64encode(jpeg_bytes).decode(),
        "timestamp": ts,
        "action": action,
        "current_state": node.current_state,          # 当前状态 (高亮)
        "all_states": node.all_state_names(),         # 全量状态 (弱化)
    }
    data = json.dumps(pkg).encode()
    req = urllib.request.Request(SNAP_URL, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()[:80]
    except Exception as e:
        return f"ERR: {e}"


def main():
    print("=== Orin 现场快照 v3 (动作联动 1fps) ===")
    rclpy.init()
    node = SnapshotNode()

    import threading
    def spin():
        rclpy.spin(node)
    threading.Thread(target=spin, daemon=True).start()

    print("⏳ 等待相机帧...")
    while node.latest is None:
        time.sleep(0.5)
    print("✅ 相机已连接")

    last_action = None
    while rclpy.ok():
        ts = time.time()
        jpeg, action = node.grab_jpeg()
        if jpeg:
            # 动作变化 → 立即上传; 平时 1fps
            action_changed = (action != last_action)
            result = upload_snapshot(jpeg, action, ts, node)
            flag = "⚡动作变化" if action_changed else "   "
            print(f"[{time.strftime('%H:%M:%S')}] {flag} {action} {len(jpeg)/1024:.0f}KB → {result}", flush=True)
            last_action = action
        time.sleep(INTERVAL)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
