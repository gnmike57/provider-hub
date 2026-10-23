"""Latency benchmark for every hub key (masked output, read-only).

Same key surface as key_audit.py (pool + env + router envs + registry), but
measures PERFORMANCE instead of validity: per key, one warmup + N timed
minimal chat calls, round-robin interleaved across keys so provider-side load
noise spreads evenly (a sequential per-key run would blame whichever key
happened to run during a busy minute). Each key uses one keep-alive
httpx.Client, so TLS setup is amortized and the numbers reflect steady-state
serving per key.

Per-sample rows append to evals/results/key_bench.jsonl (crash-proof).
Final table: per-key min/median/mean/max over SUCCESSFUL samples + success
rate, grouped by provider surface, with an EQUALITY verdict per group
(keys whose median drifts > 1.5x from the group median, or any failure,
are flagged OUTLIER).

Usage: python evals/key_bench.py [samples]   (default 5)
"""

import json
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import key_audit as ka  # reuse collect/mask/classify/surface map

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals" / "results" / "key_bench.jsonl"

PROMPT = "Reply with the single word: PONG"
BODIES = {
    "hive": {"model": ka.HIVE_MODEL, "messages": [{"role": "user",
                                                  "content": PROMPT}],
             "max_tokens": 16, "stream": False},
    "ablit": {"model": ka.AB_MODEL, "messages": [{"role": "user",
                                                  "content": PROMPT}],
              "max_tokens": 16, "stream": False},
    "ablit-admin": {"model": ka.AB_MODEL, "messages": [{"role": "user",
                                                        "content": PROMPT}],
                    "max_tokens": 16, "stream": False},
}
URLS = {"hive": ka.HIVE_URL, "ablit": ka.AB_URL, "ablit-admin": ka.AB_URL}


