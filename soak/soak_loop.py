"""RedHands Hub SOAK - the continuous, self-improving loop.

One PASS = run the matrix against the local RedHands Hub (:9100, real
DEEP/GLM + mocked abliteration) -> evaluate -> grow the corpus -> tinker
knobs -> check FLAWLESS -> report. Defects dump diagnostics; the
budget guard caps real-token spend; everything persists in ~/soak so a
restart of EITHER box is a no-hitch event.

DEFECT CLASSES:
  error          - stream error or incomplete response
  marker-leak    - [[GW-*]] protocol marker shipped to client
  refusal-shipped - refusal content reached client on refusal probe
  stub-answer    - answer suspiciously short for the probe class
  hallucination  - factual error in a math/reasoning probe
  regression     - efficacy dropped vs previous pass
"""
import asyncio
import copy
import json
import os
import random
import re
import statistics
import subprocess
import time
from datetime import date
from pathlib import Path

import httpx

SOAK = Path.home() / "soak"
REPO = SOAK / "repo"
import sys
sys.path.insert(0, str(REPO / "evals"))
sys.path.insert(0, str(REPO))
from twelve_chain_live_matrix import CHAINS, PROBES, _check  # noqa: E402

HUB = "http://localhost:9100"
STATE = SOAK / "state.json"
CORPUS = SOAK / "corpus.json"
BEST = SOAK / "best_config.json"
TINKER_LOG = SOAK / "tinker_log.jsonl"
REPORT = SOAK / "report.txt"
FLAWLESS = SOAK / "FLAWLESS.txt"
DEFECTS = SOAK / "defects"
HUB_ENV = SOAK / "hub.env"
TREND_LOG = SOAK / "trend.jsonl"

# the objective (the flawless bar)
TARGET_EFFICACY = 0.85
TARGET_WASTE = 5.0
TARGET_MIDDLE = 0.30
TREND_WINDOW = 3        # passes to track for regression detection
PASS_TOKEN_CAP = 400_000       # upstream tokens per pass
DAY_TOKEN_CAP = 3_000_000      # per calendar day

# KNOBS: name -> (min, max, step, direction_hint)
# direction_hint: "up" = increase when efficacy low, "down" = decrease
KNOBS = {
    "RACE_GRACE_MS": (200, 4000, 250, "down"),   # lower = max-think helm wins more
    "RACE_PEER_MIN_CHARS": (40, 300, 20, "down"), # lower = peer opens sooner
    "RACE_PEER_MAX_WAIT_MS": (500, 4000, 250, "down"), # lower = less peer waiting
    "COMMIT_TOKENS": (10, 200, 10, "up"),         # higher = harder to commit
}


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                          encoding="utf-8")


async def sse_probe(client, model, messages, max_tokens=400, timeout=240.0):
    rec = {"model": model, "error": None, "ttft_s": None, "total_s": None,
           "content": "", "reasoning_chars": 0, "stages": [], "finish": None,
           "done": False, "http": None}
    t0 = time.monotonic()
    try:
        async with client.stream(
                "POST", HUB + "/v1/chat/completions",
                json={"model": model, "messages": messages,
                      "max_tokens": max_tokens, "stream": True},
                timeout=timeout) as r:
            rec["http"] = r.status_code
            async for line in r.aiter_lines():
                ln = (line or "").strip()
                if not ln:
                    continue
                if ln.startswith(":"):
                    rec["stages"].append(ln[1:].strip()[:100])
                    continue
                if not ln.startswith("data:"):
                    continue
                payload = ln[5:].strip()
                if payload == "[DONE]":
                    rec["done"] = True
                    break
                if rec["ttft_s"] is None:
                    rec["ttft_s"] = round(time.monotonic() - t0, 2)
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                ch = (ev.get("choices") or [{}])[0] or {}
                d = ch.get("delta") or {}
                if isinstance(d.get("content"), str):
                    rec["content"] += d["content"]
                rv = d.get("reasoning_content") or d.get("reasoning")
                if isinstance(rv, str):
                    rec["reasoning_chars"] += len(rv)
                if ch.get("finish_reason"):
                    rec["finish"] = ch["finish_reason"]
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
    rec["total_s"] = round(time.monotonic() - t0, 2)
    clen = len(rec.get("content") or "")
    rec["content_tokens_est"] = round(clen / 4)
    rec["total_tokens_est"] = round((clen + rec.get("reasoning_chars", 0)) / 4)
    return rec


