"""Publish per-model gateway endpoints on the tailnet (one port per model).

Any peer on the tailnet can then call a "special endpoint" per model, with the
model field optional (the port already defaults it):

  9311  deepfrost          -> Hive deepseek-ai/deepseek-v4.1-flash  (hedged, worker: CYBER-FROST)
  9312  glmfrost           -> Hive zai-org/glm-5.3-flash           (hedged, worker: CYBER-FROST)
  9313  cyberfrost         -> gx10 hub CYBER-FROST-3.8-EXL3-SAGE-3.87bpw (no hedge)
  9314  deepfrost max think -> Hive deepseek-ai/deepseek-v4.1-flash (max-think, no hedge)
  9315  glmfrost max think  -> Hive zai-org/glm-5.3-flash          (max-think, no hedge)
  9310  (general)          -> any id in the body; hedge worker = CYBER-FROST

All of them accept any model id in the body as an override, and `"hedge": true`
forces the speculative dual-dispatch. Secrets stay in ufo.env; never printed.
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
UFO_ENV = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ufo.env"

HIVE_URL = "https://api-cdn.thehive.ai/api/v3/chat/completions"
HUB_URL = "http://100.67.13.78:4000/v1/chat/completions"
SPECIALIST = "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"

INSTANCES = [
    ("deepfrost", 9311, HIVE_URL, "deepseek-ai/deepseek-v4.1-flash", True),
    ("glmfrost", 9312, HIVE_URL, "zai-org/glm-5.3-flash", True),
    ("cyberfrost", 9313, HUB_URL, SPECIALIST, False),
    # Max-think ports default the max-think NAME (not the raw upstream id):
    # the gateway recognises it and injects the reasoning knobs itself. The
    # race is disabled at the env layer too (COMMIT_TOKENS=100000) - the
    # gateway already skips hedging for max-think names, this keeps the
    # process honest if the name is ever overridden in a request body.
    ("deepfrost max think", 9314, HIVE_URL, "deepfrost max think", False),
    ("glmfrost max think", 9315, HIVE_URL, "glmfrost max think", False),
    ("general (any Frost name / raw id)", 9310, HIVE_URL,
     "deepseek-ai/deepseek-v4.1-flash", True),
]

# NOTE: 9301 is owned by the ufo bridge (uvicorn fails to bind with winerror
# 10048 and the endpoint silently does not exist) - never publish there.


def key(name):
    for line in io.open(UFO_ENV, encoding="utf-8", errors="ignore"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{name} not found in {UFO_ENV}")


def launch(name, port, primary_url, model, hedged):
    env = dict(os.environ)
    env.update({
        "PRIMARY_API_URL": primary_url,
        "PRIMARY_API_KEY": key("HIVE_SECRET_KEY") if "thehive" in primary_url else "none",
        "PRIMARY_MODEL": model,
        "FALLBACK_API_URL": HUB_URL,
        "FALLBACK_API_KEY": "none",
        "FALLBACK_MODEL": SPECIALIST,
        "HEDGE_MAX_TOKENS": "4000",
        "COMMIT_TOKENS": "10", "HEDGE_LIVE_REASONING": "1",
        "AUDIT_LOG": os.path.join(ROOT, "evals", "results", f"endpoints_{port}_audit.jsonl"),
        "METRICS_PORT": str(port + 100),
        "ACCEPT_TIMEOUT_S": "120", "YIELD_TIMEOUT_S": "600",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
    })
    if not hedged:
        env["COMMIT_TOKENS"] = "100000"  # effectively no speculative race
    logf = io.open(os.path.join(ROOT, "evals", "results", f"endpoints_{port}.log"),
                   "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "proxy_gateway:app", "--host", "0.0.0.0",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
    print(f"  {name:18s} pid={proc.pid:6d} http://100.113.176.84:{port}/v1/chat/completions"
          f"{'  (hedged)' if hedged else ''}")
    return proc


if __name__ == "__main__":
    print("provider-hub endpoints (0.0.0.0, tailnet 100.113.176.84):")
    procs = [launch(*inst) for inst in INSTANCES]
    print("all up; ctrl-c or kill the pids to stop")
    for p in procs:
        p.wait()

