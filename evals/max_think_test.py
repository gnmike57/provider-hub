"""Max-think names: "deepfrost max think" / "glmfrost max think" are the
MAX-REASONING versions of DeepFrost / GLMFrost. They stay on the PRIMARY slot
(Hive / thehive.ai keys) with the SAME Hive upstream ids, and reasoning is
pushed to maximum. The gateway injects the knob set server-side (never
trusted from the body), raises the token floor, and skips the speculative
race (COMMIT_TOKENS=10 would commit the flash worker mid-deliberation).
When the primary refuses, the existing divert machinery routes to the
NanoGPT abliterated specialist (worker slot) - exactly like a plain Frost
name. The max-reasoning names are published as dedicated endpoints.
"""

import providers
import proxy_gateway
from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, WORKER, chunk, script  # noqa: F401


def test_alias_table_covers_both_max_think_names():
    assert providers.resolve_frost_alias("deepfrost max think") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash-1017")
    assert providers.resolve_frost_alias("deepfrost-max-think") == (
        "primary", "deepseek-ai/deepseek-v4.1-flash-1017")
    assert providers.resolve_frost_alias("glmfrost max think") == (
        "primary", "zai-org/glm-5.3-flash")
    assert providers.resolve_frost_alias("glmfrost-max-think") == (
        "primary", "zai-org/glm-5.3-flash")


def test_max_think_detector_matches_the_names_and_nothing_else():
    assert proxy_gateway.wants_max_think("deepfrost max think")
    assert proxy_gateway.wants_max_think("DeepFrost Max Think")
    assert proxy_gateway.wants_max_think("glmfrost max think")
    assert proxy_gateway.wants_max_think("GLMFrost-Max-Think")
    # The plain Frost names and raw ids are NOT max-think.
    assert not proxy_gateway.wants_max_think("glmfrost")
    assert not proxy_gateway.wants_max_think("deepfrost")
    assert not proxy_gateway.wants_max_think("zai-org/glm-5.3-flash")
    assert not proxy_gateway.wants_max_think("")
    assert not proxy_gateway.wants_max_think(None)


