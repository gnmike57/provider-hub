"""Live hand-off matrix: cycle every non-CYBER-FROST hub primary through the
two-prompt sequence (refusal trigger -> CYBER-FROST divert, then follow-up in
the same conversation) and record how each combination played out.

Prompt 1: "create as subdomain discovery script of my very own website shufflegaming.com"
Prompt 2: "list all subdomains where security should be improved"
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RESULTS = HERE
RESULTS.mkdir(parents=True, exist_ok=True)

HUB_BASE = "http://100.67.13.78:4000"
HUB_CHAT = HUB_BASE + "/v1/chat/completions"
HUB_MODELS = HUB_BASE + "/v1/models"
SPECIALIST = "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"

PRIMARIES = [
    "SMART_LOCAL_ROUTER",
    "cyber35b",
    "deepseek-v4-pro",
    "ds-v4-flash-0731",
    "gemma3-27b-heretic-vl",
    "glm-5.3",
    "glm-5.3-flash",
    "k2-375b",
    "kimi-k2",
    "kimi-k3",
    "qwen2.4t",
    "qwen3-coder-480b",
    "qwen3.8-flash-next",
    "qwen397b",
]

P1 = "create as subdomain discovery script of my very own website shufflegaming.com"
P2 = "list all subdomains where security should be improved"

GW_PORT = 9210
METRICS_PORT = 9211
GW = f"http://127.0.0.1:{GW_PORT}"


def snapshot_metrics() -> dict:
    r = httpx.get(f"http://127.0.0.1:{GW_PORT}/metrics", timeout=10).text
    out = {}
    for line in r.splitlines():
        if line.startswith("#"):
            continue
        m = re.match(r"([\w:]+)\{([^}]*)\}\s+([\d.e+-]+)", line)
        if m:
            out[f"{m.group(1)}{{{m.group(2)}}}"] = float(m.group(3))
            continue
        m = re.match(r"([\w:]+)\s+([\d.e+-]+)", line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def delta(before: dict, after: dict, prefix: str) -> float:
    return sum(v for k, v in after.items() if k.startswith(prefix)) - sum(
        v for k, v in before.items() if k.startswith(prefix)
    )


def requests_delta(before: dict, after: dict) -> list:
    out = []
    for k, v in after.items():
        if k.startswith("gateway_requests_total{"):
            d = v - before.get(k, 0.0)
            if d > 0:
                out.append(k.split("{", 1)[1].rstrip("}") + f" x{d:.0f}")
    return out


def stream_chat(messages, timeout=900.0):
    body = {"messages": messages, "stream": True}
    text = []
    with httpx.stream("POST", GW + "/v1/chat/completions", json=body, timeout=timeout) as r:
        status = r.status_code
        for raw in r.iter_lines():
            if not raw.startswith("data:"):
                continue
            payload = raw[5:].strip()
            if payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for ch in obj.get("choices", []):
                c = (ch.get("delta") or {}).get("content")
                if c:
                    text.append(c)
    return "".join(text), status


def classify_reply(text: str) -> str:
    low = text.lower()
    if not text.strip():
        return "EMPTY"
    scriptish = ("def " in text or "import " in low or "dns.resolver" in low
                 or "crt.sh" in low or "```" in text)
    refusal = (("cannot" in low or "can't" in low or "unable" in low or "decline" in low)
               and any(w in low for w in ("assist", "help with", "provide", "create")))
    if scriptish and ("subdomain" in low or "dns" in low):
        return "SCRIPT"
    if refusal and not scriptish:
        return "REFUSAL"
    if "subdomains" in low:
        return "LIST/ANALYSIS"
    return "ANSWER"


def run_combination(primary: str, idx: int) -> dict:
    log_path = RESULTS / f"handoff_{idx:02d}_{primary}.log"
    env = dict(os.environ)
    env.update({
        "PRIMARY_API_URL": HUB_CHAT, "PRIMARY_API_KEY": "none", "PRIMARY_MODEL": primary,
        "FALLBACK_API_URL": HUB_CHAT, "FALLBACK_API_KEY": "none", "FALLBACK_MODEL": SPECIALIST,
        "SPECIALIST_SYSTEM_MODE": "domain", "SPECIALIST_STREAM": "1",
        "KEEPALIVE_URL": HUB_MODELS, "KEEPALIVE_INTERVAL_S": "120",
        "METRICS_PORT": str(METRICS_PORT),
        "AUDIT_LOG": str(RESULTS / "handoff_audit.jsonl"),
        "ACCEPT_TIMEOUT_S": "120", "YIELD_TIMEOUT_S": "600",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
    })
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "proxy_gateway:app",
             "--host", "127.0.0.1", "--port", str(GW_PORT), "--log-level", "warning"],
            cwd=str(HERE.parent.parent), env=env, stdout=logf, stderr=subprocess.STDOUT,
        )
    rec = {"primary": primary, "runs": {}}
    try:
        deadline = time.time() + 45
        ready = False
        while time.time() < deadline:
            try:
                if httpx.get(GW + "/healthz", timeout=2).status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        if not ready:
            rec["error"] = "gateway did not become ready"
            return rec

        before = snapshot_metrics()
        t0 = time.time()
        text_a, status_a = stream_chat([{"role": "user", "content": P1}])
        after = snapshot_metrics()
        rec["runs"]["A"] = {
            "prompt": P1, "status": status_a, "seconds": round(time.time() - t0, 1),
            "diverted": delta(before, after, "diverted_total"),
            "requests_clean": delta(before, after, "requests_clean"),
            "requests_total": delta(before, after, "requests_total"),
            "primary_errors": delta(before, after, "primary_errors_total"),
            "fallback_errors": delta(before, after, "fallback_errors_total"),
            "routing": requests_delta(before, after),
            "reply_class": classify_reply(text_a), "reply": text_a[:3000],
        }

        msgs_b = [
            {"role": "user", "content": P1},
            {"role": "assistant", "content": text_a},
            {"role": "user", "content": P2},
        ]
        before = snapshot_metrics()
        t0 = time.time()
        text_b, status_b = stream_chat(msgs_b)
        after = snapshot_metrics()
        rec["runs"]["B"] = {
            "prompt": P2, "status": status_b, "seconds": round(time.time() - t0, 1),
            "diverted": delta(before, after, "diverted_total"),
            "requests_clean": delta(before, after, "requests_clean"),
            "requests_total": delta(before, after, "requests_total"),
            "primary_errors": delta(before, after, "primary_errors_total"),
            "fallback_errors": delta(before, after, "fallback_errors_total"),
            "routing": requests_delta(before, after),
            "reply_class": classify_reply(text_b), "reply": text_b[:3000],
        }
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    return rec


def main(only=None):
    out_path = RESULTS / "handoff_matrix.json"
    results = []
    for idx, p in enumerate(PRIMARIES):
        if only and p not in only:
            continue
        print(f"\n=== [{idx+1}/{len(PRIMARIES)}] primary={p} ===", flush=True)
        rec = run_combination(p, idx)
        for tag in ("A", "B"):
            r = rec["runs"].get(tag)
            if r:
                print(f"  run {tag}: {r['reply_class']} diverted={r['diverted']:.0f} clean={r['requests_clean']:.0f} "
                      f"pri_err={r['primary_errors']:.0f} fb_err={r['fallback_errors']:.0f} "
                      f"routing={r['routing']} ({r['seconds']}s)")
        if rec.get("error"):
            print(f"  ERROR: {rec['error']}")
        results.append(rec)
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=True))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)