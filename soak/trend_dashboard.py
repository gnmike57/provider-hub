"""Statistical trend dashboard for the gx10 soak loop.

Reads trend.jsonl and tinker_log.jsonl from ~/soak and produces:
  - Efficacy/waste/middle trend across passes
  - Knob adjustment history with before/after efficacy
  - Regression alerts (efficacy >0.1 below rolling average)
  - Defect breakdown by type
"""
import json
import statistics
import sys
from pathlib import Path

SOAK = Path.home() / "soak"
TREND_LOG = SOAK / "trend.jsonl"
TINKER_LOG = SOAK / "tinker_log.jsonl"
REPORT = SOAK / "report.txt"
DEFECTS = SOAK / "defects"


def _load_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def _load_defects():
    """Count defects by type from the defects directory."""
    counts = {}
    try:
        for f in DEFECTS.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                kind = data.get("kind", "unknown")
                counts[kind] = counts.get(kind, 0) + 1
            except Exception:
                pass
    except FileNotFoundError:
        pass
    return counts


def main():
    trend = _load_jsonl(TREND_LOG)
    tinkers = _load_jsonl(TINKER_LOG)
    defects = _load_defects()

    print("=" * 70)
    print("REDHANDS HUB SOAK - STATISTICAL TREND DASHBOARD")
    print("=" * 70)

    if not trend:
        print("No trend data yet. Run at least one soak pass.")
        return

    # --- Efficacy/waste/middle trend ---
    print("\n--- PERFORMANCE TREND (by pass) ---")
    print(f"{'Pass':<6} {'Corpus':<8} {'Req':<6} {'Efficacy':<10} {'Waste':<8} {'Middle':<8} {'UpTok':<8} {'Defects':<9}")
    for t in trend:
        print(f"{t.get('pass', '-'):<6} "
              f"{t.get('corpus', '-'):<8} "
              f"{t.get('requests', '-'):<6} "
              f"{t.get('efficacy', 0):<10.3f} "
              f"{t.get('waste', 0):<8.1f}x "
              f"{t.get('middle', 0):<8.0%} "
              f"{t.get('upstream_tokens', '-'):<8} "
              f"{t.get('defects', '-'):<9}")

    # --- Efficacy trend analysis ---
    effs = [t.get("efficacy", 0) for t in trend]
    print("\n--- EFFICACY ANALYSIS ---")
    print(f"Passes: {len(trend)}")
    print(f"Efficacy range: {min(effs):.3f} -> {max(effs):.3f}")
    if len(effs) >= 2:
        change = effs[-1] - effs[0]
        print(f"Total change: {change:+.3f}")
        avg = statistics.mean(effs)
        print(f"Average: {avg:.3f}")
        # Recent vs overall
        recent = effs[-3:] if len(effs) >= 3 else effs
        recent_avg = statistics.mean(recent)
        print(f"Recent {len(recent)}-pass average: {recent_avg:.3f}")
        if recent_avg < avg - 0.1:
            print("  ALERT: Recent efficacy >0.1 below overall average (regression)")

    # --- Waste trend ---
    wastes = [t.get("waste", 0) for t in trend]
    print("\n--- WASTE ANALYSIS ---")
    print(f"Waste range: {min(wastes):.1f}x -> {max(wastes):.1f}x")
    print(f"Average waste: {statistics.mean(wastes):.1f}x")

    # --- Middle contribution ---
    middles = [t.get("middle", 0) for t in trend]
    print("\n--- MIDDLE CONTRIBUTION ---")
    print(f"Middle range: {min(middles):.0%} -> {max(middles):.0%}")
    print(f"Average middle: {statistics.mean(middles):.0%}")
    if statistics.mean(middles) < 0.30:
        print("  ALERT: Middle contribution below 30% target")

    # --- Tinker history ---
    print("\n--- TINKER HISTORY ---")
    if not tinkers:
        print("No tinker adjustments recorded.")
    else:
        print(f"{'Pass':<6} {'Knob':<24} {'From':<8} {'To':<8} {'Reason'}")
        for t in tinkers:
            reg = " [REGRESSION]" if t.get("is_regression") else ""
            print(f"{t.get('pass', '-'):<6} "
                  f"{t.get('knob', '-'):<24} "
                  f"{t.get('from', '-'):<8} "
                  f"{t.get('to', '-'):<8} "
                  f"{t.get('why', '-')[:60]}{reg}")

    # --- Defect breakdown ---
    print("\n--- DEFECT BREAKDOWN ---")
    if not defects:
        print("No defects recorded.")
    else:
        total = sum(defects.values())
        for kind, count in sorted(defects.items(), key=lambda x: -x[1]):
            print(f"  {kind:<20} {count:>4}  ({count/total:.0%})")
        print(f"  {'TOTAL':<20} {total:>4}")

    # --- Recommendations ---
    print("\n--- RECOMMENDATIONS ---")
    recs = []
    if effs and effs[-1] < 0.85:
        recs.append("Efficacy below 0.85 target - continue tinkering")
    if wastes and wastes[-1] > 5.0:
        recs.append("Waste above 5.0x target - reduce RACE_GRACE_MS")
    if middles and middles[-1] < 0.30:
        recs.append("Middle below 30% target - reduce RACE_PEER_MIN_CHARS")
    if defects:
        recs.append(f"Defects present: {dict(defects)} - investigate defect types")
    if len(effs) >= 2 and effs[-1] < effs[-2]:
        recs.append("Efficacy declined from previous pass - check for regression")
    if not recs:
        recs.append("All metrics within targets - approaching FLAWLESS")
    for r in recs:
        print(f"  - {r}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
