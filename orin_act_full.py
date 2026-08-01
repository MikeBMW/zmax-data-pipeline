#!/usr/bin/env python3
"""Orin ACT 完整推理测试 — 加载模型+推理, 不发任何topic"""
import sys, os, time
sys.path.insert(0, os.path.expanduser("~/.zmax"))

import torch
from lerobot.policies.act.modeling_act import ACTPolicy

def main():
    print("=== Orin ACT 完整推理 ===")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"torch {torch.__version__}, device: {dev}")
    if dev == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    # 加载 checkpoint（本地, 不联网）
    t0 = time.time()
    policy = ACTPolicy.from_pretrained(
        "lerobot/act_aloha_sim_transfer_cube_human",
        local_files_only=True,
        cache_dir=os.path.expanduser("~/.zmax/act"),
    )
    policy.eval()
    policy.to(dev)
    print(f"✅ checkpoint 加载: {time.time()-t0:.1f}s")
    print(f"   参数量: {sum(p.numel() for p in policy.parameters())/1e6:.1f}M")

    # 随机输入推理（安全, 不发topic）
    batch = {
        "observation.state": torch.randn(1, 14, device=dev),
        "observation.images.top": torch.randn(1, 3, 480, 640, device=dev),
    }

    # 预热
    with torch.no_grad():
        _ = policy.select_action(batch)

    # 计时推理
    times = []
    for _ in range(5):
        t0 = time.time()
        with torch.no_grad():
            action = policy.select_action(batch)
        times.append(time.time() - t0)

    print(f"✅ 推理成功! action shape = {tuple(action.shape)}")
    print(f"   平均耗时: {sum(times)/len(times)*1000:.1f}ms")
    print(f"   动作样本: {[round(x,4) for x in action[0,:3].tolist()]}")
    print("✅ 完成, 未发送任何topic")

if __name__ == "__main__":
    main()
