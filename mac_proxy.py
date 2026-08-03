#!/usr/bin/env python3
"""Mac 用户级 HTTP/HTTPS 转发代理 (免sudo)
工控机设置代理 http://192.168.23.1:9100 即可上网
"""
import http.server
import socket
import ssl
import threading
import urllib.parse


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_PUT(self):
        self._forward()

    def do_DELETE(self):
        self._forward()

    def do_CONNECT(self):
        # HTTPS CONNECT 隧道
        host, _, port = self.path.partition(":")
        port = int(port or 443)
        try:
            remote = socket.create_connection((host, port), timeout=15)
            self.send_response(200, "Connection Established")
            self.end_headers()
            # 双向转发
            t1 = threading.Thread(target=self._pipe, args=(self.connection, remote), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(remote, self.connection), daemon=True)
            t1.start()
            t2.start()
            t1.join()
        except Exception as e:
            self.send_error(502, f"CONNECT failed: {e}")

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

            # 转发请求
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

            # 读响应
            resp = b""
            while True:
                chunk = remote.recv(65536)
                if not chunk:
                    break
                resp += chunk
            self.send_response(200)
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            remote.close()
        except Exception as e:
            try:
                self.send_error(502, f"forward failed: {e}")
            except Exception:
                pass

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("🌐 Mac 转发代理 @ http://192.168.23.1:9100 (工控机设此代理即可上网)")
    http.server.ThreadingHTTPServer(("0.0.0.0", 9100), ProxyHandler).serve_forever()
