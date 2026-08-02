#!/usr/bin/env python3
"""自动检测 relay 新模型 → 拉取 → 部署 Orin → 重启推理
静静推模型后自动完成闭环, 无需人工
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

RELAY = "http://datadrive.world/api/relay"
MODEL_LOCAL = "/tmp/auto_model.bin"
ORIN_MODEL = "/home/tashan/.zmax/models/act_model.safetensors"
ORIN = "tashan@192.168.23.66"

seen = set()


def relay_status():
    with urllib.request.urlopen(f"{RELAY}/status", timeout=8) as r:
        return json.loads(r.read())


def peek():
    try:
        with urllib.request.urlopen(f"{RELAY}/peek", timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None


def deploy_model():
    print("📦 拉取模型...")
    os.system(f'curl -s --max-time 300 "{RELAY}/latest" -o {MODEL_LOCAL}')
    size = os.path.getsize(MODEL_LOCAL) if os.path.exists(MODEL_LOCAL) else 0
    if size < 1_000_000:
        print(f"❌ 包太小 ({size}B), 不是模型")
        return False
    print(f"✅ 模型 {size//1048576}MB")

    # 检查结构
    try:
        from safetensors.torch import load_file
        sd = load_file(MODEL_LOCAL)
        for k in ["model.encoder_robot_state_input_proj.weight", "model.action_head.weight"]:
            if k in sd:
                print(f"  {k}: {list(sd[k].shape)}")
    except Exception as e:
        print(f"⚠️ 结构检查: {e}")

    # 部署 Orin
    print("📤 部署 Orin...")
    os.system(f"scp {MODEL_LOCAL} {ORIN}:{ORIN_MODEL}")
    # 重启推理服务
    os.system(f"""ssh -o ConnectTimeout=15 {ORIN} "ps aux | grep orin_infer | grep -v grep | awk '{{print \\$2}}' | xargs -r kill -9; sleep 2; nohup bash -c 'cd /home/tashan/.zmax && exec python3 orin_infer_service.py --model {ORIN_MODEL}' > /tmp/infer_svc.log 2>&1 &" """)
    time.sleep(8)
    # 验证
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=15", ORIN, "curl -s http://localhost:8766/status"],
                       capture_output=True, text=True, timeout=20)
    print(f"✅ 推理服务: {r.stdout[:120]}")
    return True


def main():
    print("=== 自动部署监听 v2 (30秒轮询) ===")
    while True:
        try:
            pkg = peek()
            if pkg:
                meta = pkg.get("meta", {})
                src = meta.get("source", "?")
                size = meta.get("size") or 0
                name = pkg.get("_peek", {}).get("name", "?")
                # 模型包特征: 任意包, 只要 size 大 或名字带 npz/safetensors
                is_model_name = "npz" in name or "safetensors" in name or "bin" in name
                is_big = size and size > 10_000_000
                # 数据包特征: source=orin + frames 数组
                is_data = src == "orin" and "frames" in pkg
                # meta 包黑名单 (静静上传时附带的 JSON 元数据, size 字段伪装)
                is_meta = "deploy_meta" in name or "meta" in name.lower() and name.endswith(".json")
                if name not in seen and (is_model_name or (is_big and not is_data)) and not is_meta:
                    seen.add(name)
                    print(f"🔍 候选模型包: {name} (size={size}, src={src})", flush=True)
                    deploy_model()
        except Exception as e:
            print(f"⚠️ {e}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
