"""MATRIX RUN ORCHESTRATOR (2026-10-22) - executes the max-scope matrix.

Boots an ISOLATED test stack, then runs the cases:
  - matrix_mock_ablit on 127.0.0.1:9400  (simulated ablit credits: every
    abliteration hop - chain terminals, REDHANDS specialists, ladders)
  - proxy_gateway on 127.0.0.1:9100 with PRIMARY = REAL thehive.ai (the
    ONLY real spend in the whole run) and FALLBACK + ablit.ai = the mock

Isolation: SLOT_PERSISTENCE=0 (no boot-restore), AUDIT_LOG/USAGE_FILE/
METRICS_STATE_PATH pointed at evals/loadgen_results/ - the operator's
root state files are untouched. Resume-capable: recorded case ids are
skipped, results append incrementally to cases.jsonl.

Usage:
  python evals/matrix_run.py --smoke            # ~40-case live smoke
  python evals/matrix_run.py                     # the full matrix
  python evals/matrix_run.py --limit 200 --concurrency 8
"""
import argparse
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS_DIR = os.path.join(HERE, "loadgen_results")
HUB = "http://127.0.0.1:9100"
MOCK = "http://127.0.0.1:9400"
HIVE_URL = "https://api-cdn.thehive.ai/api/v3/chat/completions"

REFUSAL_RE = re.compile(
    r"i can'?t help|i cannot help|unable to comply|i'?m sorry, but|"
    r"i won'?t be able to help|falls outside", re.IGNORECASE)
CODE_ISH = ("def ", "class ", "```", "SELECT ", "function ", "import ",
            "for ", "return ", "async ", "const ", "func ")


def log(msg):
    print(f"[matrix {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _hive_key():
    """One real hive key from the local vault (the account pool still
    rotates all of them per request; this seeds the env fallback)."""
    with io.open(os.path.join(ROOT, "account_pool.json"),
                 encoding="utf-8") as fh:
        pool = json.load(fh)
    for acct in pool.get("accounts", []):
        if acct.get("provider") == "hive":
            return acct["key"]
    raise SystemExit("no hive account in account_pool.json")


def hub_env():
    e = dict(os.environ)
    e.update({
        "PRIMARY_API_URL": HIVE_URL,
        "PRIMARY_API_KEY": _hive_key(),
        "PRIMARY_MODEL": "deepseek-ai/deepseek-v4.1-flash-1017",
        "FALLBACK_API_URL": MOCK + "/v1/chat/completions",
        "FALLBACK_API_KEY": "ak-mock-simulated",
        "FALLBACK_MODEL": "abliterated-model-large-v2",
        "ABLITERATION_API_URL": MOCK + "/v1/chat/completions",
        "ABLITERATION_API_KEY": "ak-mock-simulated",
        "SLOT_PERSISTENCE": "0",
        "AUDIT_LOG": os.path.join(RESULTS_DIR, "audit.jsonl"),
        "USAGE_FILE": os.path.join(RESULTS_DIR, "usage_events.jsonl"),
        "METRICS_STATE_PATH": os.path.join(RESULTS_DIR, "metrics_state.json"),
        "HIDE_ABLIT_MODELS": "0",
        "PYTHONUNBUFFERED": "1",
    })
    return e


def _wait_http(url, timeout=90.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = httpx.get(url, timeout=3.0)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


class Stack:
    """The mock + test-hub subprocess pair."""

    def __init__(self):
        self.procs = []

    def start(self):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        self.procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "matrix_mock_ablit:app",
             "--host", "127.0.0.1", "--port", "9400", "--log-level",
             "warning"],
            cwd=HERE, env=dict(os.environ, PYTHONUNBUFFERED="1")))
        if not _wait_http(MOCK + "/__stats"):
            raise SystemExit("mock ablit did not come up")
        log("mock ablit up on :9400")
        self.procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "proxy_gateway:app",
             "--host", "127.0.0.1", "--port", "9100", "--log-level",
             "warning"],
            cwd=ROOT, env=hub_env()))
        if not _wait_http(HUB + "/healthz"):
            raise SystemExit("test hub did not come up")
        log("test hub up on :9100 (primary=hive REAL, ablit=SIMULATED)")

    def stop(self):
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=15)
            except Exception:
                p.kill()


def verdict(case, content, raw, status):
    """Deterministic per-case verdict (never raises)."""
    v = {"pass": False, "checks": {}}
    try:
        exp = case.get("expect") or {}
        text = (content or "").strip()
        v["checks"]["status_200"] = status == 200
        v["checks"]["substantive"] = len(text) >= (
            3 if exp.get("kind") == "marker" else 30)
        v["checks"]["refusal_free"] = not REFUSAL_RE.search(text[:400])
        if exp.get("kind") == "marker":
            v["checks"]["marker"] = exp["marker"].lower() in text.lower()
        elif exp.get("kind") == "coding":
            v["checks"]["coding_shape"] = (
                any(t in text for t in CODE_ISH) or len(text) >= 80)
        elif exp.get("kind") == "terms":
            low = text.lower()
            v["checks"]["term_coverage"] = any(
                t in low for t in exp.get("terms", []))
        if exp.get("tool_mode") == "forced":
            v["checks"]["tool_calls_forwarded"] = '"tool_calls"' in raw
        v["pass"] = all(v["checks"].values())
    except Exception as exc:  # noqa: BLE001
        v["checks"]["verdict_error"] = str(exc)[:120]
    return v


