#!/usr/bin/env python3
"""诊断: active_transition 数据结构和发布频率"""
import json, subprocess

script = '''
import rclpy, time, json
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init()
node = Node("diag_trans")
trans = []
states = []
def cb_t(msg):
    trans.append(msg.data)
def cb_s(msg):
    states.append(msg.data)
node.create_subscription(String, "/motion/active_transition", cb_t, 10)
node.create_subscription(String, "/motion/active_states", cb_s, 10)
end = time.time() + 20
while time.time() < end:
    rclpy.spin_once(node, timeout_sec=0.3)
print("=== active_transition 收到的消息 ===")
for t in trans[-5:]:
    try:
        d = json.loads(t)
        frm = d.get("from","").split("::")[-1] if "::" in d.get("from","") else d.get("from","")
        to = d.get("to","").split("::")[-1] if "::" in d.get("to","") else d.get("to","")
        print(f"  转移: {frm} → {to}")
    except Exception as e:
        print("  原始:", t[:120])
print(f"=== active_states 收到 {len(states)} 条 ===")
if states:
    try:
        d = json.loads(states[-1])
        all_s = [s.split("::")[-1] for s in d.get("states",[])]
        print("  状态列表:", all_s)
    except: pass
node.destroy_node()
rclpy.shutdown()
'''

cmd = 'source /opt/ros/humble/setup.bash && timeout 25 python3 -c "' + script.replace(chr(34), chr(39)) + '"'
r = subprocess.run(['bash','-c',cmd], capture_output=True, text=True, timeout=30)
print(r.stdout[-800:])
