"""Incident refit: replace the depleted Abliteration key everywhere it is
pinned, and remove dead/foreign keys - driven by key_audit.jsonl verdicts.

Actions (all backed up, all logged masked):
  1. REPLACE the worst failed abliteration key (DEPLETED 402 - the
     "insufficient_credits" incident) with a healthy pool key in:
       - Windows User-scope env ABLITERATION_API_KEY (the launcher reads it
         at boot to pin PRIMARY/FALLBACK/SPECIALIST)
       - tars/gx10-router/router.env + .tars-setup/router/router.env
         (ABLITERATION_API_KEY and LITELLM_MASTER_KEY - the router's design
         reuses the ak_ key as its master key, so both get the healthy value)
       - gateway_registry.json provider "key" fields holding the dead value
  2. REMOVE every other failed/foreign key:
       - account_pool.json rows whose key failed (e.g. the 401'd row of a
         since-retired provider)
       - Windows User-scope env vars whose CURRENT value failed (value-guarded:
         a var already re-pointed to a healthy key is left alone)

Usage: python evals/key_refit.py [--apply]   (dry-run default)
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
KEEP = {"OK", "LOCAL"}


def mask(v: str) -> str:
    v = (v or "").strip()
    return (v[:5] + "..." + v[-4:]) if len(v) > 12 else v[:3] + "..."


def latest_group():
    rows = [json.loads(l) for l in
            AUDIT.read_text(encoding="utf-8").splitlines() if l.strip()]
    ts = rows[-1]["ts"]
    return [r for r in rows if r["ts"] == ts]


def user_env(name: str):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _ = winreg.QueryValueEx(k, name)
        return v
    except Exception:
        return os.getenv(name, "")


def set_user_env(name: str, value: str):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except Exception:
        os.environ[name] = value


def del_user_env(name: str):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


def backup(path: Path, ts: str):
    if path.exists():
        shutil.copy2(path, str(path) + f".bak-refit-{ts}")


def main() -> int:
    apply = "--apply" in sys.argv
    rows = latest_group()
    bad = [r for r in rows if r["verdict"] not in KEEP or r.get("foreign_provider")]
    if not bad:
        print("key_refit: nothing failed; nothing to do")
        return 0
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log = []

    # healthy replacement = first OK abliteration pool key
    pool = ROOT / "account_pool.json"
    data = json.loads(pool.read_text(encoding="utf-8"))
    ok_ablit = {r["masked"] for r in rows
                if r["verdict"] == "OK" and r["surface"] == "ablit"}
    healthy = ""
    healthy_label = ""
    for row in data.get("accounts", []):
        if row.get("provider") == "ablit" and mask(row.get("key", "")) in ok_ablit:
            healthy = row["key"]
            healthy_label = row.get("label")
            break
    if not healthy:
        print("key_refit: no healthy abliteration pool key found - aborting")
        return 1

    # 1. the depleted abliteration key: replace everywhere it is pinned
    dead_rows = [r for r in bad if r["surface"] == "ablit"
                 and r["verdict"] == "DEPLETED"]
    dead = ""
    if dead_rows:
        if mask(user_env("ABLITERATION_API_KEY")) == dead_rows[0]["masked"]:
            dead = user_env("ABLITERATION_API_KEY")
        else:
            for rel in ("tars/gx10-router/router.env",
                        ".tars-setup/router/router.env"):
                p = ROOT / rel
                if not p.exists():
                    continue
                for line in p.read_text(encoding="utf-8",
                                        errors="replace").splitlines():
                    m = re.match(r"^ABLITERATION_API_KEY\s*=\s*(\S+)\s*$", line)
                    if m and mask(m.group(1)) == dead_rows[0]["masked"]:
                        dead = m.group(1)
                        break
                if dead:
                    break
    if dead:
        log.append(f"REPLACING depleted abliteration key {mask(dead)} "
                   f"-> {healthy_label} {mask(healthy)}")
        targets = []
        if mask(user_env("ABLITERATION_API_KEY")) == mask(dead):
            targets.append(("User env ABLITERATION_API_KEY", None))
        for rel in ("tars/gx10-router/router.env", ".tars-setup/router/router.env"):
            p = ROOT / rel
            if p.exists() and dead in p.read_text(encoding="utf-8",
                                                  errors="replace"):
                targets.append((rel, p))
        reg = ROOT / "gateway_registry.json"
        if reg.exists() and dead in reg.read_text(encoding="utf-8",
                                                 errors="replace"):
            targets.append(("gateway_registry.json", reg))
        for label, path in targets:
            log.append(f"  {'REPLACED' if apply else 'WOULD-REPLACE'} in {label}")
            if apply:
                if path is None:
                    set_user_env("ABLITERATION_API_KEY", healthy)
                    os.environ["ABLITERATION_API_KEY"] = healthy
                else:
                    backup(path, ts)
                    text = path.read_text(encoding="utf-8", errors="replace")
                    path.write_text(text.replace(dead, healthy),
                                    encoding="utf-8")

    # 2. remove remaining failed/foreign keys (value-guarded)
    for r in bad:
        m_ = r["masked"]
        if dead and m_ == mask(dead):
            continue  # handled above by replacement
        if r["origin"].startswith("env:"):
            name = r["origin"].split(":", 1)[1]
            if mask(user_env(name)) != m_:
                log.append(f"  SKIP env {name} (value already healthy/replaced)")
                continue
            if apply:
                del_user_env(name)
                os.environ.pop(name, None)
            log.append(f"{'REMOVED' if apply else 'WOULD-REMOVE'} env {name} ({m_})")
        elif r["origin"].startswith("account_pool.json"):
            if apply:
                data["accounts"] = [row for row in data.get("accounts", [])
                                     if mask(row.get("key", "")) != m_]
            log.append(f"{'REMOVED' if apply else 'WOULD-REMOVE'} account_pool.json row ({m_})")
    if apply:
        backup(pool, ts)
        pool.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    out = ROOT / "evals" / "results" / "key_refit.jsonl"
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts, "apply": apply, "log": log},
                            ensure_ascii=False) + "\n")
    print(f"key_refit [{'APPLIED' if apply else 'DRY-RUN'}]")
    for line in log:
        print("  " + line)
    print(f"record: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

