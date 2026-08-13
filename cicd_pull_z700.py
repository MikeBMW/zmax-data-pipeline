#!/usr/bin/env python3
"""Z-MAX Z700 部署包拉取+解包+校验 (Mac 侧)
========================================
静静打包: yolo best.pt + model.pt(left/right) + 状态机yaml + meta.json → z700_<ts>.tar.gz
链路: ECS relay → Mac 拉取 → 解包 ~/zmax_deploy/z700/ → sha256校验 → docker部署准备

用法:
  python3 cicd_pull_z700.py                    # 拉最新包并解包
  python3 cicd_pull_z700.py --verify-only      # 只校验已解包
"""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import urllib.request

ECS = "http://datadrive.world"
DEPLOY_DIR = os.path.expanduser("~/zmax_deploy/z700")
RELAY_PKGS = f"{ECS}/api/relay/packages"


def fetch_latest_z700():
    """从 relay 找 z700 包名"""
    try:
        with urllib.request.urlopen(RELAY_PKGS, timeout=8) as r:
            pkgs = json.load(r)
        if isinstance(pkgs, list):
            z700 = [p for p in pkgs if "z700" in str(p.get("name", "")).lower()]
            if z700:
                return z700[-1]
    except Exception as e:
        print(f"relay 查询失败: {e}")
    return None


def download(url, dest):
    print(f"📥 下载: {url}")
    urllib.request.urlretrieve(url, dest)
    size = os.path.getsize(dest)
    print(f"  ✅ {dest} ({size/1024/1024:.1f}MB)")
    return size


def extract(tar_path):
    os.makedirs(DEPLOY_DIR, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(DEPLOY_DIR)
    print(f"📦 解包完成 → {DEPLOY_DIR}")


def verify():
    """sha256 校验 (meta.json 记录)"""
    meta_path = os.path.join(DEPLOY_DIR, "meta.json")
    if not os.path.exists(meta_path):
        print("⚠️ 无 meta.json")
        return False
    meta = json.load(open(meta_path))
    ok = True
    for name, sha in meta.get("files", {}).items():
        p = os.path.join(DEPLOY_DIR, name)
        if not os.path.exists(p):
            print(f"  ❌ 缺失: {name}")
            ok = False
            continue
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        match = h == sha
        print(f"  {'✅' if match else '❌'} {name} ({os.path.getsize(p)}B)")
        ok = ok and match
    return ok


def main():
    print("=== Z-MAX Z700 部署包拉取 (Mac) ===")
    if "--verify-only" in sys.argv:
        print("校验结果:", "✅ PASS" if verify() else "❌ FAIL")
        return

    pkg = fetch_latest_z700()
    if not pkg:
        print("❌ relay 无 z700 包 (等静静推送)")
        sys.exit(1)

    name = pkg.get("name")
    url = f"{ECS}/api/relay/download/{name}"
    dest = f"/tmp/{name}"
    try:
        download(url, dest)
        if dest.endswith(".tar.gz") or dest.endswith(".tgz"):
            extract(dest)
        print("\n=== 校验 ===")
        print("校验结果:", "✅ PASS" if verify() else "❌ FAIL")
        print(f"\n🎯 部署包就绪: {DEPLOY_DIR}")
        print("下一步: docker 方案 (zmax-std:1.0-infer 容器挂载部署)")
    except Exception as e:
        print(f"❌ 拉取失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
