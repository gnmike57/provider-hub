"""Live balance check via the hub's SIPHON agent."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _env_or_user_scope(name: str) -> str:
    """Process env first; else the persistent Windows User-scope value
    (HKCU\\Environment, where `setx` writes) - stale shells that started
    before the keys were installed still resolve them. On macOS/Linux the
    registry lookup is simply absent (ImportError) and the process env (or
    the shell profile) is the only source."""
    val = os.environ.get(name, "")
    if val:
        return val
    try:
        import winreg  # Windows only; macOS/Linux raises ImportError here
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val, _ = winreg.QueryValueEx(k, name)
    except (ImportError, OSError):
        val = ""
    return val or ""


# Abliteration keys come from the Windows user environment (installed
# 2026-10-21): ABLITERATION_API_KEY (chat) + ABLITERATION_ADMIN_KEY (admin).
# No secrets in source. Missing keys are reported as "unavailable" below,
# not fatal.
for _var in ("ABLITERATION_API_KEY", "ABLITERATION_ADMIN_KEY"):
    _val = _env_or_user_scope(_var)
    if _val:
        os.environ.setdefault(_var, _val)

import siphon  # noqa: E402


async def main():
    agent = siphon.SiphonAgent()
    print("querying org balance...", flush=True)
    org = await agent._org_balance()
    print("querying credits...", flush=True)
    creds = await agent._user_credits()
    print(f"Organization balance (real money): ${org:.2f}" if org is not None else "org balance: unavailable")
    print(f"Account credits: {creds:.1f}" if creds is not None else "credits: unavailable")
    print("Cards in inventory:", len(agent.cards.summary()))
    for c in agent.cards.summary():
        print("  -", c)


asyncio.run(main())
