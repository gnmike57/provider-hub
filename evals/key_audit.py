"""Live credential audit: real usage test for every hub key (masked output).

Boots no servers, touches no state files, prints no full key values. For each
unique key found (account_pool.json + environment + gx10 router envs + the
gateway registry) it issues a REAL minimal upstream call and classifies:

    OK          HTTP 200 with content (credential + billing are healthy)
    AUTH_FAIL   401/403 (revoked / wrong key type / no access)
    DEPLETED    402/405 (org out of balance / not in good standing)  <- the
                "insufficient" family the operator kept seeing
    RATE        429 (credential valid, throttled)
    ERROR       anything else (network / upstream 5xx / unknown endpoint)

Results land (masked) in evals/results/key_audit.jsonl. Exit code is always 0;
the JSON verdict table is the deliverable. Providers outside the operator's
declared surface (abliteration.ai + thehive.ai) are flagged FOREIGN but still
measured, so their removal is evidence-based rather than assumed.

Usage: python evals/key_audit.py [--timeout 45]
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

HIVE_URL = "https://api-cdn.thehive.ai/api/v3/chat/completions"
HIVE_MODEL = "zai-org/glm-5.3-flash"
AB_URL = "https://api.abliteration.ai/v1/chat/completions"
AB_MODEL = "abliterated-model-large-v2"
NANO_URL = "https://nano-gpt.com/api/v1/chat/completions"
NANO_MODEL = "xiaomi/mimo-v2.6-flash-abliterated"
ADMIN_BASE = "https://api.abliteration.ai/v1"

KEY_RE = re.compile(r"^\S{12,}$")  # any plausible single-token secret


def mask(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 12:
        return k[:3] + "..."
    return k[:5] + "..." + k[-4:]


def classify(status: int, body: str) -> str:
    if status in (401, 403):
        return "AUTH_FAIL"
    if status in (402, 405):
        return "DEPLETED"
    if status == 429:
        return "RATE"
    if 200 <= status < 300:
        return "OK"
    return "ERROR"


def chat_probe(url: str, key: str, model: str, timeout: float):
    """One real minimal usage call. Returns (verdict, http_status, detail)."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: PONG"}],
        "max_tokens": 16,
        "stream": False,
    }
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
    except Exception as exc:  # network layer
        return "ERROR", 0, f"{type(exc).__name__}: {exc}"[:160]
    text = (r.text or "")[:220].replace("\n", " ")
    v = classify(r.status_code, r.text)
    if v == "OK":
        try:
            content = r.json()["choices"][0]["message"]["content"]
            detail = f"usage-reply={str(content)[:60]!r}"
        except Exception:
            detail = "http 200 (envelope unparsed)"
    else:
        detail = f"http {r.status_code}: {text}"
    return v, r.status_code, detail


def admin_probe(key: str, timeout: float):
    """Abliteration admin key: no public admin spec is in-tree, so measure the
    key as a credential against both the admin base and the chat surface and
    report exactly what was observed (never guess an endpoint into OK)."""
    checks = []
    for url in (f"{ADMIN_BASE}/admin/organization/balance",
                f"{ADMIN_BASE}/organization/balance",
                f"{ADMIN_BASE}/key/info"):
        try:
            r = httpx.get(url, headers={"Authorization": "Bearer " + key},
                          timeout=timeout)
            checks.append((url, r.status_code, (r.text or "")[:120]))
        except Exception as exc:
            checks.append((url, 0, type(exc).__name__[:60]))
    # chat-surface validity: does the key even authenticate a 1-token call?
    v, status, detail = chat_probe(AB_URL, key, AB_MODEL, timeout)
    if v == "OK":
        return "OK", status, "admin key also works as a chat key: " + detail
    for url, status_c, body_c in checks:
        if status_c in (401, 403):
            return "AUTH_FAIL", status_c, f"admin GET {url.split('/v1')[-1]} -> 401/403; chat: {detail}"
        if status_c in (402, 405):
            return "DEPLETED", status_c, f"admin GET {url.split('/v1')[-1]} -> {status_c}; chat: {detail}"
        if status_c == 200:
            return "OK", status_c, f"admin GET {url.split('/v1')[-1]} -> 200"
    return "ERROR", status, "no admin endpoint answered; chat probe: " + detail


