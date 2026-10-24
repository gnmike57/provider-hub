"""T5.2 secrets hygiene: the committed launchers stay free of provider keys.

Pins (ledger T5.2 edit #5): launch_redhands_hub.ps1 + launch_redhands_hub.sh must
never contain sk-…/ak_… provider literals or "Bearer <token>" strings. The
deliberate local ops config (Fernet ENCRYPTION_KEY, ADMIN_API_KEY) is the
W2-committed exception and is NOT matched by these patterns.
"""

import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),   # OpenAI-style keys
    re.compile(r"\bak_[A-Za-z0-9_\-]{6,}"), # Abliteration ak_ keys
    re.compile(r"Bearer\s+[A-Za-z0-9_\-]{12,}"),  # pasted Authorization headers
]


@pytest.mark.parametrize("launcher", ["launch_redhands_hub.ps1", "launch_redhands_hub.sh"])
def test_launcher_is_key_free(launcher):
    path = os.path.join(REPO, launcher)
    if not os.path.exists(path):
        pytest.skip(f"{launcher} not present")
    text = open(path, encoding="utf-8", errors="replace").read()
    for pattern in SECRET_PATTERNS:
        hits = pattern.findall(text)
        assert not hits, f"{launcher} leaks {hits[:2]} (pattern {pattern.pattern})"


def test_probe_scripts_stay_untracked():
    """F18: the /v1/computer probe helpers held a live admin key on disk.
    They must remain UNTRACKED - if anyone ever `git add`s them, this pin
    fails and forces a secrets review before the key material ships."""
    import subprocess

    for name in ("_probe_computer.py", "_probe_computer.ps1"):
        r = subprocess.run(
            ["git", "-C", REPO, "ls-files", "--error-unmatch", name],
            capture_output=True, text=True)
        assert r.returncode != 0, (
            f"{name} is git-tracked; it embedded a live admin key (F18) - "
            "remove it from the index or scrub the key first")
