#!/usr/bin/env python3
"""Mac 用户级 HTTP/HTTPS 转发代理 (免sudo) · 防连接轰炸版
工控机设置代理 http://192.168.23.1:9100 即可上网

v2 改进:
  - 连接数上限 (防工控机疯狂建连耗尽线程)
  - 空闲超时 (防连接挂死)
  - 全局连接计数 + 拒绝策略
"""
import http.server
import socket
import ssl
import threading
import time
import urllib.parse

# 防轰炸配置
MAX_CONNECTIONS = 60        # 最大并发连接 (超过拒绝)
IDLE_TIMEOUT = 30           # 空闲超时秒数 (超时断开)
_conn_count = 0
_conn_lock = threading.Lock()


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _enter(self) -> bool:
        """尝试占用连接名额, 满了返回 False"""
        global _conn_count
        with _conn_lock:
            if _conn_count >= MAX_CONNECTIONS:
                return False
            _conn_count += 1
            return True

    def _exit(self):
        global _conn_count
        with _conn_lock:
            if _conn_count > 0:
                _conn_count -= 1

    def setup(self):
        # 连接进入前检查名额
        if not self._enter():
            try:
                self.connection.close()
            except Exception:
                pass
            raise ConnectionError("too many connections")
        super().setup()
        # 空闲超时
        self.connection.settimeout(IDLE_TIMEOUT)

    def finish(self):
        try:
            super().finish()
        except Exception:
            pass
        finally:
            self._exit()

    def _pipe(self, src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    def do_CONNECT(self):
        # HTTPS CONNECT 隧道
        host, _, port = self.path.partition(":")
        port = int(port or 443)
        try:
            remote = socket.create_connection((host, port), timeout=15)
            self.send_response(200, "Connection Established")
            self.end_headers()
            t1 = threading.Thread(target=self._pipe, args=(self.connection, remote), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(remote, self.connection), daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=IDLE_TIMEOUT)
            t2.join(timeout=IDLE_TIMEOUT)
        except Exception as e:
            try:
                self.send_error(502, f"CONNECT failed: {e}")
            except Exception:
                pass

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_PUT(self):
        self._forward()

    def do_DELETE(self):
        self._forward()

    def _forward(self):
        try:
            url = urllib.parse.urlsplit(self.path)
            host = url.hostname or ""
            port = url.port or (443 if url.scheme == "https" else 80)
            path = url.path or "/"
            if url.query:
                path += "?" + url.query

            remote = socket.create_connection((host, port), timeout=15)
            if url.scheme == "https":
                ctx = ssl.create_default_context()
                remote = ctx.wrap_socket(remote, server_hostname=host)

            body = None
            if self.headers.get("Content-Length"):
                body = self.rfile.read(int(self.headers["Content-Length"]))
            req = f"{self.command} {path} HTTP/1.1\r\n"
            for k, v in self.headers.items():
                if k.lower() not in ("connection", "proxy-connection", "host"):
                    req += f"{k}: {v}\r\n"
            req += f"Host: {host}\r\nConnection: close\r\n\r\n"
            remote.sendall(req.encode())
            if body:
                remote.sendall(body)

            resp = b""
            while True:
                chunk = remote.recv(65536)
                if not chunk:
                    break
                resp += chunk
                if len(resp) > 10_000_000:  # 10MB 上限
                    break
            self.wfile.write(resp)
            remote.close()
        except Exception:
            try:
                self.send_error(502, "proxy error")
            except Exception:
                pass

    def log_message(self, fmt, *args):
        pass  # 静默日志


if __name__ == "__main__":
    print("Mac 代理 v2 (防轰炸) @ :9100, 最大连接 60", flush=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 9100), ProxyHandler)
    server.serve_forever()
