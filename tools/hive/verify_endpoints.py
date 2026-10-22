"""Probe every published endpoint and print a PASS/FAIL matrix.

Two families of endpoint make up the hub's public surface:

  Gateway routes (proxy_gateway.py, the "hub" itself):
    GET  /healthz                liveness + effective config
    GET  /v1/models              OpenAI model list (Frost names, incl. max-think)
    GET  /metrics                Prometheus text
    POST /v1/chat/completions    SSE chat (streaming)
    POST /v1/execute             deterministic assembly

  Per-model ports (FROST_REGISTRY / tools/hive/serve_endpoints.py):
    9310 frost-general   9314 deepfrost max think   9315 glmfrost max think
    9316 team (always-on surface, V2 Large terminal - serve_endpoints.py)

Every port runs the SAME app, so its /healthz and /v1/models answer without
touching an upstream - a cheap liveness+shape probe. The chat probe is a real
(but tiny) streaming call; pass --skip-chat to omit it.

Usage:
  python tools/hive/verify_endpoints.py                       # hub on :9000
  python tools/hive/verify_endpoints.py --base http://127.0.0.1:9000
  python tools/hive/verify_endpoints.py --ports-host 127.0.0.1
  python tools/hive/verify_endpoints.py --skip-chat           # no upstream spend
  python tools/hive/verify_endpoints.py --fast                # liveness-only:
      # --fast implies --skip-chat/--skip-execute and caps --timeout at 2.0s
      # unless --timeout is given explicitly; a quick "is it all up" sweep.

Exit code 0 only when every probed endpoint passes.
"""
import argparse
import json
import urllib.error
import urllib.request

PORTS = [
    (9310, "frost-general"),
    (9314, "deepfrost max think"),
    (9315, "glmfrost max think"),
    (9316, "team (always-on)"),
]

RESULT = []  # (name, ok, detail)


def _get(url, timeout):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _post(url, body, timeout, headers=None):
    data = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data, hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def record(name, ok, detail):
    RESULT.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


# Per-request timeout defaults: the historical 8.0s default (DEFAULT_TIMEOUT)
# and the --fast preset's tighter cap (FAST_TIMEOUT). --timeout always wins.
DEFAULT_TIMEOUT = 8.0
FAST_TIMEOUT = 2.0


def _apply_fast(args) -> None:
    """Apply the --fast preset IN PLACE (liveness-only sweep).

    Semantics: --fast implies --skip-chat and --skip-execute (no upstream
    spend), and shortens the per-request timeout to FAST_TIMEOUT (2.0s) - but
    only when --timeout was left at its default (DEFAULT_TIMEOUT, 8.0s), so an
    explicit --timeout 30 always wins. Purely additive: without --fast this is
    a no-op and every probe behaves exactly as before.
    """
    if not getattr(args, "fast", False):
        return
    if getattr(args, "timeout", DEFAULT_TIMEOUT) == DEFAULT_TIMEOUT:
        args.timeout = FAST_TIMEOUT
    args.skip_chat = True
    args.skip_execute = True


def probe_healthz(base, timeout):
    try:
        status, raw = _get(base + "/healthz", timeout)
        doc = json.loads(raw)
        cfg = doc.get("config", {})
        record(base + " /healthz", status == 200 and doc.get("ok") is True,
               f"200 ok={doc.get('ok')} primary={cfg.get('primary_model')}")
    except Exception as exc:  # noqa: BLE001 - network probe, report anything
        record(base + " /healthz", False, f"{type(exc).__name__}: {exc}")


def probe_models(base, timeout):
    try:
        status, raw = _get(base + "/v1/models", timeout)
        data = json.loads(raw).get("data", [])
        ids = [m.get("id") for m in data]
        has_flag = all("max_think" in m for m in data)
        record(base + " /v1/models", status == 200 and bool(data),
               f"200 {len(data)} models max_think_flag={has_flag} ids={ids}")
    except Exception as exc:  # noqa: BLE001
        record(base + " /v1/models", False, f"{type(exc).__name__}: {exc}")


