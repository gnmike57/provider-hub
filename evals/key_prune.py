"""Prune failed/foreign keys from the hub's active key surface.

Consumes evals/results/key_audit.jsonl (latest run group) and removes every
key whose verdict is not OK/LOCAL from wherever it lives:

    account_pool.json        -> rows dropped (atomic rewrite + cross-process lock)
    env:<NAME>               -> os.environ pop + HKCU Environment DeleteValue
    tars/gx10-router/router.env / .tars-setup/router/router.env -> lines dropped
    gateway_registry.json    -> "key" field dropped from offending providers

Dry-run by default; pass --apply to execute. Every modified file is backed up
to <name>.bak-prune-<ts> first. LOCAL verdicts (hub admin auth, Fernet key)
are never touched - they are local credentials, not provider keys.

Usage: python evals/key_prune.py [--apply]
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "evals" / "results" / "key_audit.jsonl"
KEEP_VERDICTS = {"OK", "LOCAL"}


def latest_group():
    rows = []
    if not AUDIT.exists():
        return rows
    for line in AUDIT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return []
    ts = rows[-1]["ts"]
    return [r for r in rows if r["ts"] == ts]


def doomed(rows):
    return {r["masked"] for r in rows
            if r["verdict"] not in KEEP_VERDICTS or r.get("foreign_provider")}


def atomic_write(path: Path, text: str, ts: str):
    shutil.copy2(path, str(path) + f".bak-prune-{ts}")
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def prune_pool(rows, kill, ts, apply):
    pool = ROOT / "account_pool.json"
    if not pool.exists():
        return []
    actions = []
    try:
        data = json.loads(pool.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"SKIP account_pool.json (unreadable: {exc})"]
    kept, dropped = [], []
    for row in data.get("accounts", []):
        key = (row.get("key") or "").strip()
        masked = (key[:5] + "..." + key[-4:]) if len(key) > 12 else key[:3] + "..."
        if masked in kill:
            dropped.append(f"{row.get('label')} ({row.get('provider')}) {masked}")
        else:
            kept.append(row)
    if dropped and apply:
        data["accounts"] = kept
        try:
            import hub_ipc
            with hub_ipc.locked_path(str(pool)):
                atomic_write(pool, json.dumps(data, indent=2) + "\n", ts)
        except Exception:
            atomic_write(pool, json.dumps(data, indent=2) + "\n", ts)
    for d in dropped:
        actions.append(f"{'REMOVED' if apply else 'WOULD-REMOVE'} account_pool.json <- {d}")
    return actions


def prune_env(rows, kill, ts, apply):
    actions = []
    try:
        import winreg
    except ImportError:
        winreg = None
    for r in rows:
        if r["verdict"] in KEEP_VERDICTS and not r.get("foreign_provider"):
            continue
        origin = r["origin"]
        if not origin.startswith("env:"):
            continue
        name = origin.split(":", 1)[1]
        if apply:
            os.environ.pop(name, None)
            if winreg is not None:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment",
                                        0, winreg.KEY_SET_VALUE) as k:
                        winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    actions.append(f"WARN env {name}: {exc}")
        actions.append(f"{'REMOVED' if apply else 'WOULD-REMOVE'} env <- {name} ({r['masked']})")
    return actions


def prune_env_files(rows, kill, ts, apply):
    actions = []
    for rel in ("tars/gx10-router/router.env", ".tars-setup/router/router.env"):
        p = ROOT / rel
        if not p.exists():
            continue
        kept, dropped = [], []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(\S+)\s*$", line)
            if m and any(t in m.group(1) for t in ("KEY", "SECRET", "TOKEN")):
                val = m.group(2).strip()
                masked = (val[:5] + "..." + val[-4:]) if len(val) > 12 else val[:3] + "..."
                if masked in kill:
                    dropped.append(f"{rel} <- {m.group(1)} ({masked})")
                    continue
            kept.append(line)
        if dropped and apply:
            atomic_write(p, "\n".join(kept) + "\n", ts)
        actions.extend(f"{'REMOVED' if apply else 'WOULD-REMOVE'} {d}" for d in dropped)
    return actions


def prune_registry(rows, kill, ts, apply):
    reg = ROOT / "gateway_registry.json"
    if not reg.exists():
        return []
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
    except Exception:
        return []
    actions = []
    changed = False
    for pid, prov in (data.get("providers") or {}).items():
        if not isinstance(prov, dict):
            continue
        key = (prov.get("key") or "").strip()
        masked = (key[:5] + "..." + key[-4:]) if len(key) > 12 else key[:3] + "..."
        if masked in kill and key:
            if apply:
                prov.pop("key", None)
                changed = True
            actions.append(f"{'REMOVED' if apply else 'WOULD-REMOVE'} gateway_registry.json <- {pid} ({masked})")
    if changed and apply:
        atomic_write(reg, json.dumps(data, indent=2) + "\n", ts)
    return actions


def main() -> int:
    apply = "--apply" in sys.argv
    rows = latest_group()
    if not rows:
        print("key_prune: no audit results found (run evals/key_audit.py first)")
        return 1
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    kill = doomed(rows)
    actions = []
    actions += prune_pool(rows, kill, ts, apply)
    actions += prune_env(rows, kill, ts, apply)
    actions += prune_env_files(rows, kill, ts, apply)
    actions += prune_registry(rows, kill, ts, apply)
    out = ROOT / "evals" / "results" / "key_prune.jsonl"
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts, "apply": apply, "actions": actions,
                             "kill": sorted(kill)}, ensure_ascii=False) + "\n")
    mode = "APPLIED" if apply else "DRY-RUN"
    tally = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(f"key_prune [{mode}] verdicts: {tally}")
    for a in actions:
        print("  " + a)
    if not actions:
        print("  nothing to remove - all audited keys are OK/LOCAL")
    print(f"record: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

