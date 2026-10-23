"""Offline tests for the serve_endpoints family extraction (task 0007).

Covers tools/hive/serve_module.py, tools/hive/serve_endpoints.py,
tools/hive/serve_endpoints_gx10.py and the opt-in ENDPOINT_AUTH gate in
proxy_gateway.py. NO SERVERS ARE STARTED: subprocess.Popen is monkeypatched
with a recorder, so "launch" only records its argv/env. House style:
tmp_path/monkeypatch; every test scrubs the opt-in knobs from the environment
first so the defaults (open + launch-everything) are proven, not assumed.
"""

import dataclasses
import importlib.util
import io
import json
import os
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "serve_module_under_test",
    os.path.join(_ROOT, "tools", "hive", "serve_module.py"))
sm = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("serve_module_under_test", sm)
_SPEC.loader.exec_module(sm)

# The entrypoints import `serve_module` by name; tests import them by path,
# so the stub-registry seeding below puts a stub on sys.modules FIRST - the
# entrypoints' `import serve_module` then resolves to the stub, and
# `stub.EndpointConfig(...)` runs the stub's factory, not the real module's
# class (stub.factory = real class), keeping every object a real
# EndpointConfig while entrypoint constants (HIVE_URL/ROOT/UFO_ENV) stay
# genuinely per-entrypoint.
_HUB_DIR = os.path.join(_ROOT, "tools", "hive")

import proxy_gateway  # noqa: E402
from helpers import script  # noqa: E402,F401  (fixture)

# Opt-in knobs: scrubbed in EVERY test so unset == historical behaviour is
# exercised (and a stray exported value from the operator shell can never
# flip a default-behaviour test).
_KNOBS = ("ENDPOINT_AUTH", "ENDPOINT_DRY_RUN")


def _scrub(monkeypatch):
    for name in _KNOBS:
        monkeypatch.delenv(name, raising=False)


def _load_entrypoint(mod_name, file_name, stub):
    """Import an entrypoint by path with a stubbed serve_module name."""
    saved = sys.modules.get("serve_module")
    sys.modules["serve_module"] = stub
    try:
        spec = importlib.util.spec_from_file_location(
            mod_name, os.path.join(_HUB_DIR, file_name))
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(mod_name, mod)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved is not None:
            sys.modules["serve_module"] = saved
        else:
            sys.modules.pop("serve_module", None)


