#!/usr/bin/env python3
"""读取 motion 状态机 (rclpy 直接订阅, 无截断)"""
import json, subprocess, sys

def read_via_rclpy(topic):
    """用 rclpy 订阅一次并返回完整 JSON"""
    script = f'''
import rclpy, time, json
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init()
node = Node("motion_probe")
got = []
def cb(msg):
    if len(got) < 1:
        got.append(msg.data)
node.create_subscription(String, "{topic}", cb, 10)
deadline = time.time() + 5
while time.time() < deadline and not got:
    rclpy.spin_once(node, timeout_sec=0.3)
if got:
    print("DATA:" + got[0])
else:
    print("NODATA")
node.destroy_node()
rclpy.shutdown()
'''
    cmd = f"source /opt/ros/humble/setup.bash && timeout 10 python3 -c '{script}'"
    r = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=15)
    out = r.stdout.strip()
    if out.startswith("DATA:"):
        return out[5:]
    return None

for topic in ['/motion/active_states', '/motion/active_transition', '/motion/initialization_complete']:
    print(f'═══ {topic} ═══')
    data = read_via_rclpy(topic)
    if data:
        try:
            d = json.loads(data)
            print(json.dumps(d, indent=2, ensure_ascii=False)[:1200])
        except Exception:
            print('原始:', data[:600])
    else:
        print('(无数据)')
    print()
