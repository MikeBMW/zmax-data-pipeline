#!/usr/bin/env python3
"""Simulink CI · 自动拉取部署 (MAC侧)
轮询 ECS 中继, 有模型包就下载 → 部署到 Orin → 验证 → 报告

用法:
  python3 auto_deploy.py --once     # 拉一次
  python3 auto_deploy.py --watch    # 持续轮询(默认)
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

RELAY = "http://datadrive.world/api/relay"
ORIN = "tashan@192.168.23.66"
ORIN_MODEL_DIR = "/home/tashan/.zmax/models"


def get_latest():
    """弹栈式取最新包, 返回 (bytes, name) 或 None"""
    try:
        req = urllib.request.Request(f"{RELAY}/latest", method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            name = resp.headers.get("X-Filename", f"pkg_{int(time.time())}.bin")
            return data, name
    except Exception as e:
        err = str(e)
        if "no data yet" in err or "404" in err:
            return None
        print(f"⚠️ 拉取异常: {e}")
        return None


def is_binary_model(data):
    """判断是否为模型二进制 (safetensors/npz)"""
    if len(data) < 1000:
        return False
    # safetensors 头部是 JSON + 二进制, npz 是 PK
    head = data[:8]
    if head[:2] == b"PK" or b"{" in data[:200]:
        return True
    return False


def deploy_to_orin(local_path, remote_name):
    """SCP 到 Orin 并运行验证"""
    remote = f"{ORIN_MODEL_DIR}/{remote_name}"
    print(f"📤 上传到 Orin: {remote}")
    subprocess.run(["scp", local_path, f"{ORIN}:{remote}"], check=False, timeout=120)
    print("🔬 Orin 端部署验证...")
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", ORIN,
         f"timeout 120 python3 ~/.zmax/hw_deploy_verify.py --model {remote} --frames 10"],
        capture_output=True, text=True, timeout=150)
    print(r.stdout[-2000:])
    if r.returncode != 0:
        print("⚠️ 验证失败:", r.stderr[-500:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只拉一次")
    ap.add_argument("--interval", type=int, default=10, help="轮询间隔秒")
    args = ap.parse_args()

    print("=== Simulink CI · 自动部署 (MAC) ===")
    print(f"轮询: {RELAY}/latest")

    seen = set()
    while True:
        pkg = get_latest()
        if pkg:
            data, name = pkg
            print(f"📦 收到包: {name} ({len(data)/1048576:.1f}MB)")
            if is_binary_model(data):
                local = f"/tmp/deploy_{int(time.time())}.safetensors"
                with open(local, "wb") as f:
                    f.write(data)
                print(f"✅ 模型已保存: {local}")
                deploy_to_orin(local, os.path.basename(name).replace(".npz", ".safetensors"))
            else:
                print(f"ℹ️ 元数据包(跳过部署): {data[:200]}")
            if args.once:
                break
        else:
            if args.once:
                print("⏳ 无数据")
                break
            sys.stdout.write(".")
            sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
