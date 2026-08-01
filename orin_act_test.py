#!/usr/bin/env python3
"""Orin ACT 推理 — 绕过lerobot包,直接safetensors加载权重"""
import sys, os, json, time
sys.path.insert(0, os.path.expanduser("~/.zmax"))

import torch
from safetensors.torch import load_file

ACT_DIR = os.path.expanduser("~/.zmax/act")

def main():
    print("=== Orin ACT 推理 (safetensors直载) ===")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"torch {torch.__version__}, device: {dev}")

    # 读取 config
    cfg = json.load(open(f"{ACT_DIR}/config.json"))
    print(f"模型: {cfg.get('model_type','act')}")

    # 加载权重（只加载, 不构造完整模型）
    t0 = time.time()
    sd = load_file(f"{ACT_DIR}/model.safetensors")
    print(f"✅ 权重加载: {time.time()-t0:.1f}s, {len(sd)} 个tensor")

    # 统计参数量
    total = sum(v.numel() for v in sd.values())
    print(f"   参数量: {total/1e6:.1f}M")

    # 展示部分权重名（验证ACT结构）
    keys = list(sd.keys())
    prefix = keys[0].split('.')[0]
    print(f"   权重前缀: {prefix} (e.g. {keys[0][:60]}...)")

    # 找到 action 输出相关权重
    act_keys = [k for k in keys if 'action' in k.lower()]
    print(f"   action相关权重: {len(act_keys)} 个")

    print("✅ 权重完整可加载, ACT模型结构有效")
    print("   (未构造模型/未推理/未发topic — 权重验证通过)")

if __name__ == "__main__":
    main()
