"""Shared core for the serve_endpoints family (task 0007 extraction).

`tools/hive/serve_endpoints.py` (Windows host) and
`tools/hive/serve_endpoints_gx10.py` (gx10 host) were copy-paste twins: their
INSTANCES tables, ufo.env key readers and uvicorn launchers differed only in
per-host constants. Both entrypoints now carry ONLY those constants and import
everything else from HERE (deduplication by EXTRACTION, never by removing an
entrypoint).

Additive contract: running either entrypoint with no new flags behaves exactly
as before - same ports, same models, the same env dict handed to
`uvicorn proxy_gateway:app`, the same 0.0.0.0 bind, the same wait-forever
loop. New behaviour is opt-in only:

  --bind HOST            bind the served uvicorn apps to HOST
                         (default: 0.0.0.0, the historical bind)
  ENDPOINT_AUTH=<value>  the served apps then answer 401 to
                         POST /v1/chat/completions without
                         'Authorization: Bearer <value>' (unset or 0 = open,
                         exactly as before; the value is never printed)
  ENDPOINT_DRY_RUN=1     plan the ports and print the launch lines but start
                         nothing (unset or 0 = start, as before)

Secrets: HIVE_SECRET_KEY is read env-FIRST (os.environ), falling back to the
plaintext ufo.env file the originals read. Every env-file fallback prints a
loud warning to stderr; the value itself is never printed.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys

# Opt-in knobs (hard law: unset/0 = the historical behaviour).
AUTH_ENV = "ENDPOINT_AUTH"
DRY_RUN_ENV = "ENDPOINT_DRY_RUN"
BIND_HOST_DEFAULT = "0.0.0.0"
SECRET_NAME = "HIVE_SECRET_KEY"


@dataclasses.dataclass(frozen=True)
class EndpointConfig:
    """One published port: what to launch and what to tell the gateway."""

    name: str
    port: int
    primary_url: str
    model: str
    hedged: bool
    bind_host: str = BIND_HOST_DEFAULT
    dry_run: bool = False


def parse_ufo_env(path: str) -> dict:
    """KEY=VALUE lines of a ufo.env file -> dict; comments/blanks skipped.

    A missing file parses as {} (the caller decides whether a missing key is
    fatal) - this replaces the raw FileNotFoundError traceback the copies
    raised while keeping the same end state for a healthy file.
    """
    values = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                stripped = line.strip()
                if (not stripped or stripped.startswith("#")
                        or stripped.startswith(";") or "=" not in stripped):
                    continue
                key, _, value = stripped.partition("=")
                values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values


def resolve_secret(name, values, env_file):
    """Env-first secret lookup: os.environ wins, then the plaintext file.

    Returns (value, source) with source one of "process_env", "env_file",
    "missing"; an empty process-env value counts as unset. The env-file
    fallback is the legacy path - it still works (the plaintext path stays
    functional) but announces itself loudly on stderr. The VALUE is never
    printed.
    """
    value = os.environ.get(name)
    if value:
        return value, "process_env"
    value = values.get(name)
    if value:
        print(f"[warn] {name}: using the plaintext value from {env_file}; "
              f"export {name} in the environment instead (env wins, the file "
              f"is the legacy fallback)", file=sys.stderr)
        return value, "env_file"
    return None, "missing"


def parse_args(argv):
    """CLI surface: --bind is the only flag (additive; default = historical)."""
    parser = argparse.ArgumentParser(
        description="publish per-model gateway endpoints (shared core)")
    parser.add_argument("--bind", default=None, metavar="HOST",
                        help="host for the served uvicorn apps "
                             "(default: the entrypoint's historical bind)")
    return parser.parse_args(argv)


def plan(argv, instances, default_bind=BIND_HOST_DEFAULT):
    """Resolve --bind + ENDPOINT_DRY_RUN against the host's INSTANCES table.

    Pure (no I/O, no processes): returns the entrypoint's configs with the
    effective bind host and dry-run flag filled in. With no flags/env the
    table is the historical one (0.0.0.0, launch everything). An empty/0
    ENDPOINT_DRY_RUN keeps the launch-everything default.
    """
    args = parse_args(argv)
    dry_raw = os.environ.get(DRY_RUN_ENV, "")
    dry = bool(dry_raw) and dry_raw != "0"
    bind = args.bind or default_bind
    return [dataclasses.replace(c, bind_host=bind, dry_run=dry)
            for c in instances]


def launch(cfg, *, ufo_env, root, display_host, fallback_url, fallback_model,
           stdout=None):
    """Start one `uvicorn proxy_gateway:app` child with the gateway env dict.

    The env dict is the one the copies built (same knobs, same audit/metrics/
    log paths, same COMMIT_TOKENS semantics), plus the effective bind host.
    The Hive key is resolved env-first with the plaintext file as the loud
    legacy fallback.  stdout defaults to sys.stdout at CALL time (a def-time
    default freezes the interpreter's stdout at import and breaks capture).
    """
    if stdout is None:
        stdout = sys.stdout
    env = dict(os.environ)
    primary_key = "none"
    if "thehive" in cfg.primary_url:
        values = parse_ufo_env(ufo_env)
        primary_key, _source = resolve_secret(SECRET_NAME, values, ufo_env)
        if primary_key is None:
            raise SystemExit(f"{SECRET_NAME} not found in {ufo_env} "
                             f"(and not in the process environment)")
    # Worker/fallback credential. "none" is the LOCAL-hub sentinel (send no
    # Authorization header); a hosted fallback such as Abliteration.ai needs a
    # real key, otherwise _specialist_key() resolves "none" FIRST and masks the
    # built-in ABLITERATION_API_KEY - a guaranteed 401 on every divert.
    fallback_key = "none"
    if "abliteration.ai" in (fallback_url or ""):
        fallback_key = os.getenv("ABLITERATION_API_KEY") or "none"
    env.update({
        "PRIMARY_API_URL": cfg.primary_url,
        "PRIMARY_API_KEY": primary_key,
        "PRIMARY_MODEL": cfg.model,
        "FALLBACK_API_URL": fallback_url,
        "FALLBACK_API_KEY": fallback_key,
        "FALLBACK_MODEL": fallback_model,
        "HEDGE_MAX_TOKENS": "4000",
        "COMMIT_TOKENS": "10", "HEDGE_LIVE_REASONING": "1",
        "AUDIT_LOG": os.path.join(root, "evals", "results",
                                  f"endpoints_{cfg.port}_audit.jsonl"),
        "METRICS_PORT": str(cfg.port + 100),
        "ACCEPT_TIMEOUT_S": "120", "YIELD_TIMEOUT_S": "600",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
    })
    if not cfg.hedged:
        env["COMMIT_TOKENS"] = "100000"  # effectively no speculative race
    log_dir = os.path.join(root, "evals", "results")
    os.makedirs(log_dir, exist_ok=True)  # first-run robustness (additive)
    logf = open(os.path.join(log_dir, f"endpoints_{cfg.port}.log"),
                "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "proxy_gateway:app",
         "--host", cfg.bind_host, "--port", str(cfg.port),
         "--log-level", "warning"],
        cwd=root, env=env, stdout=logf, stderr=subprocess.STDOUT)
    print(f"  {cfg.name:18s} pid={proc.pid:6d} "
          f"http://{display_host}:{cfg.port}/v1/chat/completions"
          f"{'  (hedged)' if cfg.hedged else ''}", file=stdout)
    return proc


def launch_all(cfgs, *, ufo_env, root, display_host, fallback_url,
               fallback_model, stdout=None):
    """Launch every planned instance, in table order."""
    if stdout is None:
        stdout = sys.stdout
    return [launch(cfg, ufo_env=ufo_env, root=root, display_host=display_host,
                   fallback_url=fallback_url, fallback_model=fallback_model,
                   stdout=stdout)
            for cfg in cfgs]


def serve_all(argv, *, instances, ufo_env, root, header, display_host,
              fallback_url, fallback_model, default_bind=BIND_HOST_DEFAULT,
              stdout=None):
    """Plan, warn on opt-in knobs, launch every instance, wait forever.

    With no flags/env this is the historical entrypoint behaviour: header
    line, one launch line per port, "all up", then block on the children.
    --bind rebinds, ENDPOINT_DRY_RUN=1 prints the plan and starts nothing,
    ENDPOINT_AUTH arms the 401 gate in proxy_gateway (announced on stderr).
    """
    if stdout is None:
        stdout = sys.stdout
    cfgs = plan(argv, instances, default_bind=default_bind)
    auth = os.environ.get(AUTH_ENV, "")
    if auth and auth != "0":
        print(f"[warn] {AUTH_ENV} is set: every served app now answers 401 to "
              "POST /v1/chat/completions without "
              "'Authorization: Bearer <ENDPOINT_AUTH>' (the value is never "
              "printed)", file=sys.stderr)
    print(header, file=stdout)
    procs = []
    for cfg in cfgs:
        if cfg.dry_run:
            print(f"  [dry-run] {cfg.name:18s} would serve "
                  f"http://{display_host}:{cfg.port}/v1/chat/completions "
                  f"bind={cfg.bind_host}"
                  f"{'  (hedged)' if cfg.hedged else ''}", file=stdout)
            continue
        procs.append(launch(cfg, ufo_env=ufo_env, root=root,
                            display_host=display_host,
                            fallback_url=fallback_url,
                            fallback_model=fallback_model, stdout=stdout))
    if procs:
        print("all up; ctrl-c or kill the pids to stop", file=stdout)
        for p in procs:
            p.wait()
    else:
        print("dry-run: no processes started", file=stdout)
    return 0

