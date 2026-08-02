#!/usr/bin/env python3
"""Z-MAX 模型对比评测 · Orin端
================================
基线ACT vs 新训练ACT 对比: 用相同模拟输入, 评测推理性能/动作质量

指标:
  - 推理延迟 (ms)
  - 动作平滑度 (相邻帧差分均值)
  - 动作范围合理性
  - 一致性 (多次推理方差)

用法 (Orin):
  python3 model_compare.py
输出:
  /tmp/model_compare.json — 上传ECS供控制台显示
"""
import json
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.expanduser("~/.zmax"))

DEV = "cuda" if torch.cuda.is_available() else "cpu"
BASE_MODEL = os.path.expanduser("~/.zmax/act/model.safetensors")
NEW_MODEL = os.path.expanduser("~/.zmax/models/act_model.safetensors")
N_FRAMES = 30


def load(path):
    from orin_act_standalone import build_act_from_ckpt
    act = build_act_from_ckpt(path)
    act.to(DEV).eval()
    return act


def eval_model(act, name, n_frames=N_FRAMES):
    """评测单模型"""
    # 推断输入维度
    state_dim = act.encoder_robot_state_input_proj.weight.shape[1]
    out_dim = act.action_head.weight.shape[0]

    latencies = []
    actions_list = []
    # 正弦轨迹输入 (模拟任务)
    t = np.linspace(0, 4 * np.pi, n_frames)
    for i in range(n_frames):
        state = torch.tensor([np.sin(t[i]), np.cos(t[i])][:state_dim],
                             dtype=torch.float32, device=DEV).unsqueeze(0)
        # 补零到 state_dim
        if state.shape[1] < state_dim:
            pad = torch.zeros(1, state_dim - state.shape[1], device=DEV)
            state = torch.cat([state, pad], dim=1)
        img = torch.randn(1, 3, 480, 640, device=DEV)

        t0 = time.time()
        with torch.no_grad():
            actions = act(img, state)
        latencies.append((time.time() - t0) * 1000)
        actions_list.append(actions[0].cpu().numpy())

    acts = np.stack(actions_list)  # (N, chunk, out)
    # 指标
    lat = np.array(latencies)
    # 平滑度: 相邻帧首动作差分
    first_actions = acts[:, 0, :]  # (N, out)
    smoothness = np.mean(np.abs(np.diff(first_actions, axis=0)))
    # 范围
    amin, amax = float(acts.min()), float(acts.max())
    # 一致性: 同输入多次推理的方差
    with torch.no_grad():
        reps = [act(img, state).cpu().numpy() for _ in range(5)]
    consistency = float(np.std(np.stack(reps)))

    return {
        "model": name,
        "state_dim": state_dim,
        "out_dim": out_dim,
        "params_M": round(sum(p.numel() for p in act.parameters()) / 1e6, 1),
        "avg_latency_ms": round(float(lat.mean()), 1),
        "smoothness": round(float(smoothness), 4),
        "action_min": round(amin, 3),
        "action_max": round(amax, 3),
        "consistency_std": round(consistency, 4),
    }


def main():
    print("=== Z-MAX 模型对比评测 ===")
    print(f"device: {DEV}")

    base = eval_model(load(BASE_MODEL), "baseline_aloha")
    print(f"✅ 基线: {base['params_M']}M, {base['avg_latency_ms']}ms")
    new = eval_model(load(NEW_MODEL), "act_metaworld_v1")
    print(f"✅ 新模型: {new['params_M']}M, {new['avg_latency_ms']}ms")

    # 对比结论
    conclusion = {}
    if base["out_dim"] == new["out_dim"]:
        conclusion = {
            "latency_improve_pct": round((base["avg_latency_ms"] - new["avg_latency_ms"]) / base["avg_latency_ms"] * 100, 1),
            "smoothness_improve_pct": round((base["smoothness"] - new["smoothness"]) / max(base["smoothness"], 1e-6) * 100, 1),
            "verdict": "IMPROVED" if new["avg_latency_ms"] < base["avg_latency_ms"] else "NEEDS_IMPROVEMENT",
        }
    else:
        conclusion = {
            "note": f"维度不同无法直接对比 (基线{base['out_dim']}D vs 新{new['out_dim']}D)",
            "verdict": "DIMENSION_MISMATCH",
        }

    report = {
        "event": "model_compare",
        "source": "orin",
        "time": time.time(),
        "baseline": base,
        "new_model": new,
        "conclusion": conclusion,
    }

    out = "/tmp/model_compare.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print("\n═══ 对比报告 ═══")
    print(json.dumps(report, indent=2))

    # 上传 ECS 供控制台显示
    import urllib.request
    data = json.dumps(report).encode()
    req = urllib.request.Request("http://datadrive.world/api/relay/upload", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"\n📤 已上传ECS: {resp.read().decode()[:100]}")
    except Exception as e:
        print(f"\n⚠️ 上传失败: {e}")


if __name__ == "__main__":
    main()
