# One-shot: verify no secrets in what would be committed, then commit.
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
print(f"candidates to stage: {len(candidates)}")
leaks = []
for c in candidates:
    p = ROOT / c
    if p.is_file():
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in KEY.finditer(txt):
            frag = m.group(0)
            if "xxxx" in frag:
                continue  # placeholder tail of x's
            leaks.append((c, frag[:6] + "..." + frag[-4:]))
if leaks:
    print("KEY-BEARING FILES WOULD BE COMMITTED:")
    for c, k in leaks:
        print(f"  {c}: {k}")
    sys.exit(1)
print("no real keys in candidates - safe to commit")

r = subprocess.run(["git", "add", "-A"], cwd=str(ROOT))
if r.returncode:
    sys.exit(1)
msg = ("ZERO-REFUSAL LAW: full-reply judge at commit/[DONE]/finish points + "
       "creative verbs in the refusal core; W0-W3 remediation (parity gate, "
       "hub_ipc, key tooling, endpoint dedup); key-surface hygiene + .gitignore")
r = subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT),
                   capture_output=True, text=True)
print(r.stdout[-600:] or r.stderr[-600:])
sys.exit(r.returncode)
