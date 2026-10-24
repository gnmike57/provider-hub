# Running the system from a Mac (operator directive 2026-10-21)

The whole stack is cross-platform: every Python module is import-safe on
macOS/Linux (the Windows-registry key lookup no-ops via ImportError), and
`requirements.txt` contains only portable pins. Two ways to use it:

## Option A — remote via the gx10 (nothing to install)

Point any OpenAI-compatible client at the gx10 constellation router:

```
Base URL : http://gx10.ayu-sidewinder.ts.net:4001/v1   (tailnet only)
API key  : an Abliteration project key (see below)
Models   : GLMMAX>DEEP>ABLITV2L
           DEEPMAX>GLM>ABLITV2L
           ABLITV2L>SUB-GLM/DEEP      <- REDHANDS laws, uncensored brain
           GLMMAX>ABLIT-UNC>ABLITV2L  <- uncensored Abliterated middle
```

Works from curl, Cline, Agent TARS, UI-TARS Desktop, anything speaking
OpenAI chat completions. `X-Max-Offense: 1` on a request puts it under the
REDHANDS laws.

## Option B — copy it and run locally on the Mac

```bash
git clone <this repo> && cd provider-hub
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# keys: export in ~/.zshrc (no Windows registry on a Mac)
export ABLITERATION_ADMIN_KEY="sk_..."   # org admin key (operator-issued)
export ABLITERATION_API_KEY="ak_..."       # your inference key

bash launch_redhands_hub.sh          # hub on :9000, catalog = the 3 chains
curl -s localhost:9000/v1/models  # -> GLMMAX>…, DEEPMAX>…, ABLITV2L>…
```

The 2-key throughput pool file (`abliteration_pool.json`) is created next to
the repo root on first `ensure-pool` run and is gitignored — never committed.

## The API key factory (everyone: flak3dd, nick, Mac users)

`abliteration_keys.py` is the single source for Abliteration key lifecycle:

```bash
python3 abliteration_keys.py status          # redacted pool state
python3 abliteration_keys.py ensure-pool 2  # mint/verify the 2-key pool
python3 abliteration_keys.py revoke <id>     # revoke a project key

# mint a personal key for a new user / consumer:
python3 -c "from abliteration_keys import KeyFactory; \
  print(KeyFactory().create_key('mac-alice')['value'])"
```

- Needs only `ABLITERATION_ADMIN_KEY` in the environment (the org admin
  key, `sk_...`); on Windows it also falls back to the User-scope registry.
- On the gx10 it is deployed for **flak3dd** (and the router for **nick**):
  pool keys live in the router's `router.env` (`ABLIT_POOL_KEY_A/B`) and the
  llm-hub env, so every gx10 service egresses through the rotating pool.
- Pool maintenance is idempotent: re-running `ensure-pool 2` keeps live
  keys, re-mints revoked ones, and revokes surplus same-prefix keys.

## macOS notes

- `_env_or_user_scope()` in `audit_cards.py` / `check_balance.py` /
  `abliteration_keys.py`: process env first; the Windows registry lookup is
  `ImportError`-guarded, so on a Mac the shell profile is the only source.
- `launch_redhands_hub.sh` is the macOS/Linux twin of `launch_redhands_hub.ps1`
  (same env pins, `CONSTELLATION_ONLY=1`, uvicorn on :9000).
- The gx10 router (Linux) and the vision bridge are unchanged — Mac users
  reach them over the tailnet as normal.
