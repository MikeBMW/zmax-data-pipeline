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

    # 真实 TCP 位姿 (从 Orin 读, 或手动传入)
    if len(sys.argv) > 3:
        state = [float(x) for x in sys.argv[1:4]]
    else:
        state = [0.6639, -0.0293, 0.2935]  # 默认: 当前真实位姿

    print(f"\n📡 真实 TCP 位姿: {[round(x,4) for x in state]}")
    st = torch.tensor([state], dtype=torch.float32, device=dev)
    img = torch.randn(1, 3, 480, 640, device=dev)

    with torch.no_grad():
        t0 = time.time()
        action = act(img, st)
        dt = (time.time() - t0) * 1000

    a = action[0].cpu().numpy()  # (chunk, 4)
    print(f"⏱️  推理耗时: {dt:.1f}ms")
    print(f"🎯 输出 action 形状: {a.shape}")
    print(f"   动作块 (前3步):")
    for i in range(min(3, a.shape[0])):
        print(f"     step{i}: dx={a[i][0]:+.4f} dy={a[i][1]:+.4f} dz={a[i][2]:+.4f} grip={a[i][3]:+.4f}")

    # 对比: 输入位姿 vs 预测末端增量
    print(f"\n📊 对比:")
    print(f"   当前位姿: ({state[0]:.4f}, {state[1]:.4f}, {state[2]:.4f})")
    print(f"   预测增量: (dx={a[0][0]:+.4f}, dy={a[0][1]:+.4f}, dz={a[0][2]:+.4f})")
    print(f"   预测新位姿: ({state[0]+a[0][0]:.4f}, {state[1]+a[0][1]:.4f}, {state[2]+a[0][2]:.4f})")

    # 保存结果供 ECS 上报
    report = {
        "event": "real_infer",
        "model": "act_cartesian",
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
