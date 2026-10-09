"""Локальный dev-сервер: статика frontend/public + прокси /api на uvicorn:8000, SPA fallback."""
import http.server, urllib.request, os, sys
ROOT = sys.argv[1]; PORT = int(sys.argv[2]); API = "http://127.0.0.1:8000"

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def log_message(self, *a): pass
    def proxy(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        req = urllib.request.Request(API + self.path, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length", "connection"): req.add_header(k, v)
        if body is not None: req.add_header("Content-Length", str(len(body)))
        try:
            with urllib.request.urlopen(req) as r:
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"): self.send_header(k, v)
                data = r.read(); self.end_headers(); self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read(); self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"): self.send_header(k, v)
            self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path.startswith("/api/"): return self.proxy()
        p = self.path.split("?")[0]
        if not os.path.exists(os.path.join(ROOT, p.lstrip("/"))) or p == "/": self.path = "/index.html"
        return super().do_GET()
    do_POST = do_PATCH = do_DELETE = do_PUT = lambda self: self.proxy()

http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
