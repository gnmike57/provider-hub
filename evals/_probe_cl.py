"""Throwaway probe: does TestClient send content-length: 0 for empty POSTs?

Recorded experiment (kept as-is; 2026-10-21 run on this stack):
    no-body: {'cl': '0'}
    empty-bytes: {'cl': '0'}
    json: {'cl': '7'}
    raw-cl0: {'cl': '0'}
The asserted regression twin lives in evals/cl_test.py.
"""
import sys
sys.path.insert(0, ".")
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

app = FastAPI()


@app.post("/echo")
async def echo(request: Request):
    return {"cl": request.headers.get("content-length")}


c = TestClient(app)
print("no-body:", c.post("/echo").json())
print("empty-bytes:", c.post("/echo", content=b"").json())
print("json:", c.post("/echo", json={"a": 1}).json())
print("raw-cl0:", c.post("/echo", headers={"content-length": "0"}).json())
