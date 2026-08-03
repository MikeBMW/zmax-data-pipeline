# -*- coding: utf-8 -*-
"""
Z-MAX AOI 程序收集脚本 (Windows 工控机运行)
============================================
用途: 把 AOI 程序源码/配置打包, 方便小芳阅读分析优化。

操作步骤:
  1. 把本文件 (collect_aoi.py) 通过 U 盘拷到工控机
  2. 双击运行 或 cmd 里执行: python collect_aoi.py
  3. 运行完生成 aoi_source_export.zip (在脚本同目录)
  4. 把 zip 拷回 Mac/发给小芳

注意: 需要 python 环境 (工控机有 python, 因为 10082/10083 是 python 服务)
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

OUT_ZIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aoi_source_export.zip")
TMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_aoi_collect_tmp")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def find_aoi_process():
    """找 AOI 服务进程 (监听 10082/10083 的 python 进程)"""
    found = []
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if ":10082" in line or ":10083" in line:
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    if pid not in [p[0] for p in found]:
                        # 查进程命令
                        r2 = subprocess.run(["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
                                            capture_output=True, text=True, timeout=10)
                        cmd = r2.stdout.strip()
                        found.append((pid, cmd))
    except Exception as e:
        log(f"⚠️ 进程查找失败: {e}")
    return found


def find_python_scripts():
    """搜常见目录的 .py 文件 (AOI 程序)"""
    scripts = []
    search_dirs = [r"C:\\", r"D:\\"]
    for base in search_dirs:
        for root, dirs, files in os.walk(base):
            # 跳过系统目录
            if any(x in root for x in ["Windows", "Program Files", "ProgramData", "$Recycle", "System Volume"]):
                dirs[:] = []
                continue
            for f in files:
                if f.endswith(".py") and ("aoi" in f.lower() or "detect" in f.lower()
                                          or "capture" in f.lower() or "server" in f.lower()):
                    scripts.append(os.path.join(root, f))
            # 限制深度, 避免扫全盘太慢
            if root.count(os.sep) - base.count(os.sep) > 3:
                dirs[:] = []
    return scripts[:50]


def collect():
    log("=== AOI 程序收集 ===")
    os.makedirs(TMP_DIR, exist_ok=True)
    report = {"time": datetime.now().isoformat(), "processes": [], "scripts": [], "files": []}

    # 1. 找进程
    log("1. 查找 AOI 服务进程...")
    procs = find_aoi_process()
    for pid, cmd in procs:
        log(f"   PID {pid}: {cmd[:100]}")
        report["processes"].append({"pid": pid, "cmd": cmd})

    # 2. 找脚本
    log("2. 搜索 AOI Python 脚本...")
    scripts = find_python_scripts()
    for s in scripts:
        log(f"   {s}")
        report["scripts"].append(s)

    # 3. 收集文件到临时目录
    log("3. 复制文件...")
    for s in scripts:
        try:
            rel = s.replace(":", "").replace("\\\\", "/").replace("\\", "/")
            dst = os.path.join(TMP_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(s, dst)
            report["files"].append(s)
        except Exception as e:
            log(f"   ❌ {s}: {e}")

    # 4. 打包 zip
    log("4. 打包 zip...")
    if os.path.exists(OUT_ZIP):
        os.remove(OUT_ZIP)
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(TMP_DIR):
            for f in files:
                fp = os.path.join(root, f)
                zf.write(fp, os.path.relpath(fp, TMP_DIR))
    # 写报告
    with open(os.path.join(TMP_DIR, "_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with zipfile.ZipFile(OUT_ZIP, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(TMP_DIR, "_report.json"), "_report.json")

    # 清理临时目录
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    log(f"✅ 完成! 导出文件: {OUT_ZIP}")
    log(f"   请把这个 zip 拷回 Mac 发给小芳")


if __name__ == "__main__":
    collect()
