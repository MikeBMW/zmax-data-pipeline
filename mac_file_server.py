#!/usr/bin/env python3
"""Mac 文件接收服务 · 工控机→Mac 直传 (无 cgi 依赖, py3.13兼容)
工控机: curl -F "file=@xxx.zip" http://192.168.23.1:9000/upload
保存到 ~/zmax_uploads/
"""
import http.server
import json
import os
import re
import time

SAVE_DIR = os.path.expanduser("~/zmax_uploads")
os.makedirs(SAVE_DIR, exist_ok=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if not self.path.startswith("/upload"):
            self._send(404, {"ok": False, "error": "unknown"})
            return
        try:
            ctype = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            fname = f"upload_{int(time.time())}.bin"
            data = body
            if "multipart/form-data" in ctype:
                # 解析 multipart: 提取文件名和内容
                boundary = ctype.split("boundary=")[-1].strip().strip('"').encode()
                parts = body.split(b"--" + boundary)
                for part in parts:
                    if b"filename=" in part:
                        # 文件名
                        m = re.search(rb'filename="([^"]*)"', part)
                        if m:
                            fname = m.group(1).decode("utf-8", "ignore") or fname
                        # 内容 (空行后)
                        idx = part.find(b"\r\n\r\n")
                        if idx >= 0:
                            data = part[idx + 4:].rstrip(b"\r\n")
                        break

            fp = os.path.join(SAVE_DIR, os.path.basename(fname))
            with open(fp, "wb") as f:
                f.write(data)
            self._send(200, {"ok": True, "saved": os.path.basename(fname),
                             "size": len(data), "dir": SAVE_DIR})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def do_GET(self):
        if self.path.startswith("/files"):
            files = sorted(os.listdir(SAVE_DIR))[-20:]
            self._send(200, {"ok": True, "files": files})
        elif self.path.startswith("/health"):
            self._send(200, {"ok": True, "dir": SAVE_DIR})
        else:
            self._send(404, {"ok": False})

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"🚀 Mac 文件接收 @ http://192.168.23.1:9000  → {SAVE_DIR}")
    http.server.ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