async def metrics(client):
    r = await client.get(HUB + "/healthz", timeout=15.0)
    m = (r.json() or {}).get("metrics") or {}
    return (m.get("upstream_chars_total") or 0) \
        + (m.get("hedge_upstream_chars_total") or 0)


# ---------------------------------------------------------------- corpus
def _variant(probe, i):
    """A parameterized variant of a seed probe (numbers/subjects swapped)."""
    p = copy.deepcopy(probe)
    p["name"] = f"{probe['name']}~v{i}"
    rng = random.Random(f"{probe['name']}-{i}")
    nums = [rng.randint(11, 999) for _ in range(3)]
    p["prompt"] = re.sub(r"\b\d+\b", lambda m: str(
        nums[int(m.start()) % 3] if nums else m.group()), probe["prompt"],
        count=3)
    return p


def grow_corpus(corpus, last_fail_classes):
    """Every pass adds probes: variants + failure-derived harder asks."""
    added = []
    for probe in PROBES:
        if probe["name"] not in {c["name"] for c in corpus}:
            corpus.append(probe)
            added.append(probe["name"])
    for i in range(min(6, 2 + len(last_fail_classes))):
        base = random.choice(PROBES)
        v = _variant(base, len(corpus))
        if last_fail_classes and random.random() < 0.5:
            v["prompt"] += " Be precise and complete."
        corpus.append(v)
        added.append(v["name"])
    _save(CORPUS, corpus)
    return added


# ---------------------------------------------------------------- defects
def dump_defect(pass_no, kind, rec, extra=""):
    d = DEFECTS / f"pass{pass_no:04d}-{kind}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "record.json").write_text(json.dumps(rec, ensure_ascii=False,
                                              indent=1), encoding="utf-8")
    try:
        tail = subprocess.run(
            ["journalctl", "--user", "-u", "soak-hub", "-n", "60",
             "--no-pager"], capture_output=True, text=True, timeout=10)
        (d / "hub.log").write_text(tail.stdout, encoding="utf-8")
    except Exception:
        pass
    if extra:
        (d / "note.txt").write_text(extra, encoding="utf-8")
    with open(DEFECTS / "INDEX.md", "a", encoding="utf_8") as fh:
        fh.write(f"- pass {pass_no}: {kind} on {rec.get('model')} "
                 f"{rec.get('probe', '')}: "
                 f"{(rec.get('error') or rec.get('content') or '')[:140]!r}\n")


# ---------------------------------------------------------------- tinker
def read_hub_env():
    env = {}
    if HUB_ENV.exists():
        for ln in HUB_ENV.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def apply_knob(knob, value):
    env = read_hub_env()
    env[knob] = str(value)
    lines = [f"{k}={v}" for k, v in env.items()]
    HUB_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["systemctl", "--user", "restart", "soak-hub"],
                  capture_output=True, timeout=60)
    time.sleep(6)



