#!/usr/bin/env python3
"""Orin 现场状态采集器 · 实时上报机器人全量信息
================================================
每5秒采集: 关节/力觉/夹爪/相机/采集量/推理量/系统资源
上报到: POST /api/relay/orin/status (cicd.html 轮询源)

数据源:
  - /real_joint_states   关节 6轴
  - /robot/force_torque  六维力
  - /gripper_pos         夹爪
  - /realsense/...       相机状态
  - ~/.zmax/mcap/        采集工作量
  - :8766 /status        推理服务
"""
import json
import os
import subprocess
import time
import urllib.request

STATUS_URL = "http://datadrive.world/api/relay/upload"


def ros_echo(topic, timeout=5):
    """订阅一次 ROS2 话题"""
    cmd = f"source /opt/ros/humble/setup.bash && timeout {timeout} ros2 topic echo {topic} --once 2>/dev/null"
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout + 3)
        return r.stdout
    except Exception:
        return ""


def parse_yaml_like(text, key):
    """从 ros2 echo 输出提取 key 值"""
    for line in text.split("\n"):
        if line.strip().startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return None


def parse_float_list(text, key):
    """提取 float 列表"""
    vals = []
    in_list = False
    for line in text.split("\n"):
        s = line.strip()
        if s == key + ":":
            in_list = True
            continue
        if in_list:
            if s.startswith("-") or s.replace(".", "").replace("-", "").isdigit():
                try:
                    vals.append(float(s.lstrip("- ").split(" ")[0]) * (1 if s.startswith("-") else 1))
                    # ros2 yaml: "-0.578" 直接float
                    vals[-1] = float(s.split(" ")[-1])
                except Exception:
                    pass
            elif s and not s.startswith("-"):
                break
    return vals


def get_joints():
    out = ros_echo("/real_joint_states")
    pos = parse_float_list(out, "position")
    return [round(v, 3) for v in pos[:6]] if pos else None


def get_force():
    out = ros_echo("/robot/force_torque")
    fx = parse_yaml_like(out, "x")
    fy = parse_yaml_like(out, "y")
    fz = parse_yaml_like(out, "z")
    try:
        return [round(float(fx), 2), round(float(fy), 2), round(float(fz), 2)]
    except Exception:
        return None


def get_gripper():
    out = ros_echo("/gripper_pos")
    d = parse_yaml_like(out, "data")
    try:
        return round(float(d), 1)
    except Exception:
        return None


def get_camera_status():
    """相机话题是否在线"""
    out = ros_echo("/realsense/color/camera_info")
    h = parse_yaml_like(out, "height")
    w = parse_yaml_like(out, "width")
    return {"online": h is not None, "resolution": f"{w}x{h}" if w and h else None}


def get_collect_stats():
    """采集工作量统计"""
    mcap_dir = os.path.expanduser("~/.zmax/mcap")
    total_mb = 0
    count = 0
    if os.path.isdir(mcap_dir):
        for d in os.listdir(mcap_dir):
            dp = os.path.join(mcap_dir, d)
            if os.path.isdir(dp):
                for f in os.listdir(dp):
                    if f.endswith(".db3"):
                        total_mb += os.path.getsize(os.path.join(dp, f)) / 1048576
                        count += 1
    return {"mcap_mb": round(total_mb, 1), "bag_count": count}


def get_infer_status():
    try:
        with urllib.request.urlopen("http://localhost:8766/status", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return {"online": False}


def get_system():
    load = os.getloadavg()
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            mem[k] = int(v.strip().split()[0]) // 1024  # MB
    used = mem.get("MemTotal", 0) - mem.get("MemFree", 0) - mem.get("Buffers", 0) - mem.get("Cached", 0)
    # CPU 使用率 (读 /proc/stat 两次间隔计算)
    cpu_pct = 0.0
    try:
        def _cpu_times():
            with open("/proc/stat") as f:
                parts = f.readline().split()[1:]
            idle = int(parts[3]) + int(parts[4])
            total = sum(int(p) for p in parts)
            return idle, total
        i1, t1 = _cpu_times()
        time.sleep(0.5)
        i2, t2 = _cpu_times()
        cpu_pct = round(100 * (1 - (i2 - i1) / max(t2 - t1, 1)), 1)
    except Exception:
        pass
    # 温度
    temp = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass
    # 磁盘
    disk = {}
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize / 1073741824
        free = st.f_bavail * st.f_frsize / 1073741824
        disk = {"total_gb": round(total, 1), "free_gb": round(free, 1),
                "used_pct": round(100 * (1 - free / total), 1)}
    except Exception:
        pass
    # GPU (Orin 自带 GPU, 无 nvidia-smi; 用 GPU 频率采样近似)
    gpu = {}
    try:
        with open("/sys/class/devfreq/*/cur_freq") as f:
            pass
    except Exception:
        pass
    # 网络带宽 (读 /proc/net/dev 两次)
    net = {}
    try:
        def _net_bytes():
            with open("/proc/net/dev") as f:
                lines = f.readlines()[2:]
            rx = sum(int(l.split()[1]) for l in lines)
            tx = sum(int(l.split()[9]) for l in lines)
            return rx, tx
        r1, t1 = _net_bytes()
        time.sleep(0.5)
        r2, t2 = _net_bytes()
        net = {"rx_kbps": round((r2 - r1) / 1024 * 2, 1),
               "tx_kbps": round((t2 - t1) / 1024 * 2, 1)}
    except Exception:
        pass
    return {
        "load_avg": [round(x, 2) for x in load],
        "cpu_pct": cpu_pct,
        "temp_c": temp,
        "mem_total_mb": mem.get("MemTotal", 0),
        "mem_used_mb": used,
        "mem_pct": round(used / mem.get("MemTotal", 1) * 100, 1),
        "disk": disk,
        "net": net,
        "gpu": {"note": "Orin集成GPU, 无独立显存指标"},
    }


def main():
    print("=== Orin 现场状态采集器 ===", flush=True)
    while True:
        try:
            state = {
                "meta": {"source": "orin_sys", "type": "system_status", "time": time.time()},
                "online": True,
                "ts": time.time(),
                "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
                "robot": {
                    "joints": get_joints(),
                    "force": get_force(),
                    "gripper": get_gripper(),
                },
                "camera": get_camera_status(),
                "collect": get_collect_stats(),
                "infer": get_infer_status(),
                "system": get_system(),
            }
            data = json.dumps(state).encode()
            req = urllib.request.Request(STATUS_URL, data=data,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                pass
            print(f"[{time.strftime('%H:%M:%S')}] 上报: 关节{state['robot']['joints']} 力{state['robot']['force']} "
                  f"采集{state['collect']['mcap_mb']}MB 推理{state['infer'].get('infer_count', 0)}次 "
                  f"负载{state['system']['load_avg'][0]}", flush=True)
        except Exception as e:
            print(f"⚠️ {e}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
