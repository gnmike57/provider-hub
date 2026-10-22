"""ORG-BURST bench: every abliteration key fires CONCURRENTLY (4 workers
each) for a fixed window. If the provider enforces an ORG-level ceiling,
429s/queues appear across ALL keys simultaneously; if the ceiling is
per-key only, aggregate scales ~linearly. Masked output; results appended
to evals/results/key_bench.jsonl."""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

URL = "https://api.abliteration.ai/v1/chat/completions"
MODEL = "abliterated-model-large-v2"
WINDOW = 20.0
WORKERS_PER_KEY = 4
OUT = "evals/results/key_bench.jsonl"


async def worker(key, idx, results):
    async with httpx.AsyncClient(timeout=45.0) as c:
        deadline = time.monotonic() + WINDOW
        while time.monotonic() < deadline:
            try:
                t0 = time.monotonic()
                r = await c.post(URL, headers={"Authorization": "Bearer " + key},
                                 json={"model": MODEL, "stream": False, "max_tokens": 16,
                                       "messages": [{"role": "user",
                                                    "content": "Reply PONG only"}]})
                dt = time.monotonic() - t0
                results.append({"status": r.status_code, "dt": dt})
            except Exception as exc:
                results.append({"status": 0, "dt": 0.0, "err": type(exc).__name__})


async def main():
    import abliteration_keys
    keys = []
    pool_file = Path(__file__).resolve().parents[1] / "abliteration_pool.json"
    if pool_file.exists():
        try:
            data = json.loads(pool_file.read_text(encoding="utf-8"))
            keys = [k.get("value") or k.get("key") for k in (data.get("keys") or [])
                    if isinstance(k, dict) and (k.get("value") or k.get("key"))]
        except Exception:
            keys = []
    if not keys:
        import account_pool as ap  # noqa: F401
        keys = [a["key"] for a in json.loads(
            open("account_pool.json").read())["accounts"]
            if a.get("provider") == "ablit"]
    print(f"org-burst: {len(keys)} keys x {WORKERS_PER_KEY} workers "
          f"x {WINDOW:.0f}s = {len(keys)*WORKERS_PER_KEY} concurrent lanes")
    tasks, results = [], []
    t0 = time.monotonic()
    for k in keys:
        for i in range(WORKERS_PER_KEY):
            tasks.append(asyncio.create_task(worker(k, i, results)))
    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - t0
    ok = [r for r in results if 200 <= r["status"] < 300]
    r429 = [r for r in results if r["status"] == 429]
    r402 = [r for r in results if r["status"] in (402, 405)]
    r401 = [r for r in results if r["status"] in (401, 403)]
    other = [r for r in results if r["status"] not in (0, 200, 429, 402, 405, 401)]
    errs = [r for r in results if r["status"] == 0]
    rps = len(ok) / elapsed
    lat = sorted(r["dt"] for r in ok) if ok else [0]
    p50 = lat[len(lat)//2]
    p95 = lat[int(len(lat)*0.95)] if len(lat) > 1 else lat[-1]
    print(f"\nRESULT: {len(ok)} ok in {elapsed:.1f}s = {rps:.2f} r/s aggregate")
    print(f"  429={len(r429)}  402/405={len(r402)}  401/403={len(r401)}  "
          f"transport={len(errs)}  other={len(other)}")
    print(f"  p50={p50:.2f}s  p95={p95:.2f}s")
    verdict = ("ORG-CEILING SUSPECTED" if len(r429) + len(errs) >= len(results) * 0.3
              else "per-key ceiling only - aggregate scales")
    print(f"  verdict: {verdict}")
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(), "mode": "org-burst",
            "keys": len(keys), "lanes": len(keys) * WORKERS_PER_KEY,
            "window_s": WINDOW, "ok": len(ok), "aggregate_rps": round(rps, 2),
            "http429": len(r429), "http402_405": len(r402), "http401_403": len(r401),
            "transport": len(errs), "p50_s": round(p50, 2), "p95_s": round(p95, 2),
            "verdict": verdict}) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
