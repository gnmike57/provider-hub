"""ARSENAL - the hacking-tool surface behind the REDHANDS brain (roadmap 4).

The REDHANDS persona (redhands.py) is the BRAIN; this module is its HANDS:
a tightly-scoped execution surface for the classic offensive tools against
AUTHORIZED targets only. Design laws (mirroring the gateway's own):

  * ALLOWLIST OR NOTHING - a target is runnable only when its host is in
    ARSENAL_ALLOWED_TARGETS (default: loopback + the gx10 vuln-lab hosts,
    the deliberately-vulnerable practice range in .staging/vuln-lab/).
  * NO SHELL, EVER - commands are list-argv run via subprocess; every arg
    must match a conservative charset, so no injection surface exists.
  * BOUNDED - one hard timeout per run (ARSENAL_TIMEOUT_S, default 120);
    output is captured (capped) and returned, never streamed raw.
  * NEVER RAISES - run_tool() always returns a result dict; a missing
    binary, bad target or timeout is a structured error, not an exception
    in the request path.

Tools: nmap (port/service scan), sqlmap (SQLi), ffuf (web fuzz). The
operator extends the set by adding to TOOLS; the brain (chain-3 REDHANDS
helm / X-Max-Offense requests) decides WHAT to run - this surface decides
only whether it is ALLOWED.

Usage (via the gateway):
    POST /v1/arsenal/run  {"tool": "nmap", "target": "100.67.13.78:8100",
                           "args": ["-sV"], "timeout": 60}
    GET  /v1/arsenal/tools
Both are admin-authed (X-Admin-Key) and gated by ARSENAL_ENABLED=0.
"""
import os
import re
import subprocess
import time

__all__ = ["TOOLS", "allowed_hosts", "target_host", "validate_target",
           "build_command", "run_tool"]

# Every argv element must match this conservative charset (no shell is ever
# involved - list argv - but the belt-and-braces charset kills injection
# outright; dashes stay legal because legitimate flags need them).
_SAFE_ARG = re.compile(r"^[A-Za-z0-9._:/,@=%+~-]+$")
# A target is a host, host:port, or a URL.
_SAFE_TARGET = re.compile(
    r"^[A-Za-z0-9._-]+(?::[0-9]{1,5})?$"
    r"|^https?://[A-Za-z0-9._:/?=&%+~,-]+$")

# The authorized engagement range: loopback + the gx10 vuln-lab
# (.staging/vuln-lab/: juice-shop :8100, dvwa :8101, nginx :8102+, all on
# 100.67.13.78 tailnet / 192.168.0.230 LAN). Override with
# ARSENAL_ALLOWED_TARGETS="host1,host2,...".
DEFAULT_ALLOWED = "127.0.0.1,100.67.13.78,192.168.0.230,gx10.ayu-sidewinder.ts.net"

TOOLS = {
    "nmap": {
        "binary": "nmap",
        "description": "port + service scanner (e.g. args: -sV, -p 1-1000)",
        "kind": "host",
    },
    "sqlmap": {
        "binary": "sqlmap",
        "description": "SQL injection tester (target: the URL; --batch always added)",
        "kind": "url",
    },
    "ffuf": {
        "binary": "ffuf",
        "description": "web fuzzer (target: the URL; args must carry -w <wordlist>)",
        "kind": "url",
    },
}

MAX_OUTPUT = 200_000  # cap captured stdout/stderr per stream


def allowed_hosts():
    raw = os.getenv("ARSENAL_ALLOWED_TARGETS", DEFAULT_ALLOWED)
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def target_host(target: str) -> str:
    """'http://h:8100/x?y=1' / 'h:8100' / 'h' -> 'h' (lowercased)."""
    t = (target or "").strip()
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/", 1)[0]
    if t.count(":") == 1:  # ipv4 host:port (ipv6 stays whole - not a lab shape)
        t = t.rsplit(":", 1)[0]
    return t.strip().lower()


def validate_target(tool: str, target: str):
    """Returns None when the target is runnable, else the rejection reason."""
    t = (target or "").strip()
    if not t or not _SAFE_TARGET.match(t):
        return f"target {target!r} is not a host, host:port or URL"
    spec = TOOLS[tool]
    if spec["kind"] == "url" and "://" not in t:
        return f"{tool} needs a URL target (got {target!r})"
    host = target_host(t)
    if host not in allowed_hosts():
        return (f"target host {host!r} is not in ARSENAL_ALLOWED_TARGETS "
                f"({', '.join(sorted(allowed_hosts()))})")
    return None


def build_command(tool: str, target: str, extra_args=None):
    """List-argv for the tool. Returns (command, None) or (None, reason)."""
    if tool not in TOOLS:
        return None, f"unknown tool {tool!r} (known: {', '.join(sorted(TOOLS))})"
    err = validate_target(tool, target)
    if err:
        return None, err
    args = [str(a) for a in (extra_args or [])]
    for a in args:
        if not _SAFE_ARG.match(a):
            return None, f"argument {a!r} failed the safe-charset check"
    if tool == "nmap":
        cmd = ["nmap", "-Pn"]
        t = target.strip()
        port = None
        if "://" not in t and t.count(":") == 1:
            t, port = t.rsplit(":", 1)
        if port:
            cmd += ["-p", port]
        cmd += args + [t]
    elif tool == "sqlmap":
        cmd = ["sqlmap", "-u", target.strip(), "--batch"] + args
    else:  # ffuf
        if not any(a == "-w" or a.startswith("-w") for a in args):
            return None, "ffuf requires a wordlist (-w <path>) in args"
        cmd = ["ffuf", "-u", target.strip()] + args
    return cmd, None


def run_tool(tool: str, target: str, extra_args=None, timeout: float = 0.0):
    """Run one allowlisted tool. NEVER raises; returns a result dict:
    {ok, tool, target, command, stdout, stderr, returncode, duration_s,
    error}."""
    started = time.time()
    result = {"tool": tool, "target": target, "command": None,
              "stdout": "", "stderr": "", "returncode": None,
              "duration_s": 0.0, "ok": False, "error": ""}
    cmd, err = build_command(tool, target, extra_args)
    result["command"] = cmd
    if err:
        result["error"] = err
        return result
    timeout = float(timeout or 0) or float(os.getenv("ARSENAL_TIMEOUT_S", "120"))
    timeout = min(max(timeout, 5.0), 600.0)
    try:
        proc = subprocess.run(  # noqa: S603 - list argv, no shell
            cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        result["error"] = (f"{TOOLS[tool]['binary']!r} is not installed "
                           f"on this host (PATH lookup failed)")
        return result
    except subprocess.TimeoutExpired as exc:
        result["error"] = f"timed out after {timeout:.0f}s"
        out = exc.stdout or ""
        result["stdout"] = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        result["returncode"] = "timeout"
        result["duration_s"] = round(time.time() - started, 2)
        return result
    result["stdout"] = (proc.stdout or "")[:MAX_OUTPUT]
    result["stderr"] = (proc.stderr or "")[:MAX_OUTPUT]
    result["returncode"] = proc.returncode
    result["ok"] = proc.returncode == 0
    result["duration_s"] = round(time.time() - started, 2)
    return result