def parse_sse(raw):
    content, stages, hops, finish = [], [], [], None
    for ln in raw.splitlines():
        ln = ln.strip()
        if ln.startswith(": gw-stage "):
            stages.append(ln.split()[2])
        elif ln.startswith(": gw-hop "):
            hops.append(" ".join(ln.split()[2:6]))
        elif ln.startswith("data:"):
            payload = ln[5:].strip()
            if payload in ("", "[DONE]"):
                continue
            try:
                ev = json.loads(payload)
            except Exception:
                continue
            ch = ((ev.get("choices") or [{}])[0] or {})
            d = ch.get("delta") or {}
            if d.get("content"):
                content.append(str(d["content"]))
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    return "".join(content), stages, hops, finish


async def run_case(client, case, sem, out_fh, out_lock):
    async with sem:
        rec = dict(case)
        t0 = time.time()
        try:
            headers = {"Authorization": "Bearer matrix",
                       "X-Conversation-Id": f"matrix-{case['id']}"}
            if case.get("redhands") == "header":
                headers["X-Max-Offense"] = "1"
            body = {"model": case["surface"], "stream": True,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": case["ask"]}]}
            if case.get("tools") in ("auto", "forced"):
                from matrix_scope import TOOLS_DEF
                body["tools"] = TOOLS_DEF
                body["tool_choice"] = (
                    "auto" if case["tools"] == "auto"
                    else {"type": "function",
                          "function": {"name": "matrix_calc"}})
            turns = case.get("turns") or [{"ask": case["ask"],
                                           "expect": case.get("expect")}]
            history = []
            turn_results = []
            for t in turns:
                history.append({"role": "user", "content": t["ask"]})
                body["messages"] = list(history)
                sub = {"ask_head": t["ask"][:60]}
                s0 = time.time()
                ttft_t = None
                chunks = []
                st = None
                async with client.stream(
                        "POST", HUB + "/v1/chat/completions",
                        headers=headers, json=body, timeout=240.0) as r:
                    st = r.status_code
                    async for part in r.aiter_text():
                        if ttft_t is None and "data:" in part:
                            ttft_t = time.time() - s0
                        chunks.append(part)
                raw = "".join(chunks)
                content, stages, hops, finish = parse_sse(raw)
                sub.update({"status": st, "ttft_s": round(ttft_t or -1, 3),
                            "total_s": round(time.time() - s0, 3),
                            "chars": len(content), "stages": stages,
                            "hops": hops[:4], "finish": finish})
                tc = dict(case, expect=t.get("expect"), ask=t["ask"])
                sub["verdict"] = verdict(tc, content, raw, st)
                turn_results.append(sub)
                history.append({"role": "assistant",
                                "content": content[:2000]})
            rec["turns_meta"] = turn_results
            rec["status"] = turn_results[-1]["status"] if turn_results else 0
            rec["ttft_s"] = turn_results[0]["ttft_s"] if turn_results else -1
            rec["total_s"] = round(time.time() - t0, 3)
            rec["verdict"] = (all(t["verdict"]["pass"] for t in turn_results)
                              if turn_results else False)
        except Exception as exc:  # noqa: BLE001
            rec["status"] = 0
            rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
            rec["total_s"] = round(time.time() - t0, 3)
            rec["verdict"] = {"pass": False, "checks": {"exception": True}}
        async with out_lock:
            out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_fh.flush()


def load_done_ids(path):
    done = set()
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    done.add(json.loads(ln).get("id"))
                except Exception:
                    pass
    return done


def _smoke_subset(cases):
    """One case per (surface, bucket, mock, redhands, tools) flavour."""
    seen = set()
    out = []
    for c in cases:
        key = (c["surface"], c["bucket"], c["mock"], c["redhands"],
               c["tools"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:40]


async def main_async(args):
    import matrix_scope
    cases = matrix_scope.generate()
    if args.smoke:
        cases = _smoke_subset(cases)
    if args.limit:
        cases = cases[:args.limit]
    results_path = os.path.join(RESULTS_DIR, "cases.jsonl")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    done = load_done_ids(results_path)
    todo = [c for c in cases if c["id"] not in done]
    log(f"matrix: {len(cases)} cases, {len(done)} done, {len(todo)} to run")
    if not todo:
        log("nothing to do")
        return

    stack = Stack()
    stack.start()
    try:
        httpx.post(MOCK + "/__reset")
        sem = asyncio.Semaphore(args.concurrency)
        lock = asyncio.Lock()
        t0 = time.time()
        n_ok = [0]

        with io.open(results_path, "a", encoding="utf-8") as out:
            async with httpx.AsyncClient(timeout=240.0) as client:

                async def run(c):
                    await run_case(client, c, sem, out, lock)
                    n_ok[0] += 1
                    if n_ok[0] % 25 == 0:
                        rate = n_ok[0] / (time.time() - t0)
                        eta = (len(todo) - n_ok[0]) / max(rate, 0.01) / 60
                        log(f"{n_ok[0]}/{len(todo)} done "
                            f"({rate:.1f}/s, ETA {eta:.0f}m)")

                await asyncio.gather(*[run(c) for c in todo])
        stats = httpx.get(MOCK + "/__stats", timeout=10).json()
        log(f"mock ablit stats: total={stats['total']} "
            f"redhands={stats['redhands_calls']} by={stats['by_behavior']}")
        with io.open(os.path.join(RESULTS_DIR, "mock_stats.json"), "w",
                     encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2)
        log(f"results: {results_path} ({time.time() - t0:.0f}s)")
    finally:
        stack.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log("interrupted - results are resumable")


if __name__ == "__main__":
    main()
