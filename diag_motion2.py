#!/usr/bin/env python3
"""监听 motion 转移 5秒, 输出当前动作"""
import json, subprocess, time

def read_via_rclpy(topic, timeout=5):
    script = f'''
import rclpy, time, json
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init()
node = Node("motion_probe2")
got = []
def cb(msg):
    got.append((time.time(), msg.data))
node.create_subscription(String, "{topic}", cb, 10)
deadline = time.time() + {timeout}
while time.time() < deadline:
    rclpy.spin_once(node, timeout_sec=0.3)
if got:
    for ts, d in got[-3:]:
        print("DATA:" + d)
else:
    print("NODATA")
node.destroy_node()
rclpy.shutdown()
'''
    cmd = f"source /opt/ros/humble/setup.bash && timeout {timeout+3} python3 -c '{script}'"
    r = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=timeout+6)
    return [l[5:] for l in r.stdout.strip().split('\n') if l.startswith("DATA:")]

print("=== /motion/active_transition (5秒窗口) ===")
for d in read_via_rclpy('/motion/active_transition', 5):
    try:
        obj = json.loads(d)
        frm = obj.get('from','').split('::')[-1]
        to = obj.get('to','').split('::')[-1]
        print(f'  转移: {frm} → {to}')
    except:
        print('  原始:', d[:150])

print("\n=== /motion/execution_result (5秒窗口) ===")
for d in read_via_rclpy('/motion/execution_result', 5):
    print('  结果:', d[:150])