def refresh_env_from_user_scope():
    """SYNC process env with the persisted User-scope values (HKCU wins).

    Fill-missing was not enough: a shell whose parent inherited PRE-refit
    values shadowed the healthy User-scope ones, so audits measured ghosts
    (the 2026-10-21 ak_Ge 402 incident re-appeared in results even though
    the live surface was clean). Now: set when present in HKCU, pop when
    absent there - the audit always measures the real persisted surface."""
    try:
        import winreg
    except ImportError:
        return
    for name in ("ABLITERATION_API_KEY", "ABLITERATION_ADMIN_KEY",
                 "HIVE_SECRET_KEY", "HIVE_ACCESS_KEY", "NANOGPT_API_KEY",
                 "NANOGPT_MGMT_API_KEY", "ADMIN_API_KEY"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                val, _ = winreg.QueryValueEx(k, name)
            os.environ[name] = val
        except FileNotFoundError:
            os.environ.pop(name, None)
        except OSError:
            continue


def collect() -> list:
    """Every (origin, label, provider_hint, key) we can find - deduped by value."""
    found = {}

    def add(origin, label, hint, key):
        key = (key or "").strip()
        if not key or not KEY_RE.match(key):
            return
        if key in found:
            found[key]["origins"].append(origin)
            return
        found[key] = {"origin": origin, "label": label, "hint": hint,
                      "key": key, "origins": [origin]}

    pool = ROOT / "account_pool.json"
    if pool.exists():
        try:
            data = json.loads(pool.read_text(encoding="utf-8"))
            for i, row in enumerate(data.get("accounts", [])):
                add(f"account_pool.json[{i}]", row.get("label", f"acct-{i}"),
                    row.get("provider", ""), row.get("key", ""))
        except Exception as exc:
            print(f"WARN: account_pool.json unreadable: {exc}")
    for name in ("ABLITERATION_API_KEY", "ABLITERATION_ADMIN_KEY",
                 "HIVE_SECRET_KEY", "HIVE_ACCESS_KEY", "NANOGPT_API_KEY",
                 "NANOGPT_MGMT_API_KEY", "ADMIN_API_KEY"):
        add(f"env:{name}", name, "", os.getenv(name, ""))
    for rel in ("tars/gx10-router/router.env", ".tars-setup/router/router.env"):
        p = ROOT / rel
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(\S+)\s*$", line)
            if m and any(t in m.group(1) for t in ("KEY", "SECRET", "TOKEN")):
                val = m.group(2)
                if val.startswith(("os.environ/", "env:")):
                    continue
                add(rel, m.group(1), "", val)
    reg = ROOT / "gateway_registry.json"
    if reg.exists():
        try:
            data = json.loads(reg.read_text(encoding="utf-8"))
            for pid, prov in (data.get("providers") or {}).items():
                if isinstance(prov, dict):
                    add("gateway_registry.json", pid, pid, prov.get("key", ""))
        except Exception:
            pass
    return list(found.values())


def hint_to_surface(hint: str, origin: str) -> str:
    h = (hint or "").lower() + " " + origin.lower()
    if "hive" in h:
        return "hive"
    if "ablit" in h:
        return "ablit"
    if "nano" in h or "cat_" in h:
        return "nano"
    return ""


def probe_one(surface: str, key: str, timeout: float):
    if surface == "hive":
        return chat_probe(HIVE_URL, key, HIVE_MODEL, timeout)
    if surface == "ablit":
        return chat_probe(AB_URL, key, AB_MODEL, timeout)
    if surface == "ablit-admin":
        return admin_probe(key, timeout)
    if surface == "nano":
        return chat_probe(NANO_URL, key, NANO_MODEL, timeout)
    if key.startswith("sk_"):
        return admin_probe(key, timeout)
    # Unknown surface: try the three knowns in order, report best evidence.
    best = ("ERROR", 0, "no surface matched")
    for surf in ("hive", "ablit", "nano"):
        v, status, detail = probe_one(surf, key, timeout)
        if v == "OK":
            return v, status, f"[via {surf}] {detail}"
        if v != "ERROR":
            best = (v, status, f"[via {surf}] {detail}")
    return best


def main() -> int:
    timeout = 45.0
    if "--timeout" in sys.argv:
        timeout = float(sys.argv[sys.argv.index("--timeout") + 1])
    refresh_env_from_user_scope()
    keys = collect()
    out_path = ROOT / "evals" / "results" / "key_audit.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    print(f"key_audit: {len(keys)} unique keys found; firing live usage calls "
          f"(timeout={timeout:.0f}s)...")
    for item in keys:
        label = item["label"]
        if label in ("ADMIN_API_KEY", "ENCRYPTION_KEY", "HUB_ADMIN_KEY"):
            # Local credentials (hub admin auth / Fernet at-rest key) - they
            # never call an upstream provider and are out of audit scope.
            row = {"ts": ts, "label": label, "origin": item["origin"],
                   "surface": "local", "masked": mask(item["key"]),
                   "verdict": "LOCAL", "http": 0, "seconds": 0,
                   "detail": "local hub credential; not an upstream provider key",
                   "foreign_provider": False, "origins": item["origins"]}
            rows.append(row)
            print(f"  {label:<24} {'local':<7} {mask(item['key']):<16} "
                  f"{'LOCAL':<9} http=0    0.0s (out of audit scope)")
            with open(out_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            continue
        surface = hint_to_surface(item["hint"], item["origin"]) or "unknown"
        if label == "ABLITERATION_ADMIN_KEY" or surface == "ablit-admin":
            surface = "ablit-admin"
        t0 = time.monotonic()
        verdict, status, detail = probe_one(surface, item["key"], timeout)
        dt = time.monotonic() - t0
        foreign = surface == "nano" or "nano" in item["origin"].lower()
        row = {
            "ts": ts, "label": item["label"], "origin": item["origin"],
            "surface": surface, "masked": mask(item["key"]),
            "verdict": verdict, "http": status, "seconds": round(dt, 2),
            "detail": detail, "foreign_provider": foreign,
            "origins": item["origins"],
        }
        rows.append(row)
        flag = " FOREIGN" if foreign else ""
        print(f"  {item['label']:<24} {surface:<7} {mask(item['key']):<16} "
              f"{verdict:<9} http={status:<4} {dt:4.1f}s{flag}")
        print(f"      {detail}")
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    ok = sum(1 for r in rows if r["verdict"] == "OK")
    print(f"\nverdict: {ok}/{len(rows)} OK -> full masked record: {out_path}")
    print("removal rule: remove every non-OK and every FOREIGN key from the "
          "active surface (account_pool.json / env / router envs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

