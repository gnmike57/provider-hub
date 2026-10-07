"""Publish per-model gateway endpoints on the gx10 tailnet.

Runs on gx10 (100.67.13.78 / gx10.ayu-sidewinder.ts.net):
  9311  deepfrost          -> Hive deepseek-ai/deepseek-v4.1-flash  (hedged, worker: local CyberFrost)
  9312  glmfrost           -> Hive zai-org/glm-5.3-flash           (hedged, worker: local CyberFrost)
  9313  cyberfrost         -> local CYBER-FROST-3.8-EXL3-SAGE-3.87bpw (no hedge)
  9310  (general)          -> any id in the body; hedge worker = local CyberFrost
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# gx10 local hub (TabbyAPI on :8900, also :4000 via llm_hub.py)
HUB_URL = "http://127.0.0.1:4000/v1/chat/completions"
HIVE_URL = "https://api-cdn.thehive.ai/api/v3/chat/completions"
SPECIALIST = "CYBER-FROST-3.8-EXL3-SAGE-3.87bpw"

INSTANCES = [
    ("deepfrost", 9311, HIVE_URL, "deepseek-ai/deepseek-v4.1-flash", True),
    ("glmfrost", 9312, HIVE_URL, "zai-org/glm-5.3-flash", True),
    ("cyberfrost", 9313, HUB_URL, SPECIALIST, False),
    ("general (any Frost name / raw id)", 9310, HIVE_URL,
     "deepseek-ai/deepseek-v4.1-flash", True),
]


def key(name):
    # Read from gx10's ufo.env
    ufo_env = os.path.join(os.path.expanduser("~"), "ufo-galaxy", "hive_cleanpass", "ufo.env")
    for line in io.open(ufo_env, encoding="utf-8", errors="ignore"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{name} not found in {ufo_env}")


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
        env["COMMIT_TOKENS"] = "100000"
    logf = io.open(os.path.join(ROOT, "evals", "results", f"endpoints_{port}.log"),
                   "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "proxy_gateway:app", "--host", "0.0.0.0",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
    print(f"  {name:18s} pid={proc.pid:6d} http://gx10.ayu-sidewinder.ts.net:{port}/v1/chat/completions"
          f"{'  (hedged)' if hedged else ''}")
    return proc


if __name__ == "__main__":
    print("gx10 provider-hub endpoints (0.0.0.0, tailnet gx10.ayu-sidewinder.ts.net):")
    procs = [launch(*inst) for inst in INSTANCES]
    print("all up; ctrl-c or kill the pids to stop")
    for p in procs:
        p.wait()