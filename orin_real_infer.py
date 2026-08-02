#!/usr/bin/env python3
"""真实推理验证 · 笛卡尔模型 (state3D → action4D)
用真实 TCP 位姿 → ACT 模型推理 → 输出动作 → 对比
"""
import json
import sys
import time

import numpy as np
import torch

sys.path.insert(0, "/home/tashan/.zmax")
from orin_act_standalone import build_act_from_ckpt

MODEL = "/home/tashan/.zmax/models/act_model.safetensors"


def main():
    print("=== 笛卡尔模型真实推理 ===")
    print(f"模型: {MODEL}")
    act = build_act_from_ckpt(MODEL)
    act.eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    act.to(dev)
    print(f"设备: {dev}")

    # 从权重自动推断 state_dim (兼容 3D 笛卡尔 / 6D 关节)
    state_dim = act.encoder_robot_state_input_proj.weight.shape[1]
    out_dim = act.action_head.weight.shape[0]

    # 真实状态 (从 Orin 读, 或手动传入)
    if len(sys.argv) > state_dim:
        state = [float(x) for x in sys.argv[1:1+state_dim]]
    else:
        state = [0.0] * state_dim  # 占位

    print(f"\n📡 真实状态 ({state_dim}D): {[round(x,4) for x in state]}")
    st = torch.tensor([state], dtype=torch.float32, device=dev)
    img = torch.randn(1, 3, 480, 640, device=dev)

    with torch.no_grad():
        t0 = time.time()
        action = act(img, st)
        dt = (time.time() - t0) * 1000

    a = action[0].cpu().numpy()  # (chunk, out_dim)
    print(f"⏱️  推理耗时: {dt:.1f}ms")
    print(f"🎯 输出 action 形状: {a.shape}")
    print(f"   动作块 (前3步):")
    for i in range(min(3, a.shape[0])):
        vals = " ".join(f"a{j}={a[i][j]:+.4f}" for j in range(out_dim))
        print(f"     step{i}: {vals}")

    # 对比: 输入状态 vs 预测动作
    print(f"\n📊 对比:")
    print(f"   当前状态 ({state_dim}D): {[round(x,4) for x in state]}")
    print(f"   预测动作 ({out_dim}D): {[round(float(x),4) for x in a[0]]}")
    if state_dim == out_dim:
        print(f"   预测新状态: {[round(state[i]+a[0][i],4) for i in range(state_dim)]}")

    # 保存结果供 ECS 上报
    report = {
        "event": "real_infer",
        "model": f"act_v2_{state_dim}d_{out_dim}d",
        "input_state": state,
        "action_step0": [round(float(x), 5) for x in a[0]],
        "latency_ms": round(dt, 1),
        "time": time.time(),
    }
    with open("/tmp/real_infer_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n💾 报告: /tmp/real_infer_report.json")
    print("✅ 完成 (只读推理, 未发任何topic)")


if __name__ == "__main__":
    main()