class _StubSM:
    """serve_module name-alias stub: forwards real attributes, overrides the
    EndpointConfig NAME with a factory returning real EndpointConfig objects."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, attr):
        return getattr(self._real, attr)

    def EndpointConfig(self, *a, **kw):
        return self._real.EndpointConfig(*a, **kw)


_REAL_SM = sm  # the by-path-loaded real module


def _serve_instances(entrypoint, stub):
    return [stub.EndpointConfig(name=c[0], port=c[1], primary_url=c[2],
                                model=c[3], hedged=c[4])
            for c in entrypoint.INSTANCES]


# --- opt-out back-compat shims: EndpointConfig(*instance5) unpacking ---------

def test_endpoint_config_still_unpacks_like_a_5tuple():
    cfg = sm.EndpointConfig(*("n", 9310, "u", "m", True))
    assert cfg == sm.EndpointConfig("n", 9310, "u", "m", True)
    assert cfg.hedged is True
    assert cfg.bind_host == "0.0.0.0"  # historical bind is the default
    assert cfg.dry_run is False


# --- parse_ufo_env / resolve_secret (env-first + loud legacy fallback) -------

def test_parse_ufo_env_parses_and_skips_comments(tmp_path):
    p = tmp_path / "ufo.env"
    p.write_text("# comment\n; also comment\n\nKEY= value \nEMPTY=\n",
                 encoding="utf-8")
    values = sm.parse_ufo_env(str(p))
    assert values["KEY"] == "value"
    assert values["EMPTY"] == ""
    assert "# comment" not in values


def test_parse_ufo_env_missing_file_is_empty_not_traceback(tmp_path):
    values = sm.parse_ufo_env(str(tmp_path / "nope.env"))
    assert values == {}


def test_resolve_secret_env_wins_over_file(monkeypatch, tmp_path):
    _scrub(monkeypatch)
    monkeypatch.setenv("HIVE_SECRET_KEY", "from-env")
    values = {"HIVE_SECRET_KEY": "from-file"}
    value, source = sm.resolve_secret("HIVE_SECRET_KEY", values, "x.env")
    assert value == "from-env"
    assert source == "process_env"


def test_resolve_secret_env_file_fallback_warns_loudly(monkeypatch, tmp_path, capsys):
    _scrub(monkeypatch)
    monkeypatch.delenv("HIVE_SECRET_KEY", raising=False)
    value, source = sm.resolve_secret("HIVE_SECRET_KEY",
                                      {"HIVE_SECRET_KEY": "from-file"}, "x.env")
    assert value == "from-file"
    assert source == "env_file"
    captured = capsys.readouterr()
    # loud warning on stderr; the VALUE itself never appears in any output
    assert "legacy fallback" in captured.err
    assert "from-file" not in captured.err
    assert "from-file" not in captured.out


def test_resolve_secret_missing_is_none_not_systemexit(monkeypatch):
    _scrub(monkeypatch)
    monkeypatch.delenv("HIVE_SECRET_KEY", raising=False)
    value, source = sm.resolve_secret("HIVE_SECRET_KEY", {}, "x.env")
    assert value is None
    assert source == "missing"


def test_empty_env_value_counts_as_unset(monkeypatch):
    _scrub(monkeypatch)
    monkeypatch.setenv("HIVE_SECRET_KEY", "")
    value, source = sm.resolve_secret("HIVE_SECRET_KEY", {}, "x.env")
    assert value is None
    assert source == "missing"

# --- plan(): --bind + ENDPOINT_DRY_RUN (additive, defaults preserved) --------

def test_plan_defaults_are_historical(monkeypatch):
    _scrub(monkeypatch)
    cfgs = sm.plan([], [sm.EndpointConfig("n", 9310, "u", "m", True)])
    assert cfgs[0].bind_host == "0.0.0.0"
    assert cfgs[0].dry_run is False


def test_plan_bind_flag_rebinds(monkeypatch):
    _scrub(monkeypatch)
    cfgs = sm.plan(["--bind", "127.0.0.1"],
                   [sm.EndpointConfig("n", 9310, "u", "m", False)])
    assert cfgs[0].bind_host == "127.0.0.1"


def test_plan_dry_run_env_is_opt_in(monkeypatch):
    _scrub(monkeypatch)
    monkeypatch.setenv("ENDPOINT_DRY_RUN", "1")
    cfgs = sm.plan([], [sm.EndpointConfig("n", 9310, "u", "m", False)])
    assert cfgs[0].dry_run is True


# --- launch(): env/argv parity (Popen monkeypatched, no servers started) -----

class _Proc:
    def __init__(self, argv, env, cwd):
        self.argv, self.env, self.cwd = argv, env, cwd
        self.pid, self.waited = 4242, False

    def wait(self):
        self.waited = True


@pytest.fixture()
def popen_recorder(monkeypatch, tmp_path):
    """Replace subprocess.Popen with a recorder; scrub the knobs + secret so
    every launch test starts from the documented default environment.

    The endpoints log dir is created inside tmp_path so launch's real
    makedirs + log-file open target the sandbox root (ROOT is monkeypatched
    to tmp_path per-test), never the repo. Stubbing makedirs to a no-op
    (the earlier form) made launch's open() fail with FileNotFoundError."""
    for name in _KNOBS + ("HIVE_SECRET_KEY",):
        monkeypatch.delenv(name, raising=False)
    captured = {}

    def _fake_popen(argv, *, cwd, env, stdout, stderr):
        captured["argv"], captured["env"], captured["cwd"] = list(argv), dict(env), cwd
        return _Proc(argv, env, cwd)

    monkeypatch.setattr(sm.subprocess, "Popen", _fake_popen)
    os.makedirs(os.path.join(str(tmp_path), "evals", "results"), exist_ok=True)
    return captured


def _cfg(port=9310, hedged=True):
    return sm.EndpointConfig("general (any name / raw id)", port,
                             "https://api-cdn.thehive.ai/api/v3/chat/completions",
                             "deepseek-ai/deepseek-v4.1-flash-1017", hedged)

