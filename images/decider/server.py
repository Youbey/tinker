import json, os, signal, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Python as a container's main process ignores SIGTERM until a handler exists, so `podman stop` waited 10 s and then killed it
# (exit 137). Install the handler BEFORE the slow model load, so stopping works at any moment.
signal.signal(signal.SIGTERM, lambda *_: os._exit(0))

from decider.infer import Decider

GGUF = os.environ["DECIDER_GGUF"]
d = Decider(GGUF, gguf_options=dict(n_gpu_layers=0, n_threads=int(os.environ.get("THREADS", "4"))))
lock = threading.Lock()   # the model card says: score one prompt per decode


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, default=float).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send(200 if self.path == "/health" else 404, {"status": "ok"})

    def do_POST(self):
        if self.path != "/decide":
            return self._send(404, {})
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with lock:
            out = d.decide(req["text"], req["questions"])
        self._send(200, out)

    def log_message(self, fmt, *a):
        print("[decider]", fmt % a, flush=True)


print("[decider] loaded", GGUF, flush=True)
ThreadingHTTPServer(("0.0.0.0", 8081), H).serve_forever()
