#!/usr/bin/env python3
"""Orin 相机直读 + ACT 推理
用 pyrealsense2 直接打开相机取帧, 不依赖ROS2
"""
import os, sys, time
sys.path.insert(0, os.path.expanduser("~/.zmax"))

import numpy as np
import torch
import pyrealsense2 as rs

from orin_act_standalone import build_act_from_ckpt

DEV = "cuda" if torch.cuda.is_available() else "cpu"


def get_frame(ctx, serial, w=640, h=480):
    """打开指定 RealSense 相机取一帧"""
    pipe = rs.pipeline()
    cfg = rs.config()
    cfg.enable_device(serial)
    cfg.enable_stream(rs.stream.color, w, h, rs.format.rgb8, 30)
    pipe.start(cfg)
    try:
        # 跳过前几帧稳定
        for _ in range(10):
            pipe.wait_for_frames()
        frames = pipe.wait_for_frames()
        color = frames.get_color_frame()
        if not color:
            return None
        return np.asanyarray(color.get_data())
    finally:
        pipe.stop()


def main():
    print("=== Orin 相机直读 → ACT 推理 ===")
    print(f"device: {DEV}")

    # 1. 加载 ACT
    t0 = time.time()
    act = build_act_from_ckpt()
    act.to(DEV).eval()
    print(f"✅ ACT 加载: {time.time()-t0:.1f}s")

    # 2. 查找相机
    ctx = rs.context()
    devices = ctx.query_devices()
    print(f"✅ 检测到 {len(devices)} 台 RealSense 相机")
    serials = []
    for i, dev in enumerate(devices):
        serial = dev.get_info(rs.camera_info.serial_number)
        name = dev.get_info(rs.camera_info.name)
        print(f"   [{i}] {name} serial={serial}")
        serials.append(serial)

    if not serials:
        print("❌ 无相机")
        return

    # 3. 取帧
    img = None
    for s in serials:
        try:
            print(f"📷 取帧 {s}...")
            img = get_frame(ctx, s)
            if img is not None:
                print(f"✅ 图像: {img.shape}")
                break
        except Exception as e:
            print(f"  {s} 失败: {e}")
    if img is None:
        print("❌ 所有相机取帧失败")
        return

    # 4. 预处理
    from PIL import Image as PILImage
    img_pil = PILImage.fromarray(img)
    img_resized = img_pil.resize((480, 640))
    img_arr = np.array(img_resized, dtype=np.float32) / 255.0
    img_tensor = torch.from_numpy(img_arr).permute(2, 0, 1).unsqueeze(0).to(DEV)

    # 关节状态: 无ROS数据, 用中性位姿 (0.5 弧度占位)
    state_14 = np.zeros(14, dtype=np.float32)
    state_tensor = torch.from_numpy(state_14).unsqueeze(0).to(DEV)

    # 5. 推理
    t0 = time.time()
    with torch.no_grad():
        actions = act(img_tensor, state_tensor)
    dt = (time.time() - t0) * 1000

    # 6. 报告
    acts = actions[0].cpu().numpy()
    print("\n══════════ ACT 推理报告 ══════════")
    print(f"输入图像: {img.shape} → resize (480,640)")
    print(f"推理耗时: {dt:.1f}ms")
    print(f"输出: {tuple(actions.shape)} (100步 × 14维)")
    print(f"动作块样本 (前5步 J1-J6):")
    for i in range(5):
        j = i * 20
        print(f"  step {j:3d}: " + " ".join(f"{a:+.3f}" for a in acts[j, :6]))
    print(f"J1-J6范围: min={acts[:, :6].min():.3f}, max={acts[:, :6].max():.3f}")

    # 7. 保存图像
    os.makedirs("~/.zmax/captures".replace("~", os.path.expanduser("~")), exist_ok=True)
    save_path = os.path.expanduser("~/Desktop/camera_frame.png")
    try:
        img_pil.save(save_path)
        print(f"\n📸 图像已保存: {save_path}")
    except Exception as e:
        print(f"  保存失败: {e}")
    print("✅ 推理完成 — 仅读取相机, 未发送任何动作")


if __name__ == "__main__":
    main()