def probe_metrics(base, timeout):
    try:
        status, raw = _get(base + "/metrics", timeout)
        text = raw.decode("utf-8", "replace")
        record(base + " /metrics", status == 200 and "requests_total" in text,
               f"200 {len(text)} bytes requests_total={'requests_total' in text}")
    except Exception as exc:  # noqa: BLE001
        record(base + " /metrics", False, f"{type(exc).__name__}: {exc}")


def probe_chat(base, timeout, model="", extra=None):
    body = {"messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
            "max_tokens": 64, "stream": True}
    if model:
        body["model"] = model
    if extra:
        body.update(extra)
    label = f"{base} POST /v1/chat/completions" + (f" [{model}]" if model else "")
    try:
        status, raw = _post(base + "/v1/chat/completions", body, timeout)
        text = raw.decode("utf-8", "replace")
        saw_data = "data:" in text
        saw_done = "[DONE]" in text
        record(label, status == 200 and saw_data,
               f"200 data={saw_data} done={saw_done} {len(text)}B")
    except urllib.error.HTTPError as exc:
        record(label, False, f"HTTP {exc.code}: {exc.read()[:200]!r}")
    except Exception as exc:  # noqa: BLE001
        record(label, False, f"{type(exc).__name__}: {exc}")


def probe_execute(base, timeout):
    body = {"messages": [{"role": "user", "content": "echo ok"}]}
    try:
        status, raw = _post(base + "/v1/execute", body, timeout)
        doc = json.loads(raw)
        record(base + " POST /v1/execute", status == 200 and isinstance(doc, dict),
               f"200 keys={sorted(doc)[:6]}")
    except urllib.error.HTTPError as exc:
        # 501 = assembly intentionally disabled; that is a defined answer.
        record(base + " POST /v1/execute", exc.code == 501,
               f"HTTP {exc.code} (501 = disabled)")
    except Exception as exc:  # noqa: BLE001
        record(base + " POST /v1/execute", False, f"{type(exc).__name__}: {exc}")


def probe_port(host, port, name, timeout):
    base = f"http://{host}:{port}"
    try:
        status, raw = _get(base + "/v1/models", timeout)
        ids = [m.get("id") for m in json.loads(raw).get("data", [])]
        record(f"{base} [{name}] /v1/models", status == 200 and bool(ids),
               f"200 {len(ids)} models")
    except Exception as exc:  # noqa: BLE001
        record(f"{base} [{name}] /v1/models", False, f"{type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:9000", help="hub gateway base URL")
    ap.add_argument("--ports-host", default="", help="host for the per-model ports (empty = skip)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help="per-request timeout (s)")
    ap.add_argument("--skip-chat", action="store_true", help="skip the live chat probe")
    ap.add_argument("--skip-execute", action="store_true", help="skip the /v1/execute probe")
    ap.add_argument("--skip-ports", action="store_true", help="skip the per-model port probes")
    ap.add_argument("--fast", action="store_true",
                    help="liveness-only sweep: implies --skip-chat/--skip-execute and "
                         "defaults --timeout to 2.0s unless --timeout is given")
    args = ap.parse_args()
    _apply_fast(args)

    base = args.base.rstrip("/")
    print(f"== hub gateway: {base} ==")
    probe_healthz(base, args.timeout)
    probe_models(base, args.timeout)
    probe_metrics(base, args.timeout)
    if not args.skip_execute:
        probe_execute(base, args.timeout)
    if not args.skip_chat:
        probe_chat(base, args.timeout, model="")
        probe_chat(base, args.timeout, model="deepfrost max think")

    if args.ports_host and not args.skip_ports:
        print(f"== per-model ports on {args.ports_host} ==")
        for port, name in PORTS:
            probe_port(args.ports_host, port, name, args.timeout)

    passed = sum(1 for _, ok, _ in RESULT if ok)
    total = len(RESULT)
    print(f"\n{passed}/{total} endpoints PASS")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())