def test_launch_env_dict_matches_pre_extraction_keys(popen_recorder, tmp_path):
    env_file = tmp_path / "ufo.env"
    env_file.write_text("HIVE_SECRET_KEY=literal-test\n", encoding="utf-8")
    proc = sm.launch(_cfg(), ufo_env=str(env_file), root=str(tmp_path),
                     display_host="100.113.176.84",
                     fallback_url="http://hub:4000/v1/chat/completions",
                     fallback_model="abliterated-model-large-v2")
    env = popen_recorder["env"]
    for name in ("PRIMARY_API_URL", "PRIMARY_API_KEY", "PRIMARY_MODEL",
                 "FALLBACK_API_URL", "FALLBACK_API_KEY", "FALLBACK_MODEL",
                 "HEDGE_MAX_TOKENS", "COMMIT_TOKENS", "HEDGE_LIVE_REASONING",
                 "AUDIT_LOG", "METRICS_PORT", "ACCEPT_TIMEOUT_S",
                 "YIELD_TIMEOUT_S", "PYTHONDONTWRITEBYTECODE",
                 "PYTHONIOENCODING"):
        assert name in env, f"missing env knob {name}"
    # A local "none" sentinel is correct for a local hub, but it MASKS the
    # built-in ABLITERATION_API_KEY in _specialist_key()'s chain - so a hosted
    # fallback URL must carry a real key, never "none".
    assert env["FALLBACK_API_KEY"] == "none"  # http://hub:4000 = local sentinel
    assert env["HEDGE_MAX_TOKENS"] == "4000"
    assert env["COMMIT_TOKENS"] == "10"  # hedged instance
    assert env["METRICS_PORT"] == "9410"
    assert env["ACCEPT_TIMEOUT_S"] == "120"
    assert env["YIELD_TIMEOUT_S"] == "600"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["AUDIT_LOG"].endswith("endpoints_9310_audit.jsonl")
    assert proc.waited is False


def test_launch_hosted_fallback_carries_the_abliteration_key(popen_recorder,
                                                            monkeypatch,
                                                            tmp_path):
    """A hosted fallback must NOT be handed the local "none" sentinel.

    "none" outranks the built-in ABLITERATION_API_KEY in
    proxy_gateway._specialist_key(), so the old :4000 pairing both 404'd on the
    model id and 401'd on auth. The hosted terminal needs the real key.
    """
    monkeypatch.setenv("HIVE_SECRET_KEY", "test-hive-key")
    monkeypatch.setenv("ABLITERATION_API_KEY", "ak_pooled_test")
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    sm.launch(_cfg(), ufo_env=str(tmp_path / "ufo.env"), root=str(tmp_path),
              display_host="100.113.176.84",
              fallback_url="https://api.abliteration.ai/v1/chat/completions",
              fallback_model="abliterated-model-large-v2")
    env = popen_recorder["env"]
    assert env["FALLBACK_API_KEY"] == "ak_pooled_test"


def test_launch_unhedged_disables_the_race(popen_recorder, monkeypatch,
                                           tmp_path):
    monkeypatch.setenv("HIVE_SECRET_KEY", "test-hive-key")  # env-first path
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    sm.launch(_cfg(hedged=False), ufo_env=str(tmp_path / "ufo.env"),
              root=str(tmp_path), display_host="h",
              fallback_url="http://hub:4000/v1/chat/completions",
              fallback_model="m")
    assert popen_recorder["env"]["COMMIT_TOKENS"] == "100000"


def test_launch_argv_uses_historical_default_bind(popen_recorder, monkeypatch,
                                                  tmp_path):
    monkeypatch.setenv("HIVE_SECRET_KEY", "test-hive-key")  # env-first path
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    sm.launch(_cfg(), ufo_env=str(tmp_path / "ufo.env"), root=str(tmp_path),
              display_host="h", fallback_url="u", fallback_model="m")
    argv = popen_recorder["argv"]
    assert argv[:4] == [sys.executable, "-m", "uvicorn", "proxy_gateway:app"]
    assert "--host" in argv and "0.0.0.0" in argv  # historical default
    assert "--port" in argv and "9310" in argv
    assert "--log-level" in argv and "warning" in argv


def test_launch_bind_flag_reaches_the_uvicorn_argv(popen_recorder, monkeypatch,
                                                   tmp_path):
    monkeypatch.setenv("HIVE_SECRET_KEY", "test-hive-key")  # env-first path
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    cfg = dataclasses.replace(_cfg(), bind_host="127.0.0.1")
    sm.launch(cfg, ufo_env=str(tmp_path / "ufo.env"), root=str(tmp_path),
              display_host="h", fallback_url="u", fallback_model="m")
    host = popen_recorder["argv"][popen_recorder["argv"].index("--host") + 1]
    assert host == "127.0.0.1"


