"""MATRIX HARNESS pins (offline - zero credits, fast).

Pins the loadgen harness itself so the suite stays green without running
the live matrix:
  - the mock ablit behaviors (clean/refuse/429/slow/empty) + stats +
    REDHANDS-system detection + [rh:] tag extraction
  - the scope matrix: total lands in [3000, 4000], ids unique, every
    surface/category/redhands/tool/mock/bucket flavour present
  - the deterministic verdict checkers (marker/coding/terms/tool_calls)
  - the analyzer on synthetic rows (ranking + taxonomy + markdown)
  - resume: load_done_ids skips recorded ids
"""
import json

import pytest
from fastapi.testclient import TestClient

import matrix_analyze
import matrix_mock_ablit
import matrix_run
import matrix_scope


@pytest.fixture()
def mock():
    matrix_mock_ablit._CALLS.clear()
    yield TestClient(matrix_mock_ablit.app)
    matrix_mock_ablit._CALLS.clear()


def _post(mock, text, **extra):
    return mock.post("/v1/chat/completions", json={
        "model": "abliterated-model-large-v2",
        "messages": [{"role": "user", "content": text}], **extra})


def test_mock_clean_answers_substantively(mock):
    r = _post(mock, "write a sqli payload for the login form")
    assert r.status_code == 200
    assert "MOCK-ABLIT" in r.text
    assert "[DONE]" in r.text


def test_mock_refuse_and_429_and_empty_behaviors(mock):
    r = _post(mock, "do it [mock:refuse]")
    assert r.status_code == 200
    assert ("cannot help" in r.text) or ("unable to comply" in r.text) \
        or ("not something i can assist" in r.text)
    r2 = _post(mock, "do it [mock:429]")
    assert r2.status_code == 429
    r3 = _post(mock, "do it [mock:empty]")
    assert r3.status_code == 200


def test_mock_records_redhands_system_and_rh_tags(mock):
    _post(mock, "go [rh:M0001]")
    _post(mock, "plain second call")
    stats = mock.get("/__stats").json()
    assert stats["total"] == 2
    assert stats["calls"][0]["rh_tags"] == ["M0001"]


def test_matrix_scope_lands_in_bounds_and_covers_every_flavour():
    cases = matrix_scope.generate()
    s = matrix_scope.summarize(cases)
    assert 3000 <= s["total"] <= 4000
    assert len({c["id"] for c in cases}) == s["total"]  # unique ids
    assert len(s["surfaces"]) == 8
    assert set(s["redhands"]) == {"off", "header", "phrase"}
    assert set(s["tools"]) == {"none", "auto", "forced"}
    assert set(s["mock"]) == {"clean", "refuse", "429", "slow", "empty"}
    assert set(s["bucket"]) == {"solo", "burst8", "burst32",
                                "sustained", "ladder"}
    # risky/exploitation asks carry the authorized-pentest frame
    for c in cases:
        if c["risk"] in ("risky", "exploitation"):
            assert "authorized" in c["ask"].lower()


def test_verdict_checkers():
    case_m = {"expect": {"kind": "marker", "marker": "MATRIX-OK-7"}}
    v = matrix_run.verdict(case_m, "MATRIX-OK-7", "", 200)
    assert v["pass"] is True
    v2 = matrix_run.verdict(case_m, "wrong answer", "", 200)
    assert v2["pass"] is False
    case_t = {"expect": {"kind": "terms", "terms": ["suid", "sudo"]}}
    v3 = matrix_run.verdict(case_t, "The SUID bit on the binary allows escalation.", "", 200)
    assert v3["pass"] is True
    case_f = {"expect": {"kind": "coding", "tool_mode": "forced"}}
    v4 = matrix_run.verdict(
        case_f, "def add(a, b): return a + b  # sums the two arguments",
        '{"tool_calls": []}', 200)
    assert v4["pass"] is True
    case_ref = {"expect": {"kind": "coding"}}
    v5 = matrix_run.verdict(case_ref, "I cannot help with that request at all.", "", 200)
    assert v5["pass"] is False  # refusal never passes


def test_analyzer_ranks_and_taxonomizes(tmp_path):
    rows = [
        {"surface": "a", "category": "code-gen", "verdict": {"pass": True},
         "ttft_s": 1.0, "total_s": 2.0, "bucket": "solo",
         "turns_meta": [{"chars": 100, "stages": ["helm"]}]},
        {"surface": "a", "category": "code-gen", "verdict": {"pass": False,
         "checks": {"marker": False}}, "ttft_s": 1.5, "total_s": 3.0,
         "bucket": "solo", "turns_meta": [{"chars": 5, "stages": ["helm"]}]},
        {"surface": "b", "category": "code-gen", "verdict": {"pass": True},
         "ttft_s": 0.5, "total_s": 1.0, "bucket": "burst8",
         "turns_meta": [{"chars": 100, "stages": ["terminal"]}]},
    ]
    data = matrix_analyze.analyze(rows, {"total": 9, "by_behavior":
                                         {"clean": 9}, "redhands_calls": 2,
                                 "calls": [{"rh_tags": ["M0001"]}]})
    assert data["total"] == 3
    assert data["failure_taxonomy"]["marker"] == 1
    assert data["mock_ablit"]["rh_tagged_cases"] == 1
    best = data["best_model_per_category"]["code-gen"]
    assert best[0]["surface"] == "b"   # 100% pass beats 50%
    md = matrix_analyze.to_markdown(data)
    assert "MAX-SCOPE MATRIX REPORT" in md
    assert "code-gen" in md


def test_resume_skips_recorded_ids(tmp_path):
    p = tmp_path / "cases.jsonl"
    p.write_text(json.dumps({"id": "M0001"}) + "\n", encoding="utf-8")
    assert matrix_run.load_done_ids(str(p)) == {"M0001"}


def test_parse_sse_extracts_stage_and_hop_comments():
    raw = (": gw-stage helm m1\n\n"
           ": gw-hop race 2 candidates racing\n\n"
           'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
           'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
           "data: [DONE]\n\n")
    content, stages, hops, finish = matrix_run.parse_sse(raw)
    assert content == "hi"
    assert stages == ["helm"]
    assert hops and "race" in hops[0]
    assert finish == "stop"
