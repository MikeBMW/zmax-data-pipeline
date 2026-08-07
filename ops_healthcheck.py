#!/usr/bin/env python3
"""Z-MAX 自动运维 · 链路健康检查 + 自愈 (7x24)
========================================
检查内容:
  1. ECS 端点 (relay/snapshot/orin-status)
  2. Orin 服务进程 (gateway/infer/snapshot/shadow)
  3. Orin 资源 (负载/温度/磁盘)
  4. 数据质量 (relay包数/快照新鲜度)
自愈:
  - Orin 服务挂了 → 自动重启
  - 快照过期 → 告警
用法:
  python3 ops_healthcheck.py           # 检查并输出报告
  python3 ops_healthcheck.py --fix     # 检查+自动修复
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ECS = "http://datadrive.world"
ORIN = "tashan@192.168.23.66"
ORIN_ZMAX = "/home/tashan/.zmax"
FIX = "--fix" in sys.argv

# Orin 服务定义: (pgrep模式, 启动命令)
ORIN_SERVICES = [
    ("orin_gateway.py", f"cd {ORIN_ZMAX} && setsid nohup python3 -u orin_gateway.py > /tmp/gw.log 2>&1 < /dev/null &"),
    ("orin_infer_service.py", f"cd {ORIN_ZMAX} && setsid nohup python3 -u orin_infer_service.py {ORIN_ZMAX}/models/act_model.safetensors > /tmp/infer_svc.log 2>&1 < /dev/null &"),
    ("orin_snapshot.py", f"source /opt/ros/humble/setup.bash && cd {ORIN_ZMAX} && setsid nohup python3 -u orin_snapshot.py > /tmp/snapshot.log 2>&1 < /dev/null &"),
    ("orin_shadow.py", f"source /opt/ros/humble/setup.bash && cd {ORIN_ZMAX} && setsid nohup python3 -u orin_shadow.py > /tmp/shadow.log 2>&1 < /dev/null &"),
]

results = []


def check_http(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except Exception:
        return 0


def ssh_cmd(cmd, timeout=15):
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                            ORIN, cmd], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def main():
    print("=== Z-MAX 自动运维检查 ===")

    # 1. ECS 端点
    print("\n[1] ECS 端点:")
    for ep in ["api/relay/status", "api/snapshot/latest", "orin/status"]:
        code = check_http(f"{ECS}/{ep}")
        ok = code == 200
        results.append(("ECS/" + ep, ok))
        print(f"  {'✅' if ok else '❌'} {ep}: {code}")

    # 2. Orin 在线
    print("\n[2] Orin:")
    online = ssh_cmd("echo OK") == "OK"
    results.append(("Orin在线", online))
    print(f"  {'✅' if online else '❌'} SSH: {'通' if online else '不通'}")

    if online:
        # 3. Orin 资源
        load = ssh_cmd("uptime | awk -F'load average' '{print $2}'")
        temp = ssh_cmd("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{print $1/1000}'")
        disk = ssh_cmd("df -h / | tail -1 | awk '{print $4}'")
        print(f"  负载: {load} | 温度: {temp}°C | 磁盘: {disk}")

        # 4. Orin 服务
        print("\n[3] Orin 服务:")
        for pattern, start_cmd in ORIN_SERVICES:
            cnt = ssh_cmd(f"pgrep -f {pattern} | head -1 | wc -l")
            running = cnt.strip() == "1"
            results.append((pattern, running))
            if running:
                print(f"  ✅ {pattern}")
            elif FIX:
                print(f"  🔧 {pattern} 挂了 → 重启")
                ssh_cmd(start_cmd, timeout=20)
                time.sleep(5)
                cnt2 = ssh_cmd(f"pgrep -f {pattern} | head -1 | wc -l")
                results.append((pattern + "-修复", cnt2.strip() == "1"))
            else:
                print(f"  ❌ {pattern} 挂了 (加 --fix 自动重启)")

        # 5. 数据质量
        print("\n[4] 数据质量:")
        snap_age = ssh_cmd("curl -s --max-time 4 'http://datadrive.world/api/relay/cam/status' 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get(\"age_s\", 999))' 2>/dev/null")
        print(f"  快照新鲜度: {snap_age}s {'✅' if snap_age and float(snap_age) < 30 else '⚠️ 过期'}")

    # 汇总
    bad = [r for r in results if not r[1]]
    print(f"\n=== 结果: {'✅ 全部正常' if not bad else '❌ ' + str(len(bad)) + ' 项异常'} ===")
    for name, ok in bad:
        print(f"  异常: {name}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
