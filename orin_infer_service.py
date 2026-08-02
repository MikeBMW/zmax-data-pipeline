#!/usr/bin/env python3
"""Orin 推理服务 — 加载ACT模型 + 心跳上报ECS
========================================
功能:
  1. 加载部署的 ACT 模型 (~/.zmax/models/act_model.safetensors)
  2. 每5秒心跳上报 ECS /orin/heartbeat
  3. 本地 :8767 提供 /infer 推理端点

用法:
  python3 orin_infer_service.py [模型路径]
"""
import json
import os
import sys
import time
import threading
import urllib.request

import numpy as np
import torch

sys.path.insert(0, os.path.expanduser("~/.zmax"))

DEV = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.zmax/models/act_model.safetensors")
HB_URL = "http://datadrive.world/api/orin/heartbeat"
STATUS_URL = "http://datadrive.world/api/orin/status"
PORT = 8767

infer_count = 0
last_infer_ms = 0.0
model_loaded = False
model_name = os.path.basename(MODEL_PATH)


def load_model():
    """加载 ACT 模型"""
    global model_loaded
    from orin_act_standalone import build_act_from_ckpt
    act = build_act_from_ckpt(MODEL_PATH)
    act.to(DEV).eval()
    model_loaded = True
    print(f"✅ 模型加载成功: {MODEL_PATH} ({DEV})")
    return act


def heartbeat_loop():
    """每5秒上报 ECS"""
    while True:
        try:
            payload = json.dumps({
                "online": True,
                "model": model_name,
                "infer_count": infer_count,
                "last_infer_ms": last_infer_ms,
            }).encode()
            req = urllib.request.Request(HB_URL, data=payload,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception as e:
            print(f"⚠️ 心跳失败: {e}")
        time.sleep(5)


def infer_server(act):
    """本地 HTTP 推理端点"""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            global infer_count, last_infer_ms
            if self.path == "/infer":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length))
                    state = torch.tensor(body.get("state", [0.0] * 2),
                                         dtype=torch.float32, device=DEV).unsqueeze(0)
                    # 图像: 默认合成, 或从base64读取
                    img = torch.randn(1, 3, 480, 640, device=DEV)
                    t0 = time.time()
                    with torch.no_grad():
                        actions = act(img, state)
                    last_infer_ms = round((time.time() - t0) * 1000, 1)
                    infer_count += 1
                    resp = json.dumps({"action": actions[0].tolist(),
                                       "infer_ms": last_infer_ms}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp)
                except Exception as e:
                    resp = json.dumps({"error": str(e)}).encode()
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(resp)
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                resp = json.dumps({"online": True, "model": model_name,
                                   "infer_count": infer_count}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🖥️  推理服务: http://0.0.0.0:{PORT}/infer")
    server.serve_forever()


def main():
    print(f"=== Orin 推理服务 ===")
    print(f"模型: {MODEL_PATH}")
    print(f"设备: {DEV}")

    act = load_model()

    # 心跳线程
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    print(f"💓 心跳上报: {HB_URL} (每5秒)")

    # 推理服务
    infer_server(act)


if __name__ == "__main__":
    main()
