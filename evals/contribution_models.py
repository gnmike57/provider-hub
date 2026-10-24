"""(2026-10-23) MODEL-LEVEL contribution: which MODEL answered (the stage
text carries it) - the actual GLM/DEEP/V2 win distribution per chain."""
import io
import json
from collections import Counter

rows = [json.loads(l) for l in io.open(
    "evals/results/twelve_chain_matrix.jsonl", encoding="utf-8")]


def family(model):
    m = (model or "").lower()
    if "glm" in m:
        return "GLM"
    if "deepseek" in m:
        return "DEEP"
    if "abliter" in m:
        return "V2-specialist"
    return (model or "?")[:12]


per = {}
for r in rows:
    m = r["model"]
    stages = r.get("stages") or []
    last_model = None
    for s in stages:
        if s.startswith("gw-stage "):
            parts = s.split()
            last_model = parts[2] if len(parts) > 2 else None
    per.setdefault(m, Counter())["total"] += 1
    # exact model id, shortened for the table
    key = (last_model or "no-stage").split("/")[-1]
    per[m][key] += 1

for m, c in per.items():
    tot = c["total"]
    line = " ".join(f"{k}={v}({round(100 * v / tot)}%)"
                   for k, v in sorted(c.items()) if k != "total")
    print(f"{m:38s} {line}")