def test_launch_non_hive_url_gets_none_key_without_env_file(
        popen_recorder, tmp_path):
    cfg = sm.EndpointConfig("team", 9316, "http://hub:4000/v1/chat/completions",
                            "team", False)
    sm.launch(cfg, ufo_env=str(tmp_path / "missing.env"), root=str(tmp_path),
              display_host="h", fallback_url="u", fallback_model="m")
    assert popen_recorder["env"]["PRIMARY_API_KEY"] == "none"


def test_launch_missing_secret_raises_systemexit_like_the_originals(
        popen_recorder, tmp_path):
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        sm.launch(_cfg(), ufo_env=str(tmp_path / "ufo.env"),
                  root=str(tmp_path), display_host="h",
                  fallback_url="u", fallback_model="m")


def test_launch_prints_launch_line_with_display_host(
        popen_recorder, tmp_path, capsys):
    # the plaintext file supplies the key (env was scrubbed by the fixture):
    # exercises the documented loud env-file fallback path
    (tmp_path / "ufo.env").write_text("HIVE_SECRET_KEY=test-hive-key\n",
                                      encoding="utf-8")
    sm.launch(_cfg(hedged=False), ufo_env=str(tmp_path / "ufo.env"),
              root=str(tmp_path), display_host="gx10.ayu-sidewinder.ts.net",
              fallback_url="u", fallback_model="m")
    out = capsys.readouterr().out
    assert "http://gx10.ayu-sidewinder.ts.net:9310/v1/chat/completions" in out
    assert "(hedged)" not in out

# --- serve_all(): full entrypoint loop with Popen + wait monkeypatched -------

@pytest.fixture()
def wait_recorder(monkeypatch, popen_recorder):
    """Serve_all also blocks on p.wait(); record which pids were waited on."""
    waits = []

    def _fake_popen(argv, *, cwd, env, stdout, stderr):
        popen_recorder["argv"], popen_recorder["env"] = list(argv), dict(env)
        p = _Proc(argv, env, cwd)
        p.wait = lambda: waits.append(p.pid)  # noqa: no real blocking in tests
        return p

    monkeypatch.setattr(sm.subprocess, "Popen", _fake_popen)
    return waits


def test_serve_all_no_flags_launches_every_instance_and_waits(
        wait_recorder, popen_recorder, tmp_path, capsys):
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    inst = [sm.EndpointConfig("a", 9310, "u", "m", True),
            sm.EndpointConfig("b", 9314, "u", "m", False)]
    rc = sm.serve_all([], instances=inst, ufo_env=str(tmp_path / "ufo.env"),
                      root=str(tmp_path), header="hdr:", display_host="h",
                      fallback_url="u", fallback_model="m")
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("hdr:\n")
    assert "all up; ctrl-c or kill the pids to stop" in out
    assert sorted(wait_recorder) == [4242, 4242]  # blocked on both children


def test_serve_all_dry_run_starts_nothing(monkeypatch, popen_recorder,
                                          tmp_path, capsys):
    _scrub(monkeypatch)
    monkeypatch.setenv("ENDPOINT_DRY_RUN", "1")
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    inst = [sm.EndpointConfig("a", 9310, "u", "m", True),
            sm.EndpointConfig("b", 9314, "u", "m", False)]
    rc = sm.serve_all([], instances=inst, ufo_env=str(tmp_path / "ufo.env"),
                      root=str(tmp_path), header="hdr:", display_host="h",
                      fallback_url="u", fallback_model="m")
    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out and "bind=0.0.0.0" in out
    assert "all up" not in out
    assert "argv" not in popen_recorder  # nothing was launched


def test_serve_all_announces_auth_warning_but_never_the_value(
        monkeypatch, popen_recorder, tmp_path, capsys):
    _scrub(monkeypatch)
    monkeypatch.setenv("ENDPOINT_AUTH", "sekrit-value")
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    inst = [sm.EndpointConfig("a", 9310, "u", "m", False)]
    sm.serve_all([], instances=inst, ufo_env=str(tmp_path / "ufo.env"),
                 root=str(tmp_path), header="hdr:", display_host="h",
                 fallback_url="u", fallback_model="m")
    err = capsys.readouterr().err
    assert "ENDPOINT_AUTH" in err
    assert "sekrit-value" not in err  # the knob VALUE never leaks


