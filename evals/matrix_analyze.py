"""MATRIX ANALYZER (2026-10-22) - the max-scope performance data matrix.

Reads evals/loadgen_results/cases.jsonl (+ mock_stats.json) and produces:
  - matrix_data.json : every aggregate, machine-readable
  - matrix_report.md : the human data matrix - per surface x category
    scorecards (pass rate, TTFT/total latency p50/p95, answer size), the
    best-model ranking per category, throughput per load bucket, the
    failure taxonomy, REDHANDS activation coverage, and routing-stage mix.

Usage: python evals/matrix_analyze.py [--results cases.jsonl]
"""
import argparse
import io
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "loadgen_results")


def _pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, int(round(p / 100.0 * (len(vals) - 1)))))
    return round(vals[k], 3)


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def load_rows(path):
    rows = []
    with io.open(path, encoding="utf-8") as fh:
        for ln in fh:
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
    return rows


def _passed(r):
    """The runner records passing verdicts as a bare bool and failures as
    a checks-dict - normalize both."""
    v = r.get("verdict")
    if v is True:
        return True
    if isinstance(v, dict):
        return bool(v.get("pass"))
    return False


def _verdict_dict(r):
    v = r.get("verdict")
    return v if isinstance(v, dict) else {}


def analyze(rows, mock_stats=None):
    out = {"total": len(rows)}
    ok = [r for r in rows if _passed(r)]
    out["passed"] = len(ok)
    out["pass_rate"] = round(len(ok) / len(rows), 4) if rows else None
    out["errors"] = sum(1 for r in rows if r.get("error"))

    cells = defaultdict(list)
    for r in rows:
        cells[(r["surface"], r["category"])].append(r)

    def cell_stats(rs):
        ttfts = [r.get("ttft_s") for r in rs if r.get("ttft_s", -1) >= 0]
        tots = [r.get("total_s") for r in rs if r.get("total_s")]
        chars = [r.get("turns_meta", [{}])[-1].get("chars", 0) for r in rs]
        return {"n": len(rs),
                "pass_rate": round(
                    sum(1 for r in rs if _passed(r)) / len(rs), 4),
                "ttft_p50_s": _pct(ttfts, 50), "ttft_p95_s": _pct(ttfts, 95),
                "total_p50_s": _pct(tots, 50), "total_p95_s": _pct(tots, 95),
                "avg_chars": _avg(chars)}

    out["scorecards"] = {f"{s} | {c}": cell_stats(rs)
                        for (s, c), rs in sorted(cells.items())}

    per_cat = defaultdict(dict)
    for (s, c), rs in cells.items():
        st = out["scorecards"][f"{s} | {c}"]
        per_cat[c][s] = st
    best = {}
    for cat, models in per_cat.items():
        ranked = sorted(
            models.items(),
            key=lambda kv: (-(kv[1]["pass_rate"] or 0),
                            kv[1]["total_p50_s"] or 999))
        best[cat] = [{"surface": s, "pass_rate": st["pass_rate"],
                      "total_p50_s": st["total_p50_s"]}
                     for s, st in ranked[:3]]
    out["best_model_per_category"] = best

    buckets = defaultdict(list)
    for r in rows:
        buckets[r.get("bucket", "solo")].append(r)
    tput = {}
    for b, rs in buckets.items():
        tots = [r.get("total_s") for r in rs if r.get("total_s")]
        tput[b] = {"n": len(rs), "avg_total_s": _avg(tots),
                   "p95_total_s": _pct(tots, 95),
                   "approx_cases_per_minute_per_conc8":
                       round(len(rs) / (_avg(tots) or 1) * 8 / 60, 2)}
    out["throughput_by_bucket"] = tput

    fails = [r for r in rows if not _passed(r)]
    checks = Counter()
    for r in fails:
        for k, v in (_verdict_dict(r).get("checks") or {}).items():
            if v is False:
                checks[k] += 1
    out["failure_taxonomy"] = dict(checks)
    out["error_types"] = dict(Counter(
        r.get("error", "").split(":")[0] for r in rows if r.get("error")))

    stages = Counter()
    hops = Counter()
    for r in rows:
        for t in r.get("turns_meta") or []:
            for s in t.get("stages") or []:
                stages[s] += 1
            for h in t.get("hops") or []:
                hops[h] += 1
    out["stage_mix"] = dict(stages)
    out["hop_mix"] = dict(hops.most_common(20))
    if mock_stats:
        out["mock_ablit"] = {
            "total_calls": mock_stats.get("total"),
            "by_behavior": mock_stats.get("by_behavior"),
            "redhands_system_calls": mock_stats.get("redhands_calls"),
            "rh_tagged_cases": len({tag for c in mock_stats.get("calls", [])
                                     for tag in c.get("rh_tags", [])})}
    return out


def to_markdown(data):
    L = ["# MAX-SCOPE MATRIX REPORT", "",
         f"total cases: **{data['total']}** | passed: **{data['passed']}** "
         f"| pass rate: **{data.get('pass_rate')}** | errors: {data['errors']}",
         ""]
    L.append("## Best model per category (top 3 by pass rate, then p50)")
    for cat, ranking in data["best_model_per_category"].items():
        L.append(f"- **{cat}**: " + "; ".join(
            f"{r['surface']} ({r['pass_rate']:.0%}, p50 {r['total_p50_s']}s)"
            for r in ranking))
    L.append("\n## Throughput by bucket")
    for b, t in data["throughput_by_bucket"].items():
        L.append(f"- **{b}**: n={t['n']} avg={t['avg_total_s']}s "
                 f"p95={t['p95_total_s']}s "
                 f"~{t['approx_cases_per_minute_per_conc8']}/min@conc8")
    L.append("\n## Failure taxonomy (failed checks)")
    for k, v in data["failure_taxonomy"].items():
        L.append(f"- {k}: {v}")
    if data.get("error_types"):
        L.append("\n## Error types")
        for k, v in data["error_types"].items():
            L.append(f"- {k}: {v}")
    L.append("\n## Routing stage mix")
    for k, v in data["stage_mix"].items():
        L.append(f"- {k}: {v}")
    if data.get("mock_ablit"):
        m = data["mock_ablit"]
        L.append("\n## Simulated-ablit (zero real ablit spend)")
        L.append(f"- total mock calls: {m['total_calls']} "
                 f"(behaviors: {m['by_behavior']})")
        L.append(f"- REDHANDS system calls: {m['redhands_system_calls']}; "
                 f"rh-tagged cases reaching the terminal: "
                 f"{m['rh_tagged_cases']}")
    L.append("\n## Scorecards (surface | category)")
    L.append("| surface | category | n | pass | ttft p50/p95 | "
             "total p50/p95 | avg chars |")
    L.append("|---|---|---|---|---|---|---|")
    for key, st in data["scorecards"].items():
        s, c = key.split(" | ")
        L.append(f"| {s} | {c} | {st['n']} | {st['pass_rate']:.0%} | "
                 f"{st['ttft_p50_s']}/{st['ttft_p95_s']} | "
                 f"{st['total_p50_s']}/{st['total_p95_s']} | "
                 f"{st['avg_chars']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results",
                    default=os.path.join(RESULTS_DIR, "cases.jsonl"))
    args = ap.parse_args()
    rows = load_rows(args.results)
    mock_path = os.path.join(RESULTS_DIR, "mock_stats.json")
    mock = None
    if os.path.exists(mock_path):
        with io.open(mock_path, encoding="utf-8") as fh:
            mock = json.load(fh)
    data = analyze(rows, mock)
    with io.open(os.path.join(RESULTS_DIR, "matrix_data.json"), "w",
                 encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    md = to_markdown(data)
    with io.open(os.path.join(RESULTS_DIR, "matrix_report.md"), "w",
                 encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    print("data: matrix_data.json | report: matrix_report.md")


if __name__ == "__main__":
    main()