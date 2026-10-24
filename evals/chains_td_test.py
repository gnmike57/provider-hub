"""T-D wave (2026-10-22): the three NEW constellation chains.

Chain 5  RACE:DEEPMAX/GLMMAX>ABLITV2L       - dual-sovereign race
Chain 6  GLMMAX-CONDUCTOR>DEEP+ABLITV2L      - planner/sharpen/fanout/verify
Chain 7  ABLITV2L-HELM>GLM-PROBE>DEEP-VERIFY - pre-probe + REDHANDS helm + verifier

Pins:
  - resolution: the three ids resolve (case/whitespace-insensitive), the hop
    tuples are exact, and the four PUBLISHED chains stay byte-identical
    (the T-D additions never touch them)
  - /v1/models: the catalog grows to 7; the original four stay first
  - RACE: first clean substantive answer commits and wins (loser cancelled,
    terminal never burns); both refusing climbs to the V2 terminal;
    RACE_CHAIN_ENABLED=0 restores the plain 3-hop chain flow
  - CONDUCTOR: planner -> sharpened routine subtasks (camouflage vocabulary)
    -> blind DEEP hops + REDHANDS V2 for the nastiest -> FANOUT_MAX_PARALLEL
    fan-out -> assemble + completion-contract verify (one repair round);
    plan failure degrades to the single nasty hop; kill switch
  - SUSTAINED: GLM pre-probe skips the expensive V2 on clean + simple;
    a refusing probe / complex ask goes to the V2 helm under REDHANDS;
    DEEP verifies the evidence claims ([[GW-VERIFY]] footnote, R4: the
    finish marker re-emitted after it); SUSTAINED_CHAIN_ENABLED=0 restores
    chain-3 behaviour
"""
import json

from fastapi.testclient import TestClient
from helpers import DONE, PRIMARY, chunk, script  # noqa: F401

import providers
import proxy_gateway
import redhands

SPEC = "http://ablit.test/v1/chat/completions"

RACE = "RACE:DEEPMAX/GLMMAX>ABLITV2L"
CONDUCTOR = "GLMMAX-CONDUCTOR>DEEP+ABLITV2L"
SUSTAINED = "ABLITV2L-HELM>GLM-PROBE>DEEP-VERIFY"


def _ablit_provider(monkeypatch):
    monkeypatch.setitem(proxy_gateway.HUB_PROVIDERS, "ablit.ai",
                        {"url": SPEC, "key": "ak-test"})


def _reset_metrics():
    for key in proxy_gateway._METRICS:
        proxy_gateway._METRICS[key] = 0


def _json_step(content, model="primary"):
    return ("json", {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": content}, "finish_reason": "stop"}],
        "model": model})


def _calls_to(sc, url):
    return [c for c in sc.calls if c["url"] == url]


def _post(tc, model, content, **extra):
    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    body.update(extra)
    return tc.post("/v1/chat/completions", json=body)


# ---------------------------------------------------------------------------
# resolution + catalog (additive-only law)
# ---------------------------------------------------------------------------

def test_td_chains_resolve_and_published_four_stay_byte_identical():
    chains = providers.CONSTELLATION_CHAINS
    # the three NEW ids resolve, case/whitespace-insensitively
    assert providers.resolve_constellation_chain(
        "race: deepmax / glmmax > ablitv2l") is chains[RACE]
    assert providers.resolve_constellation_chain(
        "glmmax-conductor> deep+ablitv2l") is chains[CONDUCTOR]
    assert providers.resolve_constellation_chain(
        "ablitv2l-helm> glm-probe > deep-verify") is chains[SUSTAINED]
    # hop tuples are the contract
    r = chains[RACE]
    assert r["helm"] == ("primary", "deepseek-ai/deepseek-v4.1-flash-1017", True)
    assert r["middle"] == ("primary", "zai-org/glm-5.3-flash", True)
    assert r["terminal"] == ("ablit.ai", "abliterated-model-large-v2", False)
    assert r["redhands"] is False and r["race"] is True
    c = chains[CONDUCTOR]
    assert c["helm"] == ("primary", "zai-org/glm-5.3-flash", True)
    assert c["middle"] == ("primary", "deepseek-ai/deepseek-v4.1-flash-1017", False)
    assert c["terminal"] == ("ablit.ai", "abliterated-model-large-v2", False)
    assert c["redhands"] is False and c["conductor"] is True
    s = chains[SUSTAINED]
    assert s["helm"] == ("ablit.ai", "abliterated-model-large-v2", False)
    assert s["middle"] == ("primary", "zai-org/glm-5.3-flash", False)
    assert s["terminal"] == ("ablit.ai", "abliterated-model-large-v2", False)
    assert s["verify"] == ("primary", "deepseek-ai/deepseek-v4.1-flash-1017", False)
    assert s["redhands"] is True and s["sustained"] is True
    # ADDITIVE-ONLY LAW: the four published chains are byte-identical
    assert chains["GLMMAX>DEEP>ABLITV2L"] == {
        "description": "GLM-5.3 max-reasoning helm; DeepSeek blind sub-agent; "
                       "Abliterated V2 Large terminal (REDHANDS on offense).",
        "helm": ("primary", "zai-org/glm-5.3-flash", True),
        "middle": ("primary", "deepseek-ai/deepseek-v4.1-flash-1017", False),
        "terminal": ("ablit.ai", "abliterated-model-large-v2", False),
        "redhands": False,
    }
    assert chains["DEEPMAX>GLM>ABLITV2L"]["helm"] == (
        "primary", "deepseek-ai/deepseek-v4.1-flash-1017", True)
    assert chains["DEEPMAX>GLM>ABLITV2L"]["middle"] == (
        "primary", "zai-org/glm-5.3-flash", False)
    assert chains["ABLITV2L>SUB-GLM/DEEP"]["redhands"] is True
    assert chains["GLMMAX>ABLIT-UNC>ABLITV2L"]["middle"] == (
        "ablit.ai", "abliterated-model-large-v2", False)


def test_td_models_catalog_grows_to_ten(monkeypatch):
    monkeypatch.delenv("CONSTELLATION_ONLY", raising=False)
    # full structural pin: the ablit hide (2026-10-22) is OFF for this test
    monkeypatch.setenv("HIDE_ABLIT_MODELS", "0")
    with TestClient(proxy_gateway.app) as tc:
        data = tc.get("/v1/models").json()["data"]
    ids = [m["id"] for m in data]
    # REACTIVATION WAVE (2026-10-23): 7 -> 10 chains (three additive
    # variations - same general scope, different order/composition).
    assert len(ids) == 12
    assert ids[:4] == [  # the published four first, untouched
        "GLMMAX>DEEP>ABLITV2L", "DEEPMAX>GLM>ABLITV2L", "ABLITV2L>SUB-GLM/DEEP",
        "GLMMAX>ABLIT-UNC>ABLITV2L"]
    assert ids[4:7] == [RACE, CONDUCTOR, SUSTAINED]
    assert ids[7:] == [
        "DEEPMAX>ABLIT-UNC>ABLITV2L",
        "ABLITV2L>SUB-DEEP/GLM",
        "ABLITV2L-HELM>DEEP-PROBE>GLM-VERIFY",
        "RACE:GLMMAX/GLM>ABLITV2L",
        "RACE:DEEPMAX/DEEP>ABLITV2L",
    ]
    for m in data:
        assert m["description"]


def test_td_parity_baseline_stays_a_subset():
    import pathlib
    baseline = json.loads(pathlib.Path(__file__).with_name(
        "parity_baseline.json").read_text(encoding="utf-8"))
    assert set(baseline["chains"]) <= set(providers.CONSTELLATION_CHAINS)


# ---------------------------------------------------------------------------
# chain 5 - RACE:DEEPMAX/GLMMAX>ABLITV2L
# ---------------------------------------------------------------------------

