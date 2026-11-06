#!/usr/bin/env python3
"""Tiny reverse proxy with HTTP Basic Auth in front of FCC.

Listens on $PORT (Replit's public port) and forwards to fcc-server on
127.0.0.1:8082. Every request needs Basic Auth (user $PROXY_USER, default
"admin"; password from $PROXY_PASSWORD). FCC itself has no auth, so this
proxy is the only thing standing between the public internet and the
Admin UI. WebSocket upgrades are not proxied (returns 426); the Admin
UI's settings/API calls are plain HTTP and work through this proxy.
Standard library only.
"""
import base64
import http.client
import http.server
import os
import socketserver

PUBLIC_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8082
PROXY_USER = os.environ.get("PROXY_USER", "admin")
PROXY_PASSWORD = os.environ.get("PROXY_PASSWORD", "")

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the repl log quiet
        pass

    def _authed(self):
        if not PROXY_PASSWORD:
            return False
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", "replace")
        except Exception:
            return False
        user, _, password = decoded.partition(":")
        return user == PROXY_USER and password == PROXY_PASSWORD

    def _deny(self):
        body = b"Unauthorized"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="FCC Gateway"')
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, method):
        if not self._authed():
            self._deny()
            return
        if self.headers.get("Upgrade", "").lower() == "websocket":
            body = b"WebSocket upgrade not supported by this proxy"
            self.send_response(426)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in HOP_HEADERS and k.lower() != "authorization"
        }
        conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=120)
        try:
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_HEADERS:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # backend down
            body = f"Backend unavailable: {exc}".encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            conn.close()

    do_GET = lambda s: s._forward("GET")
    do_POST = lambda s: s._forward("POST")
    do_PUT = lambda s: s._forward("PUT")
    do_PATCH = lambda s: s._forward("PATCH")
    do_DELETE = lambda s: s._forward("DELETE")
    do_HEAD = lambda s: s._forward("HEAD")
    do_OPTIONS = lambda s: s._forward("OPTIONS")


if __name__ == "__main__":
    if not PROXY_PASSWORD:
        raise SystemExit("PROXY_PASSWORD is not set — refusing to run unauthenticated.")
    with socketserver.ThreadingTCPServer(("0.0.0.0", PUBLIC_PORT), Handler) as httpd:
        httpd.daemon_threads = True
        httpd.serve_forever()
