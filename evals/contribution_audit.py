"""(2026-10-23) CONTRIBUTION AUDIT: which hop actually answers, per chain,
across the final 336-request matrix. The operator's question: are the
DEEP/GLM parts wasted while the specialist is over-used?"""
import io
import json
import re

rows = [json.loads(l) for l in io.open(
    "evals/results/twelve_chain_matrix.jsonl", encoding="utf-8")]
print(f"rows: {len(rows)}")

TAKEOVER = re.compile(
    r"(abliterated|deepseek|glm)[a-z ]*taking over", re.I)
PROBE_FOOT = "pre-probe answered"


def answerer(rec):
    """The hop whose stage is LAST (the one whose answer shipped), plus any
    takeover footnote found in the content."""
    stages = rec.get("stages") or []
    last = None
    for s in stages:
        # gw-stage <role> <model> / gw-hop <role> ...
        if s.startswith("gw-stage "):
            last = s.split()[2] if len(s.split()) > 2 else None
    role = None
    for s in stages:
        if s.startswith("gw-stage "):
            role = s.split()[1] if len(s.split()) > 1 else None
    return role, last


per_chain = {}
for r in rows:
    m = r["model"]
    role, model = answerer(r)
    foot = TAKEOVER.findall(r.get("content") or "")
    probe_hit = PROBE_FOOT in (r.get("content") or "")
    d = per_chain.setdefault(m, {"helm": 0, "middle": 0, "probe": 0,
                                 "terminal": 0, "?": 0,
                                 "takeover": {}, "probe_hit": 0, "n": 0})
    d["n"] += 1
    if probe_hit:
        d["probe_hit"] += 1
    key = "probe" if (probe_hit and role != "terminal") else (role or "?")
    d[key if key in d else "?"] = d.get(key if key in d else "?", 0) + 1
    for who in foot:
        w = who.lower()
        d["takeover"][w[:9]] = d["takeover"].get(w[:9], 0) + 1

print("\n=== WHO ANSWERED (by stage role) + takeover footnotes ===")
for m, d in per_chain.items():
    tot = d["n"]
    print(f"\n{m}  (n={tot})")
    for k in ("probe", "helm", "middle", "terminal", "?"):
        if d.get(k):
            pct = round(100 * d[k] / tot)
            print(f"    {k:9s} {d[k]:3d}  ({pct}%)")
    if d["takeover"]:
        print(f"    footnotes: {d['takeover']}")

# also: which probe classes drive the specialist
print("\n=== specialist(terminal)-answered records by probe ===")
from collections import Counter
spec = Counter()
helm_only = Counter()
for r in rows:
    role, _ = answerer(r)
    p = (r.get("probe") or "").split("#")[0]
    if role == "terminal":
        spec[p] += 1
    elif role == "helm":
        helm_only[p] += 1
print("terminal-answered probes:", dict(spec))
print("helm-answered probes:", dict(helm_only))