def sync_env_from_user_scope():
    """OVERWRITE process env with the persisted User-scope values.

    key_audit.refresh_env_from_user_scope only fills MISSING names; a shell
    that inherited pre-refit values would shadow the healthy ones. This
    benchmark must measure the real persisted surface, so env wins from HKCU:
    set when present, popped when absent."""
    try:
        import winreg
    except ImportError:
        return
    for name in ("ABLITERATION_API_KEY", "ABLITERATION_ADMIN_KEY",
                 "HIVE_SECRET_KEY", "HIVE_ACCESS_KEY", "ADMIN_API_KEY"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                val, _ = winreg.QueryValueEx(k, name)
            os.environ[name] = val
        except FileNotFoundError:
            os.environ.pop(name, None)
        except OSError:
            continue


def surface_for(item) -> str:
    """Audit-surface with label-based fallback (router env rows carry the
    provider in the VAR NAME, not the origin/hint)."""
    s = ka.hint_to_surface(item["hint"], item["origin"])
    if s:
        return s
    label = (item["label"] or "").lower()
    if "ablit" in label:
        return "ablit"
    if "hive" in label:
        return "hive"
    if "nano" in label or "cat_" in label:
        return "nano"
    return "unknown"

_FLOCK = threading.Lock()  # serializes jsonl appends from worker threads


def _cw(w, label, surface, key, masked, url, body, deadline, results):
    """One concurrent worker: fire minimal requests until the window closes.

    Own keep-alive client (independent connection lane). Records per-sample
    rows (masked) to key_bench.jsonl under a lock; in-flight requests that
    started before the deadline are allowed to finish and count."""
    headers = {"Authorization": "Bearer " + key,
               "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as c:
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            status = 0
            tokens = 0
            try:
                r = c.post(url, json=body, headers=headers)
                dt = time.monotonic() - t0
                status = r.status_code
                verdict = ka.classify(status, r.text)
                if verdict == "OK":
                    try:
                        tokens = int((r.json().get("usage") or {})
                                     .get("completion_tokens") or 0)
                    except Exception:
                        tokens = 0
            except Exception as exc:
                dt = time.monotonic() - t0
                verdict = "ERROR:" + type(exc).__name__
            row = {"ts": datetime.now(timezone.utc).isoformat(),
                   "mode": "concurrent", "worker": w, "label": label,
                   "surface": surface, "masked": masked,
                   "seconds": round(dt, 3), "verdict": verdict,
                   "http": status, "tokens": tokens}
            results.append(row)
            with _FLOCK, open(OUT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_concurrent(workers=4, window=15.0):
    """Sustained-throughput benchmark: per key, N workers for a fixed window.

    Keys are benched one at a time (each key's workers hammer only it), so
    every measurement is uncontaminated by the other keys. Only chat-rotation
    keys are benched (hive + ablit); admin/local keys are skipped."""
    sync_env_from_user_scope()
    everything = ka.collect()
    items = [i for i in everything if surface_for(i) in ("hive", "ablit")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"key_bench[concurrent]: {len(items)} keys, {workers} workers x "
          f"{window:.0f}s window each (one key at a time)")
    stats = []
    for it in items:
        surface = surface_for(it)
        url = URLS[surface]
        body = dict(BODIES[surface])
        masked = ka.mask(it["key"])
        deadline = time.monotonic() + window
        results = []
        threads = []
        for w in range(workers):
            t = threading.Thread(target=_cw,
                                 args=(w, it["label"], surface, it["key"],
                                       masked, url, body, deadline, results),
                                 daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(window + 90)
        oks = [r for r in results if r["verdict"] == "OK"]
        lat = sorted(r["seconds"] for r in oks)
        toks = sum(r["tokens"] for r in oks)
        fails = {}
        for r in results:
            if r["verdict"] != "OK":
                fails[r["verdict"]] = fails.get(r["verdict"], 0) + 1

        def pct(p):
            return lat[min(len(lat) - 1, int(len(lat) * p))] if lat else 0.0

        row = {"label": it["label"], "surface": surface, "masked": masked,
               "workers": workers, "window": window,
               "n_total": len(results), "n_ok": len(oks),
               "req_s": round(len(oks) / window, 2),
               "tok_s": round(toks / window, 1),
               "p50": round(pct(0.50), 2), "p95": round(pct(0.95), 2),
               "fails": fails}
        stats.append(row)
        print(f"  {row['label']:<24} {surface:<7} {row['n_ok']:>4}/{row['n_total']:<4}"
              f" {row['req_s']:>5.2f} r/s  {row['tok_s']:>6.1f} tok/s"
              f"  p50={row['p50']:.2f}s p95={row['p95']:.2f}s"
              f"  fails={fails if fails else '-'}")

    print("\n" + "=" * 86)
    print(f"{'KEY':<24}{'SURFACE':<9}{'REQ/S':>7}{'TOK/S':>8}"
          f"{'P50':>7}{'P95':>7}{'FAILS':>8}  VERDICT")
    print("=" * 86)
    groups = {}
    for r in stats:
        groups.setdefault(r["surface"], []).append(r)
    for surface, rows in sorted(groups.items()):
        best = max(r["req_s"] for r in rows) or 1.0
        for r in sorted(rows, key=lambda x: -x["req_s"]):
            rate_limited = any(k == "RATE" for k in r["fails"])
            if r["req_s"] < 0.6 * best or rate_limited:
                verdict = "THROTTLED/SLOW"
            else:
                verdict = "equal"
            fl = sum(r["fails"].values())
            print(f"{r['label']:<24}{r['surface']:<9}{r['req_s']:>7.2f}"
                  f"{r['tok_s']:>8.1f}{r['p50']:>7.2f}{r['p95']:>7.2f}"
                  f"{fl:>8}  {verdict}")
        total = sum(r["req_s"] for r in rows)
        print(f"  [{surface}] pool aggregate: {total:.2f} req/s over "
              f"{len(rows)} keys (best single key {best:.2f} req/s)")
    print(f"\nrecord: {OUT}")
    return 0


def main() -> int:
    samples = 5
    mode = "latency"
    workers = 4
    window = 15.0
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif a == "--workers" and i + 1 < len(args):
            workers = max(1, min(32, int(args[i + 1])))
            i += 2
        elif a == "--seconds" and i + 1 < len(args):
            window = max(5.0, min(120.0, float(args[i + 1])))
            i += 2
        else:
            try:
                samples = max(1, min(20, int(a)))
            except ValueError:
                pass
            i += 1
    if mode == "concurrent":
        return run_concurrent(workers, window)
    sync_env_from_user_scope()
    everything = ka.collect()
    items = [i for i in everything if surface_for(i) not in ("local",
                                                             "unknown")]
    # unknown-surface keys are not benchable fairly (no provider URL known)
    skipped = [i for i in everything if surface_for(i) in ("local",
                                                            "unknown")]
    keys = []
    for it in items:
        surface = surface_for(it)
        keys.append({"label": it["label"], "surface": surface,
                     "key": it["key"], "masked": ka.mask(it["key"]),
                     "lat": [], "fails": 0})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    rounds = 1 + samples  # 1 warmup + N timed
    print(f"key_bench: {len(keys)} keys x {samples} timed samples "
          f"(+1 warmup each), round-robin interleaved, keep-alive clients")
    for sk in skipped:
        print(f"  skipped: {sk['label']} (surface "
              f"{surface_for(sk) or 'unknown'})")
    clients = {k["label"]: httpx.Client(timeout=40.0) for k in keys}
    try:
        for rnd in range(rounds):
            warm = rnd == 0
            for k in keys:
                body = dict(BODIES[k["surface"]])
                t0 = time.monotonic()
                status = 0
                try:
                    r = clients[k["label"]].post(
                        URLS[k["surface"]], json=body,
                        headers={"Authorization": "Bearer " + k["key"],
                                 "Content-Type": "application/json"})
                    dt = time.monotonic() - t0
                    status = r.status_code
                    verdict = ka.classify(r.status_code, r.text)
                except Exception as exc:
                    dt = time.monotonic() - t0
                    verdict = "ERROR:" + type(exc).__name__
                if warm:
                    continue
                row = {"ts": ts, "round": rnd, "label": k["label"],
                       "surface": k["surface"], "masked": k["masked"],
                       "seconds": round(dt, 3), "verdict": verdict,
                       "http": status}
                with open(OUT, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                if verdict == "OK":
                    k["lat"].append(dt)
                else:
                    k["fails"] += 1
                print(f"  r{rnd} {k['label']:<24} {k['surface']:<11} "
                      f"{dt:5.2f}s {verdict}")
    finally:
        for c in clients.values():
            c.close()

    # ---- summary + equality verdict per provider group ---------------
    groups = {}
    for k in keys:
        groups.setdefault(k["surface"], []).append(k)
    print("\n" + "=" * 78)
    print(f"{'KEY':<24}{'SURFACE':<12}{'OK':>4}{'FAIL':>5}"
          f"{'MIN':>7}{'MED':>7}{'MEAN':>7}{'MAX':>7}  VERDICT")
    print("=" * 78)
    for surface, gks in sorted(groups.items()):
        ok_lat = [x for k in gks for x in k["lat"]]
        gmed = statistics.median(ok_lat) if ok_lat else float("nan")
        for k in sorted(gks, key=lambda x: statistics.median(x["lat"])
                       if x["lat"] else 9e9):
            n_ok = len(k["lat"])
            if n_ok:
                mn = min(k["lat"])
                md = statistics.median(k["lat"])
                mean = statistics.mean(k["lat"])
                mx = max(k["lat"])
                ratio = md / gmed if gmed else float("nan")
                if k["fails"] or ratio > 1.5 or ratio < 0.67:
                    verdict = "OUTLIER"
                else:
                    verdict = "equal"
                print(f"{k['label']:<24}{k['surface']:<12}{n_ok:>4}"
                      f"{k['fails']:>5}{mn:>6.2f}{md:>7.2f}{mean:>7.2f}"
                      f"{mx:>7.2f}  {verdict}"
                      f"{' (' + format(ratio, '.2f') + 'x grp)' if n_ok else ''}")
            else:
                print(f"{k['label']:<24}{k['surface']:<12}{0:>4}"
                      f"{k['fails']:>5}{'-':>7}{'-':>7}{'-':>7}{'-':>7}  DEAD")
        if ok_lat:
            spread = (max(ok_lat) - min(ok_lat)) / gmed
            print(f"  [{surface}] group median {gmed:.2f}s, "
                  f"full spread {spread:.0%} of median, "
                  f"{len(gks)} keys, {len(ok_lat)} ok samples")
    print(f"\nrecord: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