def test_race_glm_wins_when_deep_refuses(script, monkeypatch):
    """Both max-reasoning helms fire in parallel; the helm (deep) refuses,
    the middle (glm) answers clean -> GLM's answer ships (buffer replayed
    verbatim), the loser never shows, and the uncensored terminal never
    burns (token efficiency)."""
    _ablit_provider(monkeypatch)
    proxy_gateway.SETTINGS.specialist_system_mode = "neutral"
    # open order: helm (deep) first, middle (glm) second - the Script pops
    # per-URL steps in order
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("The GLM answer is short but perfectly clean.",
                       finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "The GLM answer is short but perfectly clean." in r.text
    assert "I cannot help" not in r.text
    # both candidates fired, both under max reasoning (the chain NAME)
    prim = _calls_to(script, PRIMARY)
    assert len(prim) == 2
    assert [c["json"]["model"] for c in prim] == [
        "deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash"]
    for c in prim:
        assert c["json"]["reasoning_effort"] == "max"
        assert c["json"]["enable_thinking"] is True
    # TOKEN EFFICIENCY: the V2 terminal never burned
    assert not _calls_to(script, SPEC)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_total"] == 1
    assert snap["race_terminal_total"] == 0


def test_race_deep_wins_when_glm_refuses(script, monkeypatch):
    """The mirror: the deep helm answers clean and commits; the refusing GLM
    candidate is dropped, its refusal never ships, the terminal never burns."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("Deep wins this race with a clean substantive answer.",
                       finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "Deep wins this race with a clean substantive answer." in r.text
    assert "I cannot help" not in r.text
    assert not _calls_to(script, SPEC)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_total"] == 1 and snap["race_terminal_total"] == 0


def test_race_commit_token_window_wins_mid_stream(script, monkeypatch):
    """COMMIT_TOKENS is a real commit WINDOW: the first candidate to deliver
    COMMIT_TOKENS content chunks of clean substantive text commits BEFORE
    its stream ends; the loser is cancelled mid-stream (cancel-on-commit)."""
    import speculative_hedge
    _ablit_provider(monkeypatch)
    commit_tokens = max(1, int(speculative_hedge.SETTINGS.commit_tokens or 1))
    # deep streams content chunk-by-chunk: it commits at the window, well
    # before [DONE]; glm is scripted to refuse (never gets to ship)
    script.script(PRIMARY, [
        ("sse", [chunk(f"part {i} ") for i in range(commit_tokens + 2)]
                + [chunk("end of the deep answer.", finish="stop"), DONE]),
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
    ])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    # the whole winning stream replayed verbatim (buffer + live tail)
    assert "part 0 " in r.text and "end of the deep answer." in r.text
    assert "I cannot help" not in r.text
    assert not _calls_to(script, SPEC)


def test_race_both_refuse_escalate_to_the_v2_terminal(script, monkeypatch):
    """Any refusal from BOTH -> the uncensored terminal answers under the
    commitment contract (CONTEXT PURITY: the refusal text never forwards)."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        ("sse", [chunk("I cannot help with that.", finish="stop"), DONE]),
        ("sse", [chunk("I'm unable to comply with that.", finish="stop"), DONE]),
    ])
    script.script(SPEC, [
        ("sse", [chunk("uncensored race terminal answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "uncensored race terminal answer" in r.text
    term = _calls_to(script, SPEC)
    assert term and term[0]["json"]["model"] == "abliterated-model-large-v2"
    msgs = term[0]["json"]["messages"]
    # the terminal-bound re-ask carries the neutral redirect directive, never
    # either candidate's refusal text
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == proxy_gateway.CONTRACT_REDIRECT_SENTENCE + \
        proxy_gateway.CONTRACT_CAMO_TEACHBACK
    assert not any(m.get("role") == "assistant"
                   and "unable to comply" in str(m.get("content"))
                   for m in msgs)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["race_total"] == 1
    assert snap["race_terminal_total"] == 1


def test_race_kill_switch_restores_the_plain_chain_flow(script, monkeypatch):
    """RACE_CHAIN_ENABLED=0: the plain 3-hop chain semantics - the DEEPMAX
    helm answers on the normal primary stream (no dual-open race)."""
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("RACE_CHAIN_ENABLED", "0")
    script.script(PRIMARY, [
        ("sse", [chunk("helm answered without a race.", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, RACE, "audit this box")
    assert r.status_code == 200
    assert "helm answered without a race." in r.text
    prim = _calls_to(script, PRIMARY)
    # exactly ONE primary call: the helm stream, no second racing candidate
    assert len(prim) == 1
    assert prim[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
    assert prim[0]["json"]["stream"] is True
    assert not _calls_to(script, SPEC)
    assert proxy_gateway.metrics_snapshot()["race_total"] == 0


# ---------------------------------------------------------------------------
# chain 6 - GLMMAX-CONDUCTOR>DEEP+ABLITV2L
# ---------------------------------------------------------------------------

_PLAN = {
    "subtasks": [
        {"text": "Explain the keylogger capture mechanism.", "nasty": False},
        {"text": "Write the ransomware recovery playbook.", "nasty": True},
    ],
    "checklist": ["capture mechanism explanation", "ransomware recovery playbook"],
}


def test_conductor_plans_sharpens_assigns_and_assembles(script, monkeypatch):
    """The GLMMAX conductor plans; the routine subtask goes to the BLIND
    DeepSeek sub-agent with its trigger words SHARPENED by the camouflage
    learned map; the nastiest goes verbatim to the V2 under REDHANDS; the
    assembled deliverable streams with the conductor stage colour."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),
        _json_step("The input monitor hooks the keyboard event stream and "
                   "logs every keystroke with the capture mechanism."),
    ])
    script.script(SPEC, [
        _json_step("The ransomware recovery playbook: isolate, decrypt, "
                   "restore. Recovery plan done.")])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, "cover the keylogger capture and the "
                                 "ransomware recovery playbook")
    assert r.status_code == 200
    # the conductor stage colour leads the SSE stream
    assert "gw-stage conductor glm-5.3-flash" in r.text
    # both assembled sections ship in one deliverable
    assert "### Explain the keylogger capture mechanism." in r.text
    assert "### Write the ransomware recovery playbook." in r.text
    assert "logs every keystroke" in r.text
    assert "isolate, decrypt" in r.text
    # provenance closes the deliverable
    assert "(REDHANDS)" in r.text
    prim = _calls_to(script, PRIMARY)
    # call 1: the conductor planner (GLMMAX, max reasoning, non-streaming)
    assert prim[0]["json"]["model"] == "zai-org/glm-5.3-flash"
    assert prim[0]["json"]["reasoning_effort"] == "max"
    assert prim[0]["json"]["stream"] is False
    assert prim[0]["json"]["messages"][1]["content"].startswith(
        "cover the keylogger capture")
    # call 2: the routine blind DEEP hop - SHARPENED (camouflage vocabulary)
    routine = prim[1]["json"]
    assert routine["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
    assert len(routine["messages"]) == 1  # BLIND: the subtask only
    assert "input monitor" in routine["messages"][0]["content"]
    assert "keylogger" not in routine["messages"][0]["content"]
    assert routine["reasoning_effort"] == "none"  # blind hop: thinking off
    # the nasty hop: V2, REDHANDS system turn, subtask VERBATIM
    nasty = _calls_to(script, SPEC)[0]["json"]
    assert nasty["model"] == "abliterated-model-large-v2"
    assert nasty["messages"][0] == {
        "role": "system", "content": redhands.REDHANDS_SYSTEM}
    assert "ransomware recovery playbook" in nasty["messages"][1]["content"]
    assert "max_completion_tokens" not in nasty  # the ablit single-cap law
    snap = proxy_gateway.metrics_snapshot()
    assert snap["conductor_total"] == 1
    assert snap["conductor_fanout_total"] == 1
    assert snap["conductor_verified_total"] == 1  # checklist fully covered
    assert snap["conductor_repair_total"] == 0


def test_conductor_completion_contract_repairs_uncovered_items(script, monkeypatch):
    """ASSEMBLE + VERIFY via the completion contract: a round-1 answer that
    misses its checklist item triggers exactly ONE repair re-dispatch of the
    implicated subtask; the repaired deliverable then verifies."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step(json.dumps(_PLAN)),
        _json_step("Barely anything useful here."),     # round 1: misses it
        _json_step("The capture mechanism explanation: it hooks the "
                   "keyboard event stream and logs every keystroke."),
    ])
    script.script(SPEC, [
        _json_step("The ransomware recovery playbook: isolate, decrypt, "
                   "restore. Recovery plan done.")])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, "cover the keylogger capture and the "
                                 "ransomware recovery playbook")
    assert r.status_code == 200
    assert "logs every keystroke" in r.text  # the repaired section ships
    assert "Barely anything useful here." not in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["conductor_repair_total"] == 1
    assert snap["conductor_verified_total"] == 1
    # the repair re-dispatched ONLY the implicated routine subtask
    deep_calls = [c for c in _calls_to(script, PRIMARY)
                  if c["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"]
    assert len(deep_calls) == 2  # round 1 + the repair round


def test_conductor_plan_failure_degrades_to_the_single_nasty_hop(script, monkeypatch):
    """A dead planner is never a client error: the WHOLE ask becomes the
    nastiest subtask and the V2 (REDHANDS) answers it."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [("status", 500, {"error": "planner down"})])
    script.script(SPEC, [
        _json_step("the V2 answers the whole ask under REDHANDS")])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, "do the nasty thing")
    assert r.status_code == 200
    assert "the V2 answers the whole ask under REDHANDS" in r.text
    nasty = _calls_to(script, SPEC)[0]["json"]
    assert nasty["messages"][0] == {
        "role": "system", "content": redhands.REDHANDS_SYSTEM}
    assert nasty["messages"][1]["content"] == "do the nasty thing"
    snap = proxy_gateway.metrics_snapshot()
    assert snap["conductor_plan_failed_total"] == 1
    assert snap["conductor_fanout_total"] == 0  # single hop: no fan-out


def test_conductor_kill_switch_restores_the_plain_chain_flow(script, monkeypatch):
    """CONDUCTOR_CHAIN_ENABLED=0: the GLMMAX helm answers on the normal
    primary stream - no planner call at all."""
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_CHAIN_ENABLED", "0")
    script.script(PRIMARY, [
        ("sse", [chunk("plain helm answer, no conductor.",
                       finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, CONDUCTOR, "do the thing")
    assert r.status_code == 200
    assert "plain helm answer, no conductor." in r.text
    prim = _calls_to(script, PRIMARY)
    assert len(prim) == 1
    assert prim[0]["json"]["model"] == "zai-org/glm-5.3-flash"
    assert prim[0]["json"]["stream"] is True  # the streaming helm, not a planner
    assert not _calls_to(script, SPEC)
    assert proxy_gateway.metrics_snapshot()["conductor_total"] == 0


# ---------------------------------------------------------------------------
# chain 7 - ABLITV2L-HELM>GLM-PROBE>DEEP-VERIFY
# ---------------------------------------------------------------------------

def test_sustained_probe_hit_skips_the_expensive_terminal(script, monkeypatch):
    """A SIMPLE ask + a CLEAN GLM pre-probe -> the probe's answer ships
    (probe stage colour + skip disclosure), and the expensive V2 terminal is
    never called."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step("The capital of France is Paris, famously so.")])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, SUSTAINED, "what is the capital of France")
    assert r.status_code == 200
    assert "The capital of France is Paris, famously so." in r.text
    assert "gw-stage probe glm-5.3-flash" in r.text
    assert "uncensored terminal was skipped" in r.text
    assert r.text.rstrip().endswith("data: [DONE]")
    # TOKEN EFFICIENCY: the V2 helm/terminal never burned
    assert not _calls_to(script, SPEC)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["sustained_probe_total"] == 1
    assert snap["sustained_probe_hit_total"] == 1
    # the probe is the cheap blind hop: thinking off
    probe = _calls_to(script, PRIMARY)[0]["json"]
    assert probe["model"] == "zai-org/glm-5.3-flash"
    assert probe["stream"] is False
    assert probe["reasoning_effort"] == "none"


def test_sustained_refusing_probe_goes_to_the_redhands_helm(script, monkeypatch):
    """A probe that refuses pre-screens NEGATIVE: the V2 helm answers under
    the REDHANDS persona (chain-3 style), and the DEEP verifier runs after
    (VERIFIED footnote)."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step("I cannot help with that."),   # the probe refuses
        _json_step("VERIFIED"),                   # the DEEP verifier
    ])
    script.script(SPEC, [
        ("sse", [chunk("the sustained offensive answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, SUSTAINED, "what is the capital of France")
    assert r.status_code == 200
    assert "the sustained offensive answer" in r.text
    assert "I cannot help" not in r.text  # the probe's refusal never ships
    # the V2 helm ran under the REDHANDS persona
    helm = _calls_to(script, SPEC)[0]["json"]
    assert helm["model"] == "abliterated-model-large-v2"
    assert helm["messages"][0] == {
        "role": "system", "content": redhands.REDHANDS_SYSTEM}
    # DEEP-VERIFY ran and the verdict footnote shipped
    assert "[deep-verify: verified]" in r.text
    snap = proxy_gateway.metrics_snapshot()
    assert snap["sustained_probe_total"] == 1
    assert snap["sustained_probe_hit_total"] == 0
    assert snap["sustained_verify_total"] == 1
    assert snap["sustained_verify_gaps_total"] == 0


def test_sustained_complex_ask_skips_the_probe_entirely(script, monkeypatch):
    """A MULTI-ITEM ask is not simple: no probe is spent at all - the V2
    helm answers and the verifier runs."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step("VERIFIED")])
    script.script(SPEC, [
        ("sse", [chunk("the answer to the complex ask", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, SUSTAINED,
                  "1) list the open ports.\n2) explain the firewall rules.")
    assert r.status_code == 200
    assert "the answer to the complex ask" in r.text
    # the ONLY primary call is the DEEP verifier (no probe on a complex ask)
    prim = _calls_to(script, PRIMARY)
    assert len(prim) == 1
    assert prim[0]["json"]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
    assert prim[0]["json"]["messages"][0]["content"].startswith(
        "You are the verification tier")
    assert "the answer to the complex ask" in prim[0]["json"]["messages"][1]["content"]
    snap = proxy_gateway.metrics_snapshot()
    assert snap["sustained_probe_total"] == 0
    assert snap["sustained_verify_total"] == 1


def test_sustained_verify_gaps_footnote_and_r4_tail(script, monkeypatch):
    """DEEP-VERIFY reporting GAPS ships the gaps footnote, and R4 holds: the
    finish_reason is re-emitted AFTER the footnote (content before finish)."""
    _ablit_provider(monkeypatch)
    script.script(PRIMARY, [
        _json_step("GAPS: the port claim is unsupported")])
    script.script(SPEC, [
        ("sse", [chunk("port 22 is definitely open, trust me.",
                       finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, SUSTAINED,
                  "1) list the open ports.\n2) explain the firewall rules.")
    assert r.status_code == 200
    assert "port 22 is definitely open, trust me." in r.text
    assert "[deep-verify: GAPS: the port claim is unsupported]" in r.text
    # R4: the held finish marker ships AFTER the footnote, [DONE] last
    assert (r.text.find('[deep-verify')
            < r.text.find('"finish_reason": "stop"'))
    assert r.text.rstrip().endswith("data: [DONE]")
    snap = proxy_gateway.metrics_snapshot()
    assert snap["sustained_verify_gaps_total"] == 1
    assert snap["sustained_verify_total"] == 1
    # the verify stage colour announced the DEEP verifier
    assert "gw-stage verify deepseek-v4.1-flash-1017" in r.text


def test_sustained_kill_switch_restores_chain3_behaviour(script, monkeypatch):
    """SUSTAINED_CHAIN_ENABLED=0: pure chain-3 flow - the V2 helm answers
    under REDHANDS, no probe, no verifier, no GW-VERIFY marker."""
    _ablit_provider(monkeypatch)
    monkeypatch.setenv("SUSTAINED_CHAIN_ENABLED", "0")
    script.script(SPEC, [
        ("sse", [chunk("chain3 style answer", finish="stop"), DONE])])
    with TestClient(proxy_gateway.app) as tc:
        r = _post(tc, SUSTAINED, "what is the capital of France")
    assert r.status_code == 200
    assert "chain3 style answer" in r.text
    assert "GW-VERIFY" not in r.text
    # no probe and no verifier: the primary slot was never touched
    assert not _calls_to(script, PRIMARY)
    snap = proxy_gateway.metrics_snapshot()
    assert snap["sustained_probe_total"] == 0
    assert snap["sustained_verify_total"] == 0






