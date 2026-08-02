# -*- coding: utf-8 -*-
"""
Z-MAX AOI 程序升级/诊断脚本 (Windows 工控机运行)
================================================
功能:
  1. 检查 AOI 服务 (10082/10083) 是否在线
  2. 调用 capture_detect 测试检测流程
  3. 备份当前程序目录
  4. 输出诊断报告 (可回传 Mac/Orin 分析)

用法 (工控机 cmd):
  python aoi_diag.py            # 诊断+测试
  python aoi_diag.py backup     # 只备份
  python aoi_diag.py test       # 只测试检测

注意: 需要管理员权限运行 (备份程序目录时)
"""
import datetime
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

# ============ 配置 ============
AOI_HOST = "127.0.0.1"          # 本机
AOI_PORTS = [10082, 10083]      # AOI 服务端口
AOI_ENDPOINT = "capture_detect"  # 检测端点
# AOI 程序目录 (按实际修改)
AOI_DIRS = [
    r"D:\\AOI_program",          # 猜测, 按实际改
    r"C:\\AOI_program",
]
BACKUP_DIR = r"D:\\AOI_backup"  # 备份目录

# ============ 工具函数 ============
def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"[{now()}] {msg}", flush=True)


def check_port(port, timeout=2):
    """检查端口"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((AOI_HOST, port))
        s.close()
        return True
    except Exception:
        return False


def call_aoi(port, endpoint=AOI_ENDPOINT, payload=None, timeout=30):
    """调用 AOI HTTP 接口"""
    url = f"http://{AOI_HOST}:{port}/{endpoint}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except Exception as e:
        return f"ERROR: {e}"


def find_aoi_dir():
    """找 AOI 程序目录"""
    for d in AOI_DIRS:
        if os.path.isdir(d):
            return d
    return None


def backup_aoi(src_dir):
    """备份 AOI 程序"""
    if not src_dir or not os.path.isdir(src_dir):
        log(f"❌ 程序目录不存在: {src_dir}")
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.basename(src_dir.rstrip("\\\\")) or "AOI"
    dst = os.path.join(BACKUP_DIR, f"{name}_{ts}")
    log(f"📦 备份 {src_dir} → {dst}")
    try:
        shutil.copytree(src_dir, dst)
        log(f"✅ 备份完成: {dst}")
        return dst
    except Exception as e:
        log(f"❌ 备份失败: {e}")
        return None


# ============ 主流程 ============
def main():
    log("=== Z-MAX AOI 诊断脚本 ===")
    log(f"系统: {platform_name()}")

    # 1. 端口检查
    log("--- 1. 端口检查 ---")
    for port in AOI_PORTS:
        ok = check_port(port)
        log(f"  {port}: {'✅ 在线' if ok else '❌ 离线'}")

    # 2. 备份
    if "backup" in sys.argv or len(sys.argv) == 1:
        log("--- 2. 备份程序 ---")
        aoi_dir = find_aoi_dir()
        if aoi_dir:
            log(f"  找到目录: {aoi_dir}")
            backup_aoi(aoi_dir)
        else:
            log("  ⚠️ 未找到 AOI 程序目录, 请修改脚本 AOI_DIRS 配置")

    # 3. 检测测试
    if "test" in sys.argv or len(sys.argv) == 1:
        log("--- 3. 检测测试 ---")
        for port in AOI_PORTS:
            if check_port(port):
                log(f"  调用 :{port}/{AOI_ENDPOINT} ...")
                r = call_aoi(port, timeout=30)
                log(f"  响应: {r[:200]}")
                # 保存结果
                result_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"aoi_test_{port}.json")
                with open(result_file, "w", encoding="utf-8") as f:
                    f.write(r)
                log(f"  💾 已保存: {result_file}")

    # 4. 系统信息
    log("--- 4. 系统信息 ---")
    try:
        r = subprocess.run(["systeminfo"], capture_output=True, text=True, timeout=30)
        lines = [l for l in r.stdout.split("\\n") if any(k in l for k in ["OS 名称", "OS 版本", "系统型号", "处理器", "物理内存"])]
        for l in lines[:5]:
            log(f"  {l.strip()}")
    except Exception:
        pass

    log("=== 完成 ===")
    log("请把 aoi_test_*.json 传回 Orin/Mac 分析")


def platform_name():
    try:
        import platform
        return f"{platform.system()} {platform.release()} {platform.machine()}"
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
