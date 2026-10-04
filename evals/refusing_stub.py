"""refusing_stub.py - a fake upstream that lets us test the divert path deterministically.

The gateway's whole job is: primary refuses / times out / errors -> the specialist
answers instead. Cloud models only *sometimes* refuse an authorized-lab prompt
(measured: the hub's cloud aliases mostly comply), so the divert path cannot be
exercised reliably against a real primary. This stub makes it deterministic.

    python refusing_stub.py 9100 refuse     # SSE opening with a refusal (Tier 3)
    python refusing_stub.py 9100 clean      # SSE with a normal answer
    python refusing_stub.py 9100 timeout    # accept, then never answer (Tier 1)
    python refusing_stub.py 9100 500        # HTTP 500 (Tier 1 retry_then_divert)

Modes can also be switched per request with ?mode=... so one process can serve a
mixed matrix. Every response carries a stable stream id (the gateway adopts it).
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 9100
DEFAULT_MODE = sys.argv[2] if len(sys.argv) > 2 else "refuse"
REFUSAL = "I cannot help with that. I'm not able to assist with this request."
ANSWER = "Here is the lab walkthrough you asked for: step one is enumeration."


def sse(obj):
    return f"data: {json.dumps(obj)}\n\n".encode()


def chunk(text, finish=None, model="refusing-stub"):
    return {
        "id": "stub-stream-1",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": ({"content": text} if text else {}),
                     "finish_reason": finish}],
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the run output clean
        pass

    def _mode(self):
        query = parse_qs(urlparse(self.path).query)
        return (query.get("mode") or [DEFAULT_MODE])[0]

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "refusing-stub"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        mode = self._mode()
        if mode == "timeout":
            time.sleep(900)  # the gateway's read timeout decides this one
            return
        if mode == "500":
            body = b'{"error":{"message":"injected upstream failure","type":"server_error"}}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        text = REFUSAL if mode == "refuse" else ANSWER
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(payload):
            self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
            self.wfile.flush()

        write(sse(chunk("")))
        # stream the opening in a few pieces, like a real model
        for piece in text.split(" "):
            write(sse(chunk(piece + " ")))
        write(sse(chunk("", finish="stop")))
        # NOTE: must go through write() - a raw wfile.write here corrupts the
        # chunked framing and hangs the client (found live: 1 fallback error +
        # a stalled harness at 16-way concurrency).
        write(b"data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


if __name__ == "__main__":
    print(f"refusing_stub on 127.0.0.1:{PORT} mode={DEFAULT_MODE} "
          f"(override per request with ?mode=refuse|clean|timeout|500)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
