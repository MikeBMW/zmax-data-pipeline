#!/usr/bin/env python3
"""诊断 motion 状态机中文编码"""
import json, subprocess

def read_via_rclpy(topic, timeout=5):
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
deadline = time.time() + {timeout}
while time.time() < deadline and not got:
    rclpy.spin_once(node, timeout_sec=0.3)
if got:
    print("DATA:" + got[0])
else:
    print("NODATA")
node.destroy_node()
rclpy.shutdown()
'''
    cmd = f"source /opt/ros/humble/setup.bash && timeout {timeout+3} python3 -c '{script}'"
    r = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=timeout+6)
    out = r.stdout.strip()
    return out[5:] if out.startswith("DATA:") else None

data = read_via_rclpy('/motion/active_states')
print('=== active_states ===')
print('原始JSON:', data)
if data:
    try:
        d = json.loads(data)
        print('states 数量:', len(d.get('states', [])))
        for s in d.get('states', []):
            name = s.split('::')[-1]
            print(f'  状态名: [{name}] unicode={[hex(ord(c)) for c in name[:6]]}')
    except Exception as e:
        print('解析失败:', e)
