# Key-free commit gate, round 3.
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r"\b(?:ak_|sk_|cat_)[A-Za-z0-9\-_]{20,}")

out = subprocess.run(["git", "add", "-An"], capture_output=True, text=True,
                    cwd=str(ROOT)).stdout
candidates = [ln[4:].strip().strip("'\"") for ln in out.splitlines()
              if ln.startswith("add ")]
print(f"candidates: {len(candidates)}")
leaks = []
for c in candidates:
    p = ROOT / c
    if p.is_file():
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in KEY.finditer(txt):
            if "xxxx" in m.group(0):
                continue
            leaks.append((c, m.group(0)[:6]))
if leaks:
    print("KEY-BEARING:")
    for c, k in leaks:
        print(f"  {c}: {k}...")
    sys.exit(1)
print("clean - committing")
subprocess.run(["git", "add", "-A"], cwd=str(ROOT))
msg = ("T-A/B/C/D/E: multilingual refusal cores + COMPLETION_STRICT + "
       "is_multi_item_ask; org-burst bench + 4-key minted abliteration pool; "
       "logprob presignal + conversation stickiness; chains RACE/CONDUCTOR/"
       "SUSTAINED; AUTO_TEAM gate + /v1/verify RARV-C surface")
r = subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT),
                   capture_output=True, text=True)
print((r.stdout or r.stderr)[-400:])
sys.exit(r.returncode)
