"""(2026-10-23) THE COMPLETE TOKEN EFFICIENCY + EFFICACY MATRIX.

Per chain, SEQUENTIALLY (so the hub's upstream-spend counters attribute
cleanly): run the full 28-probe registry, snapshotting /healthz metrics
before/after each chain. The output table:

  chain | efficacy | upstream tok/req | shipped tok/req | waste ratio
        | tok per CORRECT answer | ttft med | tok/s

- upstream = TRUE provider spend (winners, shadow-race losers, escalations,
  continuations, probes, verifies) measured in chars/4 by the hub's
  upstream_chars_total + hedge_upstream_chars_total counters.
- shipped = what the client received (the useful output).
- efficacy = the probe checker's verdict (correct/28).
"""
import argparse
import asyncio
import json
import time

import httpx

from twelve_chain_live_matrix import CHAINS, chain_matrix

HUB = "http://localhost:9000"


async def _ametrics(client):
    r = await client.get(HUB + "/healthz", timeout=15.0)
    r.raise_for_status()
    m = (r.json() or {}).get("metrics") or {}
    return {"up": (m.get("upstream_chars_total") or 0)
            + (m.get("hedge_upstream_chars_total") or 0)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default=",".join(CHAINS))
    ap.add_argument("--out",
                    default="evals/results/token_efficiency_matrix.jsonl")
    args = ap.parse_args()
    chains = [c.strip() for c in args.chains.split(",") if c.strip()]

    summary = {}
    async with httpx.AsyncClient(trust_env=False) as client:
        for model in chains:
            before = await _ametrics(client)
            t0 = time.monotonic()
            res = await chain_matrix(asyncio.Semaphore(4), client,
                                    model, args.out)
            after = await _ametrics(client)
            wall = round(time.monotonic() - t0, 1)

            recs = list(res.values())
            n = len(recs)
            ok = sum(1 for r in recs if r.get("correct"))
            shipped = sum(r.get("content_tokens_est") or 0 for r in recs)
            up_tok = round((after["up"] - before["up"]) / 4)
            ttfts = sorted(r["ttft_s"] for r in recs
                          if r.get("ttft_s") is not None)
            med = ttfts[len(ttfts) // 2] if ttfts else None
            tps = [r.get("tokens_per_s") for r in recs
                   if r.get("tokens_per_s")]
            summary[model] = {
                "probes": n, "correct": ok, "efficacy": round(ok / max(1, n), 2),
                "upstream_tokens": up_tok,
                "shipped_tokens": shipped,
                "upstream_per_req": round(up_tok / max(1, n)),
                "shipped_per_req": round(shipped / max(1, n)),
                "waste_ratio": round(up_tok / max(1, shipped), 2),
                "tokens_per_correct": round(up_tok / max(1, ok)),
                "ttft_med": med,
                "tps_med": (sorted(tps)[len(tps) // 2] if tps else None),
                "wall_s": wall,
            }
            print(f"done {model}: {ok}/{n} correct, {up_tok} upstream tok, "
                  f"{wall}s", flush=True)

    print("\n=== TOKEN EFFICIENCY + EFFICACY MATRIX ===")
    hdr = (f"{'chain':38s} {'eff':>6s} {'up/req':>7s} {'ship/req':>8s} "
           f"{'waste':>5s} {'tok/ok':>7s} {'ttft':>5s} {'tps':>6s}")
    print(hdr)
    print("-" * len(hdr))
    for m, s in summary.items():
        print(f"{m:38s} {s['efficacy']:>6.2f} {s['upstream_per_req']:>7d} "
              f"{s['shipped_per_req']:>8d} {s['waste_ratio']:>5} "
              f"{s['tokens_per_correct']:>7d} {s['ttft_med']:>5} "
              f"{s['tps_med'] or 0:>6}")
    print(f"\nefficacy = correct/probes | up/req = TRUE provider tokens per "
          f"request | ship/req = client-received | waste = up/shipped"
          f" | tok/ok = upstream tokens per correct answer")
    with open("evals/results/token_efficiency_summary.json", "w",
              encoding="utf_8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print("summary -> evals/results/token_efficiency_summary.json")


if __name__ == "__main__":
    asyncio.run(main())
