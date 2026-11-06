#!/usr/bin/env python3
"""Tiny reverse proxy with HTTP Basic Auth in front of FCC.

Listens on $PORT (the host's public port) and forwards to fcc-server on
127.0.0.1:8082. Every request needs Basic Auth (user $PROXY_USER, default
"admin"; password from $PROXY_PASSWORD). FCC itself has no auth, so this
proxy is the only thing standing between the public internet and the
Admin UI. WebSocket upgrades are not proxied (returns 426); the Admin
UI's settings/API calls are plain HTTP and work through this proxy.

Logging: every request and backend step is printed to stdout (flushed),
so the host's log stream shows exactly where a request goes. The backend
timeout is short (15 s) so a stuck backend fails fast with a 502 instead
of hanging the client forever. Responses are streamed in chunks.
Standard library only.
"""
import base64
import http.client
import http.server
import os
import socketserver
import sys
import time

PUBLIC_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8082
BACKEND_TIMEOUT = 15
PROXY_USER = os.environ.get("PROXY_USER", "admin")
PROXY_PASSWORD = os.environ.get("PROXY_PASSWORD", "")

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
}

# Headers the host's edge / the browser adds that would make FCC's
# local-only Admin check fail. FCC allows Admin access only from the
# local machine: it requires a loopback client, a loopback Host header,
# and a loopback (or absent) Origin. The public edge adds X-Forwarded-*
# with the real client IP, and a browser sends Origin: <public URL> —
# both would trip the check even though the proxy itself connects from
# 127.0.0.1. Stripping them makes the forwarded request look local,
# which is correct here: this proxy's Basic Auth is the authentication
# in front of FCC's local-only Admin UI.
STRIP_HEADERS = {
    "origin", "referer",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-forwarded-port", "x-forwarded-by", "forwarded",
}


def log(msg):
    print(f"[proxy {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
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

    def _send(self, status, body, extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, method):
        started = time.time()
        if not self._authed():
            log(f"{method} {self.path} -> 401 (no/invalid auth)")
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="FCC Gateway"')
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "12")
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return
        if self.headers.get("Upgrade", "").lower() == "websocket":
            log(f"{method} {self.path} -> 426 (websocket not proxied)")
            self._send(426, "WebSocket upgrade not supported by this proxy")
            return
        log(f"{method} {self.path} -> authed, forwarding to {BACKEND_HOST}:{BACKEND_PORT}")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in HOP_HEADERS
            and k.lower() not in STRIP_HEADERS
            and k.lower() != "authorization"
        }
        conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=BACKEND_TIMEOUT)
        try:
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            log(f"{method} {self.path} -> backend {resp.status} {resp.reason} ({time.time() - started:.2f}s)")
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_HEADERS:
                    self.send_header(k, v)
            # Stream the body in chunks instead of buffering it all.
            length_hdr = resp.getheader("Content-Length")
            if length_hdr is not None:
                self.send_header("Content-Length", length_hdr)
            self.end_headers()
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                self.wfile.write(chunk)
            log(f"{method} {self.path} -> done, {total} bytes ({time.time() - started:.2f}s)")
        except Exception as exc:
            log(f"{method} {self.path} -> BACKEND ERROR after {time.time() - started:.2f}s: {exc}")
            try:
                self._send(502, f"Backend unavailable: {exc}")
            except Exception:
                pass
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
    log(f"auth proxy listening on 0.0.0.0:{PUBLIC_PORT}, backend {BACKEND_HOST}:{BACKEND_PORT}")
    with socketserver.ThreadingTCPServer(("0.0.0.0", PUBLIC_PORT), Handler) as httpd:
        httpd.daemon_threads = True
        httpd.serve_forever()
