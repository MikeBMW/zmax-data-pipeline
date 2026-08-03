#!/usr/bin/env python3
"""Orin 系统性能采集 → 心跳 sys 字段 (供 cicd.html 显示)
小芳在 Orin 侧运行: orin_infer_service.py 心跳里调用本函数

返回字段 (web 前端 cicd.html 显示用):
  cpu:      CPU使用率 %
  gpu:      GPU使用率 % (tegrastats GR3D)
  mem_pct:  内存使用率 %
  mem_used: 已用内存 MB
  mem_total: 总内存 MB
  disk_pct: 磁盘使用率 %
  disk_used: 已用磁盘 GB
  disk_total: 总磁盘 GB
  net_rx:   下载 KB/s
  net_tx:   上传 KB/s
  temp:     温度 °C
"""
import os
import re
import subprocess
import time

_last_net = None
_last_ts = 0.0


def _get_gpu():
    """GPU 使用率: 优先 tegrastats GR3D_FREQ, fallback 频率占比"""
    # 方案1: tegrastats GR3D_FREQ
    try:
        r = subprocess.run(["/usr/bin/tegrastats", "--interval", "500"],
                           capture_output=True, text=True, timeout=3)
        if not r.stdout:
            r = subprocess.run(["/usr/bin/tegrastats"],
                               capture_output=True, text=True, timeout=3)
        if r.stdout:
            line = r.stdout.strip().splitlines()[-1]
            m = re.search(r"GR3D_FREQ\s+(\d+)%", line)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    # 方案2: GPU 频率占比 (cur_freq-min)/(max-min)
    try:
        base = "/sys/class/devfreq/17000000.gpu"
        with open(f"{base}/cur_freq") as f:
            cur = int(f.read().strip())
        with open(f"{base}/max_freq") as f:
            mx = int(f.read().strip())
        with open(f"{base}/min_freq") as f:
            mn = int(f.read().strip())
        if mx > mn:
            return round((cur - mn) / (mx - mn) * 100)
        return 0
    except Exception:
        pass
    return None  # 读不到返回 None, 前端显示 "N/A"


def get_sys_info():
    global _last_net, _last_ts
    info = {}

    # CPU
    try:
        import psutil
        info["cpu"] = round(psutil.cpu_percent(interval=0.2), 1)
    except ImportError:
        with open("/proc/loadavg") as f:
            info["cpu"] = round(float(f.read().split()[0]) * 100, 1)

    # GPU
    gpu = _get_gpu()
    if gpu is not None:
        info["gpu"] = gpu
    else:
        info["gpu"] = None  # N/A

    # 内存 (used/total MB + 百分比)
    try:
        with open("/proc/meminfo") as f:
            lines = dict(l.split(":", 1) for l in f if ":" in l)
        total = int(lines["MemTotal"].split()[0]) // 1024  # KB→MB
        avail = int(lines["MemAvailable"].split()[0]) // 1024
        used = total - avail
        info["mem_pct"] = round(used / total * 100, 1) if total else 0
        info["mem_used"] = used
        info["mem_total"] = total
    except Exception:
        info["mem_pct"] = 0
        info["mem_used"] = 0
        info["mem_total"] = 0

    # 磁盘 (used/total GB + 百分比)
    try:
        st = os.statvfs("/")
        total_gb = st.f_blocks * st.f_frsize / 1073741824
        free_gb = st.f_bavail * st.f_frsize / 1073741824
        used_gb = total_gb - free_gb
        info["disk_pct"] = round(used_gb / total_gb * 100, 1) if total_gb else 0
        info["disk_used"] = round(used_gb, 1)
        info["disk_total"] = round(total_gb, 1)
    except Exception:
        info["disk_pct"] = 0
        info["disk_used"] = 0
        info["disk_total"] = 0

    # 温度
    try:
        with open("/sys/devices/virtual/thermal/thermal_zone0/temp") as f:
            info["temp"] = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                info["temp"] = round(int(f.read().strip()) / 1000, 1)
        except Exception:
            info["temp"] = 0

    # 网络带宽 (rx/tx KB/s, /proc/net/dev 差分, 只统计物理接口排除lo)
    try:
        now = time.time()
        with open("/proc/net/dev") as f:
            rx = tx = 0
            for l in f.readlines()[2:]:
                iface = l.split(":")[0].strip()
                if iface.startswith("lo") or iface.startswith("docker"):
                    continue  # 排除回环/容器虚拟接口
                parts = l.split(":")
                if len(parts) > 1:
                    vals = parts[1].split()
                    rx += int(vals[0])
                    tx += int(vals[8])
        if _last_net is not None and now - _last_ts > 0:
            dt = now - _last_ts
            info["net_rx"] = round((rx - _last_net[0]) / 1024 / dt, 1)
            info["net_tx"] = round((tx - _last_net[1]) / 1024 / dt, 1)
        else:
            info["net_rx"] = 0.0
            info["net_tx"] = 0.0
        _last_net = (rx, tx)
        _last_ts = now
    except Exception:
        info["net_rx"] = 0.0
        info["net_tx"] = 0.0

    return info


if __name__ == "__main__":
    import json
    print(json.dumps(get_sys_info(), ensure_ascii=False))