# --- both entrypoints: importability + pre-extraction shape ------------------

@pytest.fixture()
def hub_stub():
    return _StubSM(_REAL_SM)


def test_serve_endpoints_windows_entrypoint_imports_and_keeps_shape(hub_stub):
    se = _load_entrypoint("serve_endpoints_under_test", "serve_endpoints.py",
                          hub_stub)
    # the port family + models are unchanged (regression pin)
    assert [(c.port, c.name, c.model, c.hedged) for c in se.INSTANCES] == [
        (9314, "deepfrost max think", "deepfrost max think", False),
        (9315, "glmfrost max think", "glmfrost max think", False),
        (9316, "team (always-on)", "team", False),
        (9310, "general (any name / raw id)",
         "deepseek-ai/deepseek-v4.1-flash-1017", True),
    ]
    assert se.UFO_ENV.endswith("ufo.env")
    assert se.SPECIALIST == "abliterated-model-large-v2"
    assert callable(se.key) and callable(se.launch)


def test_serve_endpoints_gx10_entrypoint_imports_and_keeps_shape(hub_stub):
    gx = _load_entrypoint("serve_endpoints_gx10_under_test",
                          "serve_endpoints_gx10.py", hub_stub)
    assert [c.port for c in gx.INSTANCES] == [9314, 9315, 9316, 9310]
    # The worker slot must speak the model SPECIALIST names: pairing the legacy
    # gx10 :4000 catalog with abliterated-model-large-v2 was a guaranteed 404.
    assert gx.SPECIALIST == "abliterated-model-large-v2"
    assert gx.HUB_URL.endswith("/v1/chat/completions")
    assert "abliteration.ai" in gx.HUB_URL
    assert "ufo-galaxy" in gx.UFO_ENV and "hive_cleanpass" in gx.UFO_ENV
    assert callable(gx.key) and callable(gx.launch)


def test_entrypoint_key_reader_env_first(monkeypatch, hub_stub):
    se = _load_entrypoint("serve_endpoints_under_test", "serve_endpoints.py",
                          hub_stub)
    monkeypatch.setenv("HIVE_SECRET_KEY", "env-wins")
    assert se.key("HIVE_SECRET_KEY") == "env-wins"


def test_entrypoint_key_reader_file_fallback_still_works(
        monkeypatch, tmp_path, capsys, hub_stub):
    se = _load_entrypoint("serve_endpoints_under_test", "serve_endpoints.py",
                          hub_stub)
    _scrub(monkeypatch)
    monkeypatch.delenv("HIVE_SECRET_KEY", raising=False)
    fake_env = tmp_path / "ufo.env"
    fake_env.write_text("HIVE_SECRET_KEY=file-value\n", encoding="utf-8")
    monkeypatch.setattr(se, "UFO_ENV", str(fake_env))
    assert se.key("HIVE_SECRET_KEY") == "file-value"  # plaintext path intact
    err = capsys.readouterr().err
    assert "legacy fallback" in err
    assert "file-value" not in err  # the value never leaks into the warning


def test_entrypoint_key_reader_missing_raises_systemexit(monkeypatch, hub_stub,
                                                         tmp_path):
    se = _load_entrypoint("serve_endpoints_under_test", "serve_endpoints.py",
                          hub_stub)
    _scrub(monkeypatch)
    monkeypatch.delenv("HIVE_SECRET_KEY", raising=False)
    # sandbox UFO_ENV: without this the reader consults the real project
    # ufo.env (present on dev machines) and the "missing" case never fires
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    monkeypatch.setattr(se, "UFO_ENV", str(tmp_path / "ufo.env"))
    with pytest.raises(SystemExit):
        se.key("HIVE_SECRET_KEY")


def test_entrypoint_launch_wrapper_still_unpacks_5tuples(
        hub_stub, monkeypatch, popen_recorder, tmp_path):
    se = _load_entrypoint("serve_endpoints_under_test", "serve_endpoints.py",
                          hub_stub)
    (tmp_path / "ufo.env").write_text("", encoding="utf-8")
    monkeypatch.setattr(se, "UFO_ENV", str(tmp_path / "ufo.env"))
    monkeypatch.setattr(se, "ROOT", str(tmp_path))
    # pre-extraction positional unpacking of the old 5-tuples keeps working
    proc = se.launch(*("n", 9310, "http://hub:4000/v1/chat/completions",
                       "m", False))
    assert proc.pid == 4242


