"""W2 money & card safety regression tests (one test per fix).

Fixes covered (no test here ever charges real money - all siphon HTTP is
mocked; the CLI test runs against an empty tmp card inventory):
  1.  siphon: charge intent persisted BEFORE the POST + idempotency key sent
  2.  siphon: a timeout marks the intent and never auto-retries (no double charge)
  3.  siphon: the ONE hard pre-charge guard blocks every unsafe condition
  4.  siphon: the guard allows a genuinely safe charge
  5.  siphon: the audit path is wrapped by the same guard + per-card budget
  6.  siphon: the audit path honours the amount cap
  7.  audit_cards.py: __main__ guard + --dry-run never charge
  8.  proxy_gateway: /v1/user/topup requires admin + bounded numeric amount
  9.  proxy_gateway: /v1/user/keys requires admin; refuses plaintext at rest
  10. proxy_gateway: /v1/siphon/* requires admin
  11. billing: UsageTracker._load survives a malformed timestamp line
  12. billing: free-credit minting via X-User-Id is bounded
  13. billing: KeyVault roundtrips encrypted; plaintext refused with no key
  14. launch_frost_hub.ps1 pins ENCRYPTION_KEY (+ ADMIN_API_KEY)
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import billing
import proxy_gateway
import siphon

ROOT = Path(__file__).resolve().parents[1]
TEST_FERNET = "ER9W35oE9l3Hm3V9dEBdeOCht4R5DPiaQJ6BmfFDjiE="


# --------------------------------------------------------------------------
# siphon test harness: fake httpx module so no test ever hits the network
# --------------------------------------------------------------------------
class _FakeAsyncClient:
    def __init__(self, post_handler):
        self._post = post_handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        return self._post(headers, json)

    async def get(self, url, headers=None):
        return httpx.Response(200, json={"data": {}})


class _FakeHttpx:
    """Stands in for the httpx module inside siphon for one test."""

    TimeoutException = httpx.TimeoutException

    def __init__(self, post_handler):
        self._post = post_handler

    def AsyncClient(self, timeout=None):
        return _FakeAsyncClient(self._post)


def _fresh_agent(tmp_path):
    """SiphonAgent whose every ledger is tmp-backed (never the real files)."""
    agent = siphon.SiphonAgent()
    agent.intents = siphon.ChargeIntents(path=str(tmp_path / "intents.jsonl"))
    agent.cards = siphon.CardInventory(path=str(tmp_path / "cards.jsonl"))
    agent.memory = siphon.SiphonMemory(path=str(tmp_path / "memory.jsonl"))
    agent.audit = siphon.CardAmountAudit(
        path=str(tmp_path / "audit.jsonl"), intents=agent.intents
    )
    agent.state = {
        "last_charge_ts": 0.0,
        "total_charges": 0,
        "total_extracted_usd": 0.0,
        "enabled": True,
    }
    return agent


def _low_balance(v):
    async def f():
        return v
    return f


# --------------------------------------------------------------------------
# 1. siphon: intent persisted BEFORE the POST + idempotency key
# --------------------------------------------------------------------------
def test_execute_charge_persists_intent_before_post_with_idempotency_key(
    tmp_path, monkeypatch
):
    agent = _fresh_agent(tmp_path)
    cid = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    seen = {}

    def handler(headers, json_body):
        key = headers.get("Idempotency-Key")
        assert key, "charge POST must carry an Idempotency-Key header"
        assert json_body.get("idempotency_key") == key
        # THE regression: while the POST is in flight the intent row must
        # already be persisted, status pending (BEFORE the response exists).
        row = agent.intents.get(key)
        assert row is not None, "intent row not persisted before the POST"
        assert row["status"] == "pending"
        seen["key"] = key
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(siphon, "httpx", _FakeHttpx(handler))
    decision = {"charge_now": True, "card_id": cid, "amount_usd": 25.0}
    outcome = asyncio.run(agent._execute_charge(decision, org_balance=1.0))
    assert outcome["status"] == "charged"
    assert agent.intents.get(seen["key"])["status"] == "success"


# --------------------------------------------------------------------------
# 2. siphon: timeout marks the intent, never auto-retries
# --------------------------------------------------------------------------
def test_execute_charge_timeout_marks_intent_and_never_retries(tmp_path, monkeypatch):
    agent = _fresh_agent(tmp_path)
    cid = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    calls = []

    def handler(headers, json_body):
        calls.append(json_body)
        raise httpx.ReadTimeout("read timed out")

    monkeypatch.setattr(siphon, "httpx", _FakeHttpx(handler))
    decision = {"charge_now": True, "card_id": cid, "amount_usd": 25.0}
    outcome = asyncio.run(agent._execute_charge(decision, org_balance=1.0))
    assert outcome["status"] == "error"
    assert "timeout" in outcome["error"]
    # exactly one POST: retrying after a timeout is what double-charges
    assert len(calls) == 1
    key = None
    for row in agent.intents._rows:
        if row["source"] == "siphon":
            key = row["idempotency_key"]
    assert key is not None
    assert agent.intents.get(key)["status"] == "timeout"


# --------------------------------------------------------------------------
# 3. siphon: the ONE hard pre-charge guard blocks every unsafe condition
# --------------------------------------------------------------------------
def test_pre_charge_guard_blocks_every_unsafe_condition(tmp_path, monkeypatch):
    agent = _fresh_agent(tmp_path)

    # unknown card
    ok, reason = asyncio.run(
        agent._pre_charge_guard("card_missing", 25.0, org_balance=1.0)
    )
    assert not ok and "not found" in reason

    # inactive card
    cid = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    agent.cards.mark_failed(cid)
    ok, reason = asyncio.run(agent._pre_charge_guard(cid, 25.0, org_balance=1.0))
    assert not ok and "status is" in reason

    # maxed card (charges >= MAX_CHARGE_PER_CARD)
    c_max = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    for _ in range(siphon.MAX_CHARGE_PER_CARD):
        agent.cards.mark_used(c_max, 20.0)
    ok, reason = asyncio.run(agent._pre_charge_guard(c_max, 25.0, org_balance=1.0))
    assert not ok and "MAX_CHARGE_PER_CARD" in reason

    # interval not elapsed (card used moments ago)
    c_recent = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    agent.cards.mark_used(c_recent, 20.0)
    ok, reason = asyncio.run(
        agent._pre_charge_guard(c_recent, 25.0, org_balance=1.0)
    )
    assert not ok and "interval" in reason

    # amount out of bounds
    c_ok = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    ok, reason = asyncio.run(agent._pre_charge_guard(c_ok, 99.0, org_balance=1.0))
    assert not ok and "outside" in reason
    ok, reason = asyncio.run(agent._pre_charge_guard(c_ok, 5.0, org_balance=1.0))
    assert not ok and "outside" in reason

    # balance at/above the low-balance trigger
    ok, reason = asyncio.run(
        agent._pre_charge_guard(c_ok, 25.0, org_balance=siphon.BALANCE_LOW_TRIGGER)
    )
    assert not ok and "trigger" in reason

    # balance unknown: fail CLOSED
    monkeypatch.setattr(agent, "_org_balance", _low_balance(None))
    ok, reason = asyncio.run(agent._pre_charge_guard(c_ok, 25.0, org_balance=None))
    assert not ok and "unknown" in reason


# --------------------------------------------------------------------------
# 4. siphon: the guard allows a genuinely safe charge
# --------------------------------------------------------------------------
def test_pre_charge_guard_allows_a_safe_charge(tmp_path, monkeypatch):
    agent = _fresh_agent(tmp_path)
    cid = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    monkeypatch.setattr(agent, "_org_balance", _low_balance(1.0))
    ok, reason = asyncio.run(agent._pre_charge_guard(cid, 25.0, org_balance=None))
    assert ok, reason


# --------------------------------------------------------------------------
# 5. siphon: the audit path is wrapped by the same guard + per-card budget
# --------------------------------------------------------------------------
def test_audit_path_respects_guard_and_card_budget(tmp_path, monkeypatch):
    agent = _fresh_agent(tmp_path)
    cid = agent.cards.add_card("4111111111111111", 12, 2030, "123")
    posts = []

    def handler(headers, json_body):
        posts.append(json_body)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(siphon, "httpx", _FakeHttpx(handler))

    # healthy balance: the guard skips EVERY pair (the audit path used to
    # bypass every budget and charge the full ~$298/card grid regardless)
    monkeypatch.setattr(agent, "_org_balance", _low_balance(100.0))
    results = asyncio.run(agent.audit_cards(amounts=[20.0, 25.0]))
    assert posts == []
    assert [r["status"] for r in results] == ["skipped", "skipped"]
    assert "trigger" in results[0]["error"]

    # low balance + zero interval: charges at most MAX_CHARGE_PER_CARD pairs,
    # then the card is maxed and the rest are skipped
    monkeypatch.setattr(agent, "_org_balance", _low_balance(1.0))
    monkeypatch.setattr(siphon, "MIN_CHARGE_INTERVAL_S", 0)
    results = asyncio.run(agent.audit_cards(amounts=[20.0, 25.0, 30.0, 35.0]))
    assert len(posts) == siphon.MAX_CHARGE_PER_CARD
    statuses = [r["status"] for r in results]
    assert statuses[: siphon.MAX_CHARGE_PER_CARD] == [
        "success"
    ] * siphon.MAX_CHARGE_PER_CARD
    assert statuses[siphon.MAX_CHARGE_PER_CARD] == "skipped"
    assert "MAX_CHARGE_PER_CARD" in results[siphon.MAX_CHARGE_PER_CARD]["error"]
    card = agent.cards.get_card(cid)
    assert card["charges"] == siphon.MAX_CHARGE_PER_CARD
    assert card["status"] == "maxed"


# --------------------------------------------------------------------------
# 6. siphon: the audit path honours the amount cap
# --------------------------------------------------------------------------
def test_audit_respects_amount_cap(tmp_path, monkeypatch):
    agent = _fresh_agent(tmp_path)
    agent.cards.add_card("4111111111111111", 12, 2030, "123")
    posts = []

    def handler(headers, json_body):
        posts.append(json_body)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(siphon, "httpx", _FakeHttpx(handler))
    monkeypatch.setattr(agent, "_org_balance", _low_balance(1.0))
    monkeypatch.setattr(siphon, "MIN_CHARGE_INTERVAL_S", 0)
    results = asyncio.run(agent.audit_cards(amounts=[20.0, 60.0], max_amount=50.0))
    assert [r["amount_usd"] for r in results] == [20.0]
    assert len(posts) == 1
    assert posts[0]["amount_usd"] == 20.0


# --------------------------------------------------------------------------
# 7. audit_cards.py: __main__ guard + --dry-run never charge
# --------------------------------------------------------------------------
def test_audit_cards_cli_guarded_and_dry_run(tmp_path, monkeypatch):
    # Keys are env-sourced since 2026-10-21 (no secrets in source). Dummies
    # suffice: --dry-run never calls the API, and the module-level guard only
    # requires them to be present.
    monkeypatch.setenv("ABLITERATION_API_KEY", "ak-test")
    monkeypatch.setenv("ABLITERATION_ADMIN_KEY", "sk-test")
    env = dict(os.environ)
    env.update(
        {
            "SIPHON_CARDS_FILE": str(tmp_path / "cards.jsonl"),
            "SIPHON_MEMORY_FILE": str(tmp_path / "memory.jsonl"),
            "SIPHON_STATE_FILE": str(tmp_path / "state.json"),
            "SIPHON_AUDIT_FILE": str(tmp_path / "audit.jsonl"),
            "SIPHON_INTENTS_FILE": str(tmp_path / "intents.jsonl"),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    r = subprocess.run(
        [sys.executable, "audit_cards.py", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        timeout=180,
    )
    assert r.returncode == 0, r.stderr
    assert "Active cards: 0" in r.stdout
    assert "dry-run" in r.stdout
    audit_file = tmp_path / "audit.jsonl"
    assert not audit_file.exists() or audit_file.read_text(encoding="utf-8") == ""

    # importing the module must NOT run main() (a module-level asyncio.run
    # used to fire real charges on a plain import)
    import audit_cards as audit_cli

    assert callable(audit_cli.main)
    assert hasattr(audit_cli, "_parse_args")


# --------------------------------------------------------------------------
# 8. proxy_gateway: /v1/user/topup requires admin + bounded numeric amount
# --------------------------------------------------------------------------
def test_topup_requires_admin_and_validates_amount(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
    monkeypatch.setattr(proxy_gateway.SETTINGS, "abliteration_admin_key", "sk-test")
    monkeypatch.setattr(proxy_gateway.SETTINGS, "credit_topup_amount", 10.0)
    monkeypatch.setattr(
        proxy_gateway.billing_mod,
        "BILLING",
        billing.UserBilling(path=str(tmp_path / "users.jsonl")),
    )
    with TestClient(proxy_gateway.app) as tc:
        # unauthenticated / wrong admin key
        assert tc.post("/v1/user/topup", json={"amount_usd": 5}).status_code == 403
        assert (
            tc.post(
                "/v1/user/topup",
                headers={"X-Admin-Key": "nope"},
                json={"amount_usd": 5},
            ).status_code
            == 403
        )
        # non-numeric amount: 400, not a 500
        r = tc.post(
            "/v1/user/topup",
            headers={"X-Admin-Key": "adm-test"},
            json={"amount_usd": "five"},
        )
        assert r.status_code == 400
        # out-of-bounds amounts
        for bad in (0, -3.0, 999.0):
            r = tc.post(
                "/v1/user/topup",
                headers={"X-Admin-Key": "adm-test"},
                json={"amount_usd": bad},
            )
            assert r.status_code == 400, bad

        # happy path: mocked upstream + real (tmp-backed) billing credit
        class _Upstream:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, headers=None, json=None):
                self.calls.append(json)
                return httpx.Response(200, json={"ok": True})

        up = _Upstream()
        monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: up)
        r = tc.post(
            "/v1/user/topup",
            headers={"X-Admin-Key": "adm-test", "X-User-Id": "topup-user"},
            json={"amount_usd": 5.0},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "charged"
        assert up.calls and up.calls[0]["amount_usd"] == 5.0
        assert proxy_gateway.billing_mod.BILLING.get_balance("topup-user") == (
            pytest.approx(billing.CREDIT_FREE_TIER + 5.0)
        )

        # /v1/admin/charge: same numeric bounds (defense in depth - it also
        # charges real money, so a non-numeric or out-of-bounds amount is a
        # 400 rather than a crash / unbounded charge)
        r = tc.post(
            "/v1/admin/charge",
            headers={"X-Admin-Key": "adm-test"},
            json={"user_id": "topup-user", "amount_usd": "five"},
        )
        assert r.status_code == 400
        r = tc.post(
            "/v1/admin/charge",
            headers={"X-Admin-Key": "adm-test"},
            json={"user_id": "topup-user", "amount_usd": 999.0},
        )
        assert r.status_code == 400
        assert not tc.post("/v1/admin/charge", json={}).status_code == 200


# --------------------------------------------------------------------------
# 9. proxy_gateway: /v1/user/keys requires admin; refuses plaintext at rest
# --------------------------------------------------------------------------
def test_user_keys_admin_and_encryption_refusal(tmp_path, monkeypatch):
    saved = billing._FERNET
    try:
        monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
        # no admin key -> 403 before touching the vault
        with TestClient(proxy_gateway.app) as tc:
            assert (
                tc.post("/v1/user/keys", json={"hive_api_key": "sk-1"}).status_code
                == 403
            )
            assert tc.get("/v1/user/keys").status_code == 403

        # admin key but no ENCRYPTION_KEY -> 503 refusal (no plaintext at rest)
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        billing._FERNET = None
        with TestClient(proxy_gateway.app) as tc:
            r = tc.post(
                "/v1/user/keys",
                headers={"X-Admin-Key": "adm-test"},
                json={"hive_api_key": "sk-plain"},
            )
            assert r.status_code == 503
            assert "ENCRYPTION_KEY" in r.text

        # with the key pinned -> 200, ciphertext at rest, roundtrip works
        monkeypatch.setenv("ENCRYPTION_KEY", TEST_FERNET)
        billing._FERNET = None
        kv = billing.KeyVault(path=str(tmp_path / "keys.jsonl"))
        monkeypatch.setattr(proxy_gateway.billing_mod, "KEY_VAULT", kv)
        with TestClient(proxy_gateway.app) as tc:
            r = tc.post(
                "/v1/user/keys",
                headers={"X-Admin-Key": "adm-test", "X-User-Id": "u1"},
                json={"hive_api_key": "sk-secret"},
            )
            assert r.status_code == 200, r.text
            r = tc.get(
                "/v1/user/keys",
                headers={"X-Admin-Key": "adm-test", "X-User-Id": "u1"},
            )
            assert r.status_code == 200
            assert r.json()["keys"]["hive"]["key_present"] is True
        stored = (tmp_path / "keys.jsonl").read_text(encoding="utf-8")
        assert "sk-secret" not in stored
        assert kv.get_key("u1", "hive") == "sk-secret"
    finally:
        billing._FERNET = saved


# --------------------------------------------------------------------------
# 10. proxy_gateway: /v1/siphon/* requires admin
# --------------------------------------------------------------------------
def test_siphon_endpoints_require_admin(monkeypatch):
    monkeypatch.setattr(proxy_gateway.SETTINGS, "admin_api_key", "adm-test")
    with TestClient(proxy_gateway.app) as tc:
        assert tc.get("/v1/siphon/status").status_code == 403
        assert tc.get("/v1/siphon/cards").status_code == 403
        assert tc.get("/v1/siphon/memory").status_code == 403
        assert tc.post("/v1/siphon/evaluate").status_code == 403
        assert tc.post("/v1/siphon/card", json={}).status_code == 403
        assert tc.post("/v1/siphon/toggle", json={"enabled": False}).status_code == 403
        # read-only endpoints answer with the admin key
        r = tc.get("/v1/siphon/status", headers={"X-Admin-Key": "adm-test"})
        assert r.status_code == 200
        assert "enabled" in r.json()
        assert (
            tc.get("/v1/siphon/cards", headers={"X-Admin-Key": "adm-test"}).status_code
            == 200
        )
        assert (
            tc.get("/v1/siphon/memory", headers={"X-Admin-Key": "adm-test"}).status_code
            == 200
        )


# --------------------------------------------------------------------------
# 11. billing: UsageTracker._load survives a malformed timestamp line
# --------------------------------------------------------------------------
def test_usage_tracker_malformed_timestamp_is_skipped(tmp_path):
    p = tmp_path / "usage.jsonl"
    good = json.dumps(
        {
            "user_id": "u1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": "m",
            "tokens_in": 1,
            "tokens_out": 2,
            "cost_usd": 0.1,
            "provider": "hive",
        }
    )
    p.write_text(
        good + "\n"
        + json.dumps({"user_id": "u2", "timestamp": "not-a-date"}) + "\n"
        + json.dumps({"user_id": "u3"}) + "\n",
        encoding="utf-8",
    )
    ut = billing.UsageTracker(path=str(p))  # must not raise (boot safety)
    assert ut.user_usage("u1")["total_requests"] == 1
    assert ut.user_usage("u2")["total_requests"] == 0
    assert ut.user_usage("u3")["total_requests"] == 0


# --------------------------------------------------------------------------
# 12. billing: free-credit minting via X-User-Id is bounded
# --------------------------------------------------------------------------
def test_free_tier_minting_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(billing, "FREE_TIER_MAX_USERS", 2)
    ub = billing.UserBilling(path=str(tmp_path / "users.jsonl"))
    assert ub.get_balance("u1") == billing.CREDIT_FREE_TIER
    assert ub.get_balance("u2") == billing.CREDIT_FREE_TIER
    # past the cap a NEW user id (e.g. spoofed X-User-Id) mints nothing
    assert ub.get_balance("u3") == 0.0
    assert ub.get_balance("u4") == 0.0
    # an existing user keeps their grant
    assert ub.get_balance("u1") == billing.CREDIT_FREE_TIER


# --------------------------------------------------------------------------
# 13. billing: KeyVault roundtrips encrypted; plaintext refused with no key
# --------------------------------------------------------------------------
def test_vault_refuses_plaintext_writes_and_roundtrips_encrypted(tmp_path, monkeypatch):
    saved = billing._FERNET
    try:
        # no key configured: the write is REFUSED (was silently plaintext)
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        billing._FERNET = None
        kv = billing.KeyVault(path=str(tmp_path / "keys.jsonl"))
        with pytest.raises(RuntimeError):
            kv.store_key("u1", "hive", "sk-plain")
        assert not (tmp_path / "keys.jsonl").exists()

        # key pinned: stored encrypted, reads roundtrip
        monkeypatch.setenv("ENCRYPTION_KEY", TEST_FERNET)
        billing._FERNET = None
        kv.store_key("u1", "hive", "sk-secret")
        stored = (tmp_path / "keys.jsonl").read_text(encoding="utf-8")
        assert "sk-secret" not in stored
        assert kv.get_key("u1", "hive") == "sk-secret"
    finally:
        billing._FERNET = saved


# --------------------------------------------------------------------------
# 14. launch_frost_hub.ps1 pins ENCRYPTION_KEY (+ ADMIN_API_KEY)
# --------------------------------------------------------------------------
def test_launch_script_pins_encryption_and_admin_keys():
    text = (ROOT / "launch_frost_hub.ps1").read_text(encoding="utf-8")
    # 2026-10-21 (W0 secret hygiene): the launcher resolves ENCRYPTION_KEY and
    # ADMIN_API_KEY from process/User scope (Resolve-Secret, -Required boot
    # preflight) instead of pinning literals in source - secrets must not live
    # in the repo. New contract: both names MUST be resolved via Resolve-Secret
    # -Required; a literal pin, when one is present, must still validate as
    # before (valid Fernet key / >=20 chars).
    for _name in ("ENCRYPTION_KEY", "ADMIN_API_KEY"):
        assert f"Resolve-Secret '{_name}' -Required" in text, (
            f"{_name} must be resolved via Resolve-Secret -Required "
            "in the launcher (or pinned as a valid literal)")
    m = re.search(r"\$env:ENCRYPTION_KEY\s*=\s*\"([^\"]+)\"", text)
    if m and m.group(1).strip():
        Fernet(m.group(1).encode())  # literal pin, if any: valid Fernet key
    m = re.search(r"\$env:ADMIN_API_KEY\s*=\s*\"([^\"]+)\"", text)
    if m and m.group(1).strip():
        assert len(m.group(1)) >= 20, "ADMIN_API_KEY literal must be >= 20 chars"