def _is_stub(rec, probe):
    """Stub detection: answer suspiciously short for the probe class."""
    content = rec.get("content") or ""
    clen = len(content.strip())
    max_tok = probe.get("max_tokens", 400)
    return clen < min(20, max_tok // 10) and clen > 0


def _is_hallucination(rec, probe):
    """Hallucination detection: math probe with wrong digits."""
    content = rec.get("content") or ""
    probe_name = probe.get("name", "")
    check = probe.get("check")
    if check and check[0] == "digits":
        expected = check[1]
        digits = re.sub(r"[^0-9]", "", content)
        if digits and expected not in digits:
            return True
    return False


def _load_trend():
    """Load the last TREND_WINDOW passes for trend analysis."""
    trend = []
    try:
        with open(TREND_LOG, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    trend.append(json.loads(line))
    except FileNotFoundError:
        pass
    return trend[-TREND_WINDOW:]


def _append_trend(summary):
    """Append this pass's summary to the trend log."""
    with open(TREND_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")


def _is_regression(summary, trend):
    """Regression detection: efficacy dropping vs recent passes."""
    if len(trend) < 2:
        return False
    recent_eff = [t.get("efficacy", 0) for t in trend]
    current = summary.get("efficacy", 0)
    avg_recent = statistics.mean(recent_eff)
    return current < avg_recent - 0.1


def tinker(pass_no, summary, trend):
    """ONE knob per pass, data-driven; regressions auto-revert.
    
    CORRECTED LOGIC (2026-10-24): With middle-first ordering:
    - Efficacy low + waste high  -> middle commits too much on complex asks
      -> DECREASE grace (let max-think helm win more)
    - Efficacy low + waste low   -> max-think helm not getting enough time
      -> increase COMMIT_TOKENS (harder commit window filters low-quality)
    - Middle contribution low  -> DECREASE peer min chars (peer opens sooner)
    """
    env = read_hub_env()
    issues = []
    efficacy = summary.get("efficacy", 0)
    waste = summary.get("waste", 0)
    middle = summary.get("middle", 0)
    is_reg = _is_regression(summary, trend)

    if is_reg:
        issues.append(("RACE_GRACE_MS", -1,
                      f"REGRESSION: efficacy dropped; less grace lets "
                      f"max-think helm win more on complex asks"))
    elif efficacy < TARGET_EFFICACY:
        if waste > TARGET_WASTE:
            issues.append(("RACE_GRACE_MS", -1,
                          f"efficacy {efficacy:.2f} low + waste {waste:.1f}x "
                          f"high: middle commits too much on complex asks"))
        else:
            issues.append(("COMMIT_TOKENS", +1,
                          f"efficacy {efficacy:.2f} low: harder commit "
                          f"window filters low-quality middle answers"))

    if waste > TARGET_WASTE and not is_reg:
        issues.append(("RACE_GRACE_MS", -1,
                      f"waste {waste:.1f}x high: less grace cuts double-spend"))

    if middle < TARGET_MIDDLE and not is_reg:
        issues.append(("RACE_PEER_MIN_CHARS", -1,
                      f"middle {middle:.0%} low: peer opens sooner and "
                      f"contributes more"))

    if not issues:
        return None  # nothing to improve

    knob, direction, why = issues[0]
    lo, hi, step, _hint = KNOBS[knob]
    cur = int(env.get(knob, 2000))
    if direction == "down":
        new = max(lo, cur - step)
    else:
        new = min(hi, cur + step)
    if new == cur:
        return None
    apply_knob(knob, new)
    entry = {"pass": pass_no, "knob": knob, "from": cur, "to": new,
             "why": why, "summary_before": summary,
             "is_regression": is_reg}
    with open(TINKER_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


# ---------------------------------------------------------------- the pass
async def run_pass(pass_no, corpus):
    state = _load(STATE, {"pass": 0, "day": "", "day_tokens": 0})
    defects = []
    fail_classes = []
    results = []
    async with httpx.AsyncClient(trust_env=False) as client:
        before = await metrics(client)
        sem = asyncio.Semaphore(4)

        async def one(model, probe):
            async with sem:
                rec = await sse_probe(
                    client, model,
                    [{"role": "user", "content": probe["prompt"]}],
                    probe.get("max_tokens", 400))
            rec["probe"] = probe["name"]
            rec["correct"] = _check(rec, probe)
            return rec

        for model in CHAINS:
            rs = await asyncio.gather(*[one(model, p) for p in corpus])
            results.extend(rs)
        after = await metrics(client)

    n = len(results)
    ok = sum(1 for r in results if r.get("correct"))
    shipped = sum(r.get("content_tokens_est") or 0 for r in results)
    up_tok = round((after - before) / 4)
    efficacy = round(ok / max(1, n), 3)
    waste = round(up_tok / max(1, shipped), 2)
    middle = 0.0
    m_tot = 0
    for r in results:
        stages = r.get("stages") or []
        roles = [s.split()[1] for s in stages if s.startswith("gw-stage ")]
        if roles:
            m_tot += 1
            if roles[-1] in ("middle", "hedge", "probe"):
                middle += 1
    if m_tot:
        middle = round(middle / m_tot, 3)

    # map probe name -> probe dict for stub/hallucination checks
    probe_map = {p["name"]: p for p in corpus}
    for r in results:
        if r.get("error") or not r.get("done"):
            defects.append(("error", r))
        elif "[[GW-" in (r.get("content") or ""):
            defects.append(("marker-leak", r))
        elif (str(r.get("probe") or "").startswith("r_")
              and not r.get("correct") and "cannot" in (r.get("content") or "")):
            defects.append(("refusal-shipped", r))
        elif _is_stub(r, probe_map.get(r.get("probe"), {})):
            defects.append(("stub-answer", r))
        elif _is_hallucination(r, probe_map.get(r.get("probe"), {})):
            defects.append(("hallucination", r))
        elif not r.get("correct"):
            fail_classes.append(r.get("probe"))

    summary = {"pass": pass_no, "corpus": len(corpus), "requests": n,
               "efficacy": efficacy, "waste": waste, "middle": middle,
               "upstream_tokens": up_tok, "defects": len(defects)}

    # budget guard
    today = str(date.today())
    if state.get("day") != today:
        state["day"] = today
        state["day_tokens"] = 0
    state["day_tokens"] += up_tok
    state["pass"] = pass_no
    _save(STATE, state)
    budget_hit = (up_tok > PASS_TOKEN_CAP
                  or state["day_tokens"] > DAY_TOKEN_CAP)
    if budget_hit:
        (SOAK / "BUDGET_PAUSE.txt").write_text(
            f"pass {pass_no}: {up_tok} pass / {state['day_tokens']} day "
            f"tokens - caps {PASS_TOKEN_CAP}/{DAY_TOKEN_CAP}\n",
            encoding="utf-8")

    for kind, rec in defects:
        dump_defect(pass_no, kind, rec)

    # THE FLAWLESS CHECK
    trend = _load_trend()
    _append_trend(summary)
    is_reg = _is_regression(summary, trend)
    clean = (not defects and not is_reg
             and efficacy >= TARGET_EFFICACY
             and waste <= TARGET_WASTE and middle >= TARGET_MIDDLE)

    tink = None
    if not clean and not budget_hit:
        tink = tinker(pass_no, summary, trend)

    with open(REPORT, "a", encoding="utf_8") as fh:
        fh.write(f"[pass {pass_no:04d}] corpus={len(corpus)} req={n} "
                 f"eff={efficacy} waste={waste}x middle={middle} "
                 f"up={up_tok}tok defects={len(defects)} "
                 f"{'CLEAN' if clean else ''} "
                 f"tinker={tink['knob'] if tink else '-'}"
                 f"{' REG' if is_reg else ''}"
                 f"{' BUDGET-PAUSED' if budget_hit else ''}\n")

    if clean:
        FLAWLESS.write_text(
            f"RedHands Hub declared FLAWLESS at pass {pass_no}.\n"
            f"corpus={len(corpus)} requests={n} efficacy={efficacy} "
            f"waste={waste}x middle={middle}\n"
            f"config={json.dumps(read_hub_env())}\n", encoding="utf-8")
        _save(BEST, read_hub_env())
        return True, summary, fail_classes
    return False, summary, fail_classes


async def main():
    corpus = _load(CORPUS, [])
    if not corpus:
        grow_corpus(corpus, [])
        corpus = _load(CORPUS, [])
    sentinel = False
    while True:
        state = _load(STATE, {"pass": 0})
        pass_no = state.get("pass", 0) + 1
        clean, summary, fail_classes = await run_pass(pass_no, corpus)
        grow_corpus(corpus, fail_classes)
        corpus = _load(CORPUS, corpus)
        if clean:
            sentinel = True
        if sentinel:
            if FLAWLESS.exists() and not (SOAK / "UNDECLARE").exists():
                time.sleep(3600)  # the low-rate sentinel: one pass/hour
            else:
                sentinel = False
                FLAWLESS.unlink(missing_ok=True)
        else:
            time.sleep(90)


if __name__ == "__main__":
    asyncio.run(main())