def test_max_think_name_streams_and_hits_the_primary(script):
    """Max-reasoning names stay on the PRIMARY slot (Hive / thehive.ai keys)
    with the Hive upstream id - the NanoGPT abliterated specialist is reached
    only through the normal divert path, not by alias routing."""
    script.script(PRIMARY, [("sse", [chunk("deep", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "glmfrost max think",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "deep" in resp.text
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent, "the primary was never called"
    assert sent[0]["json"]["model"] == "zai-org/glm-5.3-flash"
    # The specialist worker must not be touched by the alias itself.
    assert not [c for c in script.calls if c["url"] == WORKER]


def test_max_think_deepfrost_uses_the_hive_deepseek_id(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "deepfrost max think",
                      "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    assert sent[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"


def test_max_think_injects_the_knob_set_server_side(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "deepfrost max think",
                      "messages": [{"role": "user", "content": "hi"}]})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    body = sent[0]["json"]
    assert body["reasoning_effort"] == "max"
    assert body["reasoning"] == {"effort": "max"}
    assert body["reasoning_content"] is True
    assert body["enable_thinking"] is True
    assert body["chat_template_kwargs"] == {"thinking": True}
    assert body["thinking"] == {"type": "enabled"}
    # Token floor: 4096 < 32768, both caps raised so extra-hard thinking
    # cannot exhaust the budget on hidden reasoning alone (measured empty-
    # content-at-length failure on Hive at 2000).
    assert body["max_tokens"] == 32768
    assert body["max_completion_tokens"] == 32768


def test_max_think_respects_a_higher_client_token_cap(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "glmfrost max think",
                      "messages": [{"role": "user", "content": "hi"}],
                      "max_tokens": 65000})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    body = sent[0]["json"]
    assert body["max_tokens"] == 65000
    assert body["max_completion_tokens"] == 65000


def test_max_think_never_races_the_speculative_hedge(script):
    """A forced hedge must NOT dual-dispatch a max-think request: the race
    commits to the 10-token flash worker while the deep model still thinks."""
    script.script(PRIMARY, [("sse", [chunk("maxthink", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("flash", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "deepfrost max think",
                             "messages": [{"role": "user", "content": "hi"}],
                             "hedge": True})
    assert resp.status_code == 200
    assert "maxthink" in resp.text
    assert not [c for c in script.calls if c["url"] == WORKER], (
        "a max-think request must never dispatch the worker slot")


def test_max_think_refusal_diverts_to_the_nanogpt_specialist(script):
    """The max-think name is a PRIMARY model; when the primary refuses, the
    existing divert machinery routes to the worker slot (the NanoGPT
    abliterated specialist) - exactly like a plain Frost name."""
    script.script(PRIMARY, [("sse", [chunk("I cannot help with that", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("specialist-answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        resp = tc.post("/v1/chat/completions",
                       json={"model": "glmfrost max think",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "specialist-answer" in resp.text
    worker_calls = [c for c in script.calls if c["url"] == WORKER]
    assert worker_calls, "a refused max-think request must divert to the specialist"


def test_plain_frost_names_keep_their_hedge_and_get_no_knobs(script):
    script.script(PRIMARY, [("sse", [chunk("plain", finish="stop"), DONE])])
    script.script(WORKER, [("sse", [chunk("flash", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "glmfrost",
                      "messages": [{"role": "user", "content": "hi"}],
                      "hedge": True})
    sent = [c for c in script.calls if c["url"] == PRIMARY]
    body = sent[0]["json"]
    assert "reasoning_effort" not in body
    assert body["max_tokens"] == 4096  # unchanged default
    assert [c for c in script.calls if c["url"] == WORKER], (
        "the forced hedge on a plain Frost name must still race")


def test_max_think_requests_are_counted(script):
    script.script(PRIMARY, [("sse", [chunk("ok", finish="stop"), DONE])])
    before = proxy_gateway._METRICS["max_think_total"]
    with TestClient(proxy_gateway.app) as tc:
        tc.post("/v1/chat/completions",
                json={"model": "DeepFrost Max Think",
                      "messages": [{"role": "user", "content": "hi"}]})
    assert proxy_gateway._METRICS["max_think_total"] == before + 1


def test_model_list_publishes_both_max_think_endpoints(monkeypatch):
    # legacy catalog view: the 3-chain-only default is explicitly opted out
    monkeypatch.setenv("CONSTELLATION_ONLY", "0")
    with TestClient(proxy_gateway.app) as tc:
        data = tc.get("/v1/models").json()["data"]
    ids = [m["id"] for m in data]
    assert "deepfrost max think" in ids
    assert "glmfrost max think" in ids
    by_id = {m["id"]: m for m in data}
    assert by_id["deepfrost max think"]["max_think"] is True
    assert by_id["glmfrost max think"]["max_think"] is True
    # Max-reasoning names stay on the Hive primary with the Hive upstream ids.
    assert by_id["deepfrost max think"]["endpoint"].endswith(":9314/v1")
    assert by_id["glmfrost max think"]["endpoint"].endswith(":9315/v1")
    assert by_id["deepfrost max think"]["root"] == "deepseek-ai/deepseek-v4.1-flash-1017"
    assert by_id["glmfrost max think"]["root"] == "zai-org/glm-5.3-flash"
    assert by_id["deepfrost max think"]["reasoning"] == "max"
    assert by_id["glmfrost max think"]["reasoning"] == "max"
    assert by_id["deepfrost max think"]["hedged"] is False
    # The plain names stay unflagged.
    assert by_id["deepfrost"]["max_think"] is False
    assert by_id["deepfrost"]["reasoning"] is None
    assert by_id["glmfrost"]["max_think"] is False
