"""The tap: a logging reverse-proxy between your agent and its LLM API.

First principles: every harness mechanism (system prompts, config files, hooks, injected
context, tool schemas) COMPILES into one artifact — the request sent to the model endpoint.
The tap records that artifact so "did my harness change actually reach the model?" is an
observable fact, not a guess.

Zero dependencies: stdlib http.server + http.client, streaming (SSE) passthrough.

Point your agent at it (any client honoring a base-URL env var works):
    ANTHROPIC_BASE_URL=http://127.0.0.1:8082   # or OPENAI_BASE_URL, etc.

Hard-won correctness notes (each was a production incident for us):
  * Relay EVERY HTTP method. Our first version lacked do_HEAD; the client's startup
    HEAD probe got 501, it marked the API unreachable, and its plugin system never
    attached — the agent went silently deaf. (README: Gotcha #1)
  * Log the RESPONSE STATUS per request — diagnosing anything without it is guesswork.
  * Logging failures must never break proxying; bind loopback only (auth headers transit).
"""
from __future__ import annotations
import gzip
import hashlib
import json
import ssl
import time
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import config as _config

_SKIP_REQ = {"host", "connection", "keep-alive", "transfer-encoding", "content-length",
             "accept-encoding"}
_SKIP_RESP = {"connection", "keep-alive", "transfer-encoding", "content-length",
              "content-encoding"}


def make_handler(cfg: dict):
    up = urlsplit(cfg["upstream"])
    data_dir = Path(cfg["data_dir"])
    log_path = data_dir / "tap-log.jsonl"
    bodies = data_dir / "bodies"
    capture_prefixes = tuple(cfg["capture_paths"])

    class Tap(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _upstream_conn(self):
            if up.scheme == "https":
                return http.client.HTTPSConnection(up.netloc, timeout=600,
                                                   context=ssl.create_default_context())
            return http.client.HTTPConnection(up.netloc, timeout=600)

        def _relay(self, method: str):
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""

            rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "method": method,
                   "path": self.path, "req_bytes": len(body)}
            if method == "POST" and self.path.startswith(capture_prefixes) and body:
                try:
                    d = json.loads(body)
                    sha = hashlib.sha256(body).hexdigest()[:8]
                    bid = f"{int(time.time()*1000)}-{sha}"
                    with gzip.open(bodies / f"{bid}.json.gz", "wb") as f:
                        f.write(body)
                    rec.update({"model": d.get("model"), "n_messages": len(d.get("messages", [])),
                                "n_tools": len(d.get("tools", []) or []),
                                "body_file": f"bodies/{bid}.json.gz"})
                except Exception as e:
                    rec["capture_error"] = str(e)[:120]

            fwd = {k: v for k, v in self.headers.items() if k.lower() not in _SKIP_REQ}
            fwd["Host"] = up.netloc
            sent = 0
            try:
                conn = self._upstream_conn()
                conn.request(method, self.path, body=body or None, headers=fwd)
                r = conn.getresponse()
                rec["status"] = r.status
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in _SKIP_RESP:
                        self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    chunk = r.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    sent += len(chunk)
                rec["resp_bytes"] = sent
                conn.close()
            except Exception as e:
                rec["relay_error"] = f"{type(e).__name__}: {e}"[:200]
                rec["resp_bytes"] = sent
                try:
                    self.send_response(502)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(b'{"error":"harness-loop tap upstream failure"}')
                except Exception:
                    pass
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass

        # relay EVERY method (Gotcha #1: a missing method = 501 = agent thinks API is down)
        def do_GET(self):        self._relay("GET")
        def do_POST(self):       self._relay("POST")
        def do_PUT(self):        self._relay("PUT")
        def do_DELETE(self):     self._relay("DELETE")
        def do_PATCH(self):      self._relay("PATCH")
        def do_HEAD(self):       self._relay("HEAD")
        def do_OPTIONS(self):    self._relay("OPTIONS")

    return Tap


def rotate(cfg: dict):
    bodies = sorted(Path(cfg["data_dir"], "bodies").glob("*.json.gz"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    for p in bodies[cfg.get("max_bodies", 500):]:
        p.unlink(missing_ok=True)


def main(cfg: dict | None = None):
    cfg = cfg or _config.load()
    host, port = cfg["bind"].rsplit(":", 1)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[tap] WARNING: binding {host} — the tap forwards auth headers; "
              f"loopback-only is strongly recommended.")
    rotate(cfg)
    srv = ThreadingHTTPServer((host, int(port)), make_handler(cfg))
    print(f"[tap] listening on {cfg['bind']} -> {cfg['upstream']}")
    print(f"[tap] captures: {cfg['data_dir']}/tap-log.jsonl + bodies/")
    srv.serve_forever()
