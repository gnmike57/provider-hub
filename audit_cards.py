"""Completely real card-amount audit via the hub's SIPHON agent.

Really charges every configured amount (SIPHON_AUDIT_AMOUNTS, default grid
within the charge bounds) on every active card through the Abliteration.ai
admin charge API, recording every outcome in card_amount_audit.jsonl.

Money safety (W2):
  * every pair must pass the ONE hard pre-charge guard in siphon.py
    (card exists+active, charges < MAX_CHARGE_PER_CARD, MIN_CHARGE_INTERVAL
    elapsed, org balance < BALANCE_LOW_TRIGGER) before it is charged;
  * --max-amount caps the audited amounts (default: SIPHON_MAX_CHARGE_AMOUNT);
  * --dry-run only LISTS the untested pairs and never charges;
  * without --yes an interactive confirmation is required, so running this
    script can never spend real money by accident.

Run:  python audit_cards.py [--dry-run | --yes] [--max-amount USD]
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, r"C:\Users\lnxzf\Desktop\projects\provider-hub")
os.environ.setdefault("ABLITERATION_API_KEY", "REDACTED_ABLIT_KEY")
os.environ.setdefault("ABLITERATION_ADMIN_KEY", "REDACTED_ADMIN_KEY")

import siphon  # noqa: E402


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Completely real card-amount audit (charges REAL money)."
    )
    p.add_argument("--yes", action="store_true",
                   help="skip the interactive confirmation and charge immediately")
    p.add_argument("--dry-run", action="store_true",
                   help="only list the untested pairs; never charge anything")
    p.add_argument("--max-amount", type=float, default=siphon.MAX_CHARGE_AMOUNT,
                   help="audit amount cap in USD (default: SIPHON_MAX_CHARGE_AMOUNT)")
    return p.parse_args(argv)


async def main(argv=None):
    args = _parse_args(argv)
    cap = float(args.max_amount)
    agent = siphon.SiphonAgent()
    active = agent.cards.active_cards()
    print(f"Active cards: {len(active)}")
    for c in agent.cards.summary():
        print("  -", c)
    untested = [(cid, amt) for cid, amt in agent.audit.untested(active) if amt <= cap]
    est_total = sum(amt for _, amt in untested)
    print(f"Untested (card, amount) pairs to REALLY charge (<= ${cap:.2f}): {len(untested)}")
    for cid, amt in untested:
        print(f"  - {cid} @ ${amt:.2f}")
    print(f"Estimated spend if all succeed: ${est_total:.2f}")

    if args.dry_run:
        print("\n--dry-run: listed only, nothing charged.")
        return
    if not untested:
        print("\nNothing to charge.")
        return
    if not args.yes:
        answer = input(
            f"\nREALLY charge {len(untested)} pair(s), ~${est_total:.2f} total? "
            "Type 'yes' to continue: "
        )
        if answer.strip().lower() not in ("yes", "y"):
            print("Aborted: nothing charged.")
            return

    print("\nRunning completely real audit charges...", flush=True)
    results = await agent.audit_cards(max_amount=cap)
    for r in results:
        status = r.get("status")
        err = r.get("error", "") or r.get("detail", "")
        print(f"  [{r['card_id']}] ${r['amount_usd']:.2f} -> {status}"
              + (f" :: {err[:120]}" if err and status not in ("success",) else ""))

    print("\n=== INTELLIGENT AUDIT SUMMARY ===")
    print(json.dumps(agent.audit.summary(), indent=2))
    print("\nBest proven combo for auto top-up:", agent.intelligent_topup_combo())


if __name__ == "__main__":
    asyncio.run(main())

