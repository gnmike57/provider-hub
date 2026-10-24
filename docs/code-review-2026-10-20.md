# Provider-Hub code review — 2026-10-20

**Scope:** every hand-written runtime file in the repository root: 14 Python
modules, 4 PowerShell scripts, 1 HTML UI, plus the dependency/config surface.
**Method:** full read of each file, `py_compile`, `ruff 0.16.7`,
`mypy 2.3.1`, `pyflakes`, complexity analysis (`C901`), the full eval suite
(`py -3.12 -m pytest evals/ -q --ignore=evals/results`), a live `/healthz` +
`/metrics` probe, a secrets scan, and `git` tracking/history checks.
**Baseline:** 21 failed, 291 passed, 3 skipped. `py_compile` clean.

## Grading rubric

| Axis | Weight | What it measures |
|---|---|---|
| Correctness | 30 | Does it do what the docstring/contract says, including edge cases? |
| Reliability | 20 | Failure handling, state ownership, test isolation, observability. |
| Security | 25 | Secrets, authn/authz, data at rest, input trust, blast radius. |
| Architecture | 15 | Boundaries, single source of truth, coupling, complexity. |
| Readability | 10 | Naming, comments, lint/type cleanliness, doc accuracy. |

## Overall: **61 / 100 — structurally strong, operationally unsafe**

The routing core (`routing_patterns`, `ingress_assembler`,
`context_formatter`, `speculative_hedge`) is genuinely well designed and
unusually well documented. The document's design rules are real and mostly
enforced. But the repository currently ships **live provider secrets**, a
**card-charging agent that is on by default and stores PAN+CVV in plaintext**,
several **unauthenticated money-moving endpoints**, and a **red test baseline
caused by an unfinished divert rewrite**. None of those are style issues; they
are stop-the-line issues.

## Scorecard

| # | File | Lines | Grade | One-line verdict |
|---|---|---:|---:|---|
| 1 | `routing_patterns.py` | 530 | **88** | Best file in the repo: one source of truth, calibrated, tests pin it. |
| 2 | `conftest.py` | 25 | **88** | Small, correct, well-explained shim. |
| 3 | `ingress_assembler.py` | 177 | **86** | Fail-closed assembly and hashed audit records; audit sink needs rotation. |
| 4 | `open_control_room.ps1` | 30 | **85** | Correct idempotent launcher; relies on a 200-only health check. |
| 5 | `context_formatter.py` | 146 | **84** | Clear 4-stage contract; `assert_clean` can raise into the stream. |
| 6 | `watchdog_redhands_hub.ps1` | 229 | **82** | Real supervisor design (mutex, budget, cooldown); health is liveness-only. |
| 7 | `ask.py` | 99 | **80** | Useful CLI; hand-rolled arg parsing, no timeout configurability. |
| 8 | `providers.py` | 507 | **78** | Clean data layer; plaintext keys + silent env fallback are dangerous. |
| 9 | `control_room.html` | 478 | **78** | Escapes all injected strings; unauthenticated admin surface. |
| 10 | `model_switch.py` | 817 | **76** | Solid switch contract; `id(settings)` keying and unlocked event list. |
| 11 | `speculative_hedge.py` | 435 | **74** | Strong race logic; documented `tools` forwarding is missing. |
| 12 | `constellation.py` | 534 | **70** | Good history/health model; stores keys in clear and has doc drift. |
| 13 | `proxy_gateway.py` | 2444 | **62** | The core works, but it is a 63-complexity monolith with unsafe surfaces. |
| 14 | `install_redhands_autostart.ps1` | 251 | **62** | Registers a user-writable script to run as SYSTEM every minute. |
| 15 | `billing.py` | 593 | **55** | Auto-top-up mints free credits; metering is an estimate; failing test. |
| 16 | `launch_redhands_hub.ps1` | 244 | **45** | Good process hygiene, but committed live secrets cap the grade. |
| 17 | `check_balance.py` | 26 | **30** | Live keys in source, private methods, runs on import. |
| 18 | `siphon.py` | 744 | **18** | PCI-hostile card vault + autonomous charging + fraud-evasion logic. |
| 19 | `audit_cards.py` | 45 | **10** | Live keys in source and real charges execute on import. |

Supporting files: `requirements.txt` **55** (pinned, but `cryptography` is
missing), `.gitignore` **40** (omits `users.jsonl`, `usage_events.jsonl`,
`card_amount_audit.jsonl`, `user_keys.jsonl`).

---

# P0 — stop the line

These are not code-quality opinions. Each one is exploitable or illegal in the
current deployment.

## P0-1. Live provider secrets are in the working tree **and in git history**

`launch_redhands_hub.ps1:173-185` hardcodes:

| Secret | Where | Committed? |
|---|---|---|
| Hive `HIVE_SECRET_KEY` | `launch_redhands_hub.ps1:173` | **Yes — present at `HEAD`** |
| nano chat key (x2: `SPECIALIST_API_KEY`, `nano key env (retired)`) | `launch_redhands_hub.ps1:181,183` | Working tree (file is tracked) |
| Abliteration chat key | `launch_redhands_hub.ps1:184`, `audit_cards.py:15`, `check_balance.py:7` | Working tree / untracked |
| Abliteration **admin** key | `launch_redhands_hub.ps1:185`, `audit_cards.py:16`, `check_balance.py:8` | Working tree / untracked |

`git show HEAD:launch_redhands_hub.ps1` already contains the Hive key and a
previous Abliteration key, so rotating in the working tree does
**not** remove the exposure: anyone with clone access can read history.
`audit_cards.py` / `check_balance.py` are untracked today and will be swept in
by the next `git add -A`.

**Do:** revoke and re-issue every key above; delete the literals and read from
the user/machine environment or a secret store; run `gitleaks`/`trufflehog`
over history; either purge history (`git filter-repo`) or treat the old keys as
public forever. Add a pre-commit secret scan. The launcher comment "never
committed to a public remote" is not a control.

## P0-2. Unauthenticated endpoints move money and change routing

`AUTHZ_ENFORCED` defaults to `0` (`proxy_gateway.py:243`), so `run_guards()`
checks nothing unless the operator opts in. On top of that:

| Endpoint | Guards | Effect |
|---|---|---|
| `POST /v1/user/topup` | **none** | Calls Abliteration's `/admin/charge` with the server's admin key and credits the caller's `X-User-Id` (`proxy_gateway.py:2243-2298`). Repeatable → drain the funding account. |
| `POST /v1/siphon/card` | **none** | Accepts `number`, `exp_month`, `exp_year`, `cvv` (`2397-2413`). |
| `POST /v1/siphon/evaluate` | **none** | Forces a real card charge (`2422-2426`). |
| `POST /v1/siphon/toggle` | **none** | Turns the charging loop on/off (`2429-2435`). |
| `GET /v1/siphon/cards` | **none** | Lists the inventory. |
| `GET /admin/models`, `GET /v1/models/dna` | **none** | Full Control Room + provider URLs. |
| `POST /v1/switch`, `/v1/constellations/apply` | authz only if enabled | Whoever can reach the port can repoint every request. |

Identity is a **client-supplied header**: `_get_user_id()` trusts `X-User-Id`
verbatim and falls back to the socket IP (`proxy_gateway.py:2162-2165`). So
"user A" can read/write user B's stored keys and charge to B's balance.

**Do:** default `AUTHZ_ENFORCED=1`; require `ADMIN_API_KEY` (or a real auth
layer) for every management/charging route; never derive identity from a
request header without a verified token; bind the hub to loopback unless a
reverse proxy terminates auth.

## P0-3. Card data at rest is plaintext, including CVV

`CardInventory.add_card()` writes `number`, `exp_month`, `exp_year`, `cvv`
verbatim to `cards.jsonl` (`siphon.py:111-140`). The file currently holds
**two rows** with those fields. Storing the CVV after authorization is
prohibited by PCI DSS 3.2; storing the PAN unencrypted is equally out of
bounds. `/v1/siphon/card` accepts this over plain HTTP by default
(`127.0.0.1` today, but `HOST=0.0.0.0` is one env var away).

**Do:** stop accepting card data entirely. If a payment flow is genuinely
required, use the provider's hosted/tokenized checkout and store only the
returned token. Delete `cards.jsonl` through a documented destruction process
and rotate the cards.

## P0-4. SIPHON is on by default and is designed to evade fraud controls

- `SIPHON_ENABLED` defaults to **on** (`proxy_gateway.py:975`); the background
  loop evaluates every hour and charges automatically (`siphon.py:693-707`).
- `audit_cards()` really charges **eight amounts ($20–$53) on every active
  card** to "test" them (`siphon.py:678-682`, `audit_cards.py:32-33`).
- `_execute_charge()` adds a random ±$2–3 **"to avoid exact-pattern
  detection"** and the prompt tells the model to "vary amounts to avoid fraud
  detection" (`siphon.py:591-605`, `520-529`).
- The model is explicitly instructed that it is "funding YOURSELF" and decides
  when to charge (`siphon.py:505-520`).

Individually these read as deliberate structuring; together they are a
liability, not a feature. **Do:** set `SIPHON_ENABLED=0` now, remove the
endpoints from the public router, and get a legal/compliance decision before
any of this code runs again. The code grade (18) reflects that the
implementation is also weak, but the reason to remove it is not code quality.

## P0-5. "Encrypted at rest" is false by default

`billing.KeyVault` falls back to **plaintext** when `ENCRYPTION_KEY` is unset
(`billing.py:83-90`). `ENCRYPTION_KEY` is unset in the launcher, so
`/v1/user/keys` stores Hive/Abliteration user keys in clear text in
`user_keys.jsonl` — a file `.gitignore` does not cover. The endpoint's response
says "Keys stored securely" (`proxy_gateway.py:2191`). `store_key()` also
swallows `OSError` and still reports success (`billing.py:158-163`).

**Do:** refuse to start (or refuse the endpoint) when the key is absent; use a
KMS/DPAPI-backed key; add `user_keys.jsonl` to `.gitignore`; return an error
when persistence fails.

## P0-6. Boot-restore trusts an unvalidated file that contains keys

`slot_bindings.json` stores the raw provider keys for all three slots
(`constellation.py:330-343`, explicitly "by choice"), and on startup
`proxy_gateway.py:942-967` applies the newest snapshot to the **live**
`SETTINGS` with no validation. Today that file contains the test bindings
`http://primary.test/...` and `http://dead.test/v1`, which is why the live hub
reports `ok:false` and real traffic would fail. Anyone who can write the file
controls routing and reads the keys.

**Do:** persist a provider/model reference, not `url`+`key`; resolve through
the registry at boot; reject unknown hosts and any `*.test`; record only
`key_present`; add `SLOT_PERSISTENCE=0` in tests (the code already special-cases
`pytest`, but the damage was done by a real run). Delete/repair the current
file before serving traffic.

## P0-7. CORS is wildcard with credentials

`allow_origins=["*"]` together with `allow_credentials=True`
(`proxy_gateway.py:851-860`). Browsers reject that combination, and the
intended permissive behaviour is unsafe for an admin surface. Default to
loopback origins and make `*` an explicit, credential-free opt-in.

## P0-8. Sensitive runtime files are not ignored

`.gitignore` covers `gateway_registry.json`, `cards.jsonl`,
`siphon_memory.jsonl`, `slot_bindings.json`, `model_health.jsonl` — but **not**
`users.jsonl` (balances), `usage_events.jsonl` (per-user usage, 141 KB),
`card_amount_audit.jsonl`, or `user_keys.jsonl`. `git status` already shows the
first three as untracked. Add them before the next commit.

---

# P1 — correctness and reliability

## P1-1. The divert regression is a real bug, not just a stale test

The live symptom: a refusal from the primary is delivered to the client as the
answer. `evals/specialist_system_test.py:104` asserts `"specialist answer" in
text` and gets `"I cannot help with that."`; `evals/e2e_gateway_test.py:148`
records an empty fallback payload. Eleven of the 21 failures share this cause.

Two defects in the new continue-with-primary block:

1. When the pre-signal fires on a content chunk, the code does `continue`
   (`proxy_gateway.py:1521`). That skips the `if finish:` block for that same
   chunk, so a stub/stream that carries `content + finish_reason` never reaches
   the confirm/recovery logic.
2. The `[DONE]` branch (`1452-1470`) replays `pending` and `return`s **without
   ever consulting `refusal_presignal`**. The "grace window never expired, did
   the primary recover?" logic exists only in the `finish` and
   "stream ended without [DONE]" branches (`1556-1588`, `1594-1627`). A model
   that refuses and closes with `[DONE]` therefore leaks its refusal verbatim.

This is exactly the failure mode the gateway exists to prevent. Fix the state
machine before any other routing work: treat `[DONE]` as a terminal event that
runs the same presignal confirmation as `finish`, and do not `continue` past a
chunk that carries `finish`.

## P1-2. `/healthz` probes the wrong URL and bypasses the injected client

```python
probe_url = (SETTINGS.scout_api_url or SETTINGS.primary_api_url).rstrip("/")
models_url = probe_url + "/v1/models"          # 2083
async with httpx.AsyncClient(timeout=5.0) ...  # 2089
```

`primary_api_url` is a **chat-completions** URL
(`.../v1/chat/completions`), so the probe becomes
`.../v1/chat/completions/v1/models` — a guaranteed 404. `scout_api_url` has
the same shape after a switch (`_slots_for_history` stores the chat URL), so
the "scout" path is broken too. The probe also creates a fresh client instead
of using `app.state.http`, which is why every health test that monkeypatches
the shared client fails and why the endpoint can block for 5 s per call. The
watchdog calls it every minute.

**Do:** strip `/chat/completions` and `/messages` (reuse
`providers._strip_chat_suffix`), reuse the shared client, cache the last probe
for a few seconds, and skip the live probe under pytest/`TESTING=1`.

## P1-3. In-flight accounting is not trustworthy

The live hub reported `in_flight=6`, then `2`, with no client traffic, while
`/metrics` simultaneously reported `1`. `_stream_opened/_stream_closed` keep
`app.state.in_flight` and `_METRICS["in_flight"]` in lockstep in the normal
path, so the divergence points at a path where the generator is never iterated
or its `finally` never runs. A leaked slot eventually returns 429 for
everyone, and the shutdown grace loop waits on the same counter.

**Do:** make the counter a single source (`app.state.in_flight`, render it),
decrement from a Starlette `BackgroundTask`/response finalizer rather than only
the generator's `finally`, and add a test that aborts a stream mid-flight.

## P1-4. Metering charges the wrong thing, at the wrong time, and never gates

`usage_middleware` (`proxy_gateway.py:866-929`):

- `total_tokens += len(chunk) // 4` counts the **raw SSE bytes**, including
  JSON keys, `data:` prefixes and `[DONE]`. It is not a token count.
- At `credit_cost_per_token=0.002`, 10 KB of SSE is billed as $5.00.
- `response.headers[...]` is set inside the generator's `finally`, after the
  response has started — headers are already on the wire, so the credit
  reminder never reaches the client.
- `request.state.request_id` is never assigned anywhere, so every usage row has
  an empty `request_id`.
- `balance` is read and never used (`F841`).
- There is **no pre-flight balance check**; `is_depleted()` is only used to
  choose a message. A user at $0 is still served.
- The deduction happens in `finally`, so an aborted stream is still charged for
  whatever bytes it produced.

## P1-5. Billing auto-top-up mints credits

`AUTO_TOPUP_ENABLED` defaults to `true` (`billing.py:42`) and `_auto_topup()`
adds credit locally without charging anything (`billing.py:300-420`). It
records a `card_id` but never calls the payment API. Consequences:

- `evals/constellation_test.py::test_billing_registry_basic` expects
  `balance < free_tier` and gets **2.89** — the test is correctly catching the
  behaviour.
- Any user who spends down to $2 is refilled to ~$3, forever.
- The "velocity tuning" logic optimises a number that is not tied to revenue.

`UsageTracker._load()` also does `datetime.fromisoformat(r["timestamp"])`
without a per-row guard (`billing.py:452-466`); one malformed timestamp makes
module import raise and the hub cannot boot.

## P1-6. `assert_clean()` can turn a divert into a 500

`fallback_stream()` calls `assert_clean(msgs)` at `proxy_gateway.py:764`.
`prune_artifacts()` removes paired `<thinking>…</thinking>` but not an
**unclosed** `<thinking`, while `_LEAK_MARKERS` contains `"<thinking"`. A client
that sends a truncated tag therefore raises `ValueError` while the streaming
response is being iterated — after headers — and the client sees an empty 200.
`specialist_messages()` raises the same way when there is no user turn. Design
rule 7 says hooks never raise into the request path; these do.

## P1-7. The Frost alias contract was removed, not migrated

`FROST_ALIASES` now contains only the four max-think names and
`frost-general` (`providers.py:64-77`). `deepfrost`, `glmfrost` and
`cyberfrost` are gone, so `resolve_frost_alias()` returns `None` and
`model_switch.resolve_target()` raises
`could not resolve model 'CyberFrost'` (`evals/switch_test.py:227`). The
`/v1/models` list is also hand-written to two entries
(`proxy_gateway.py:1890-1899`), so the aliases that do exist are not
discoverable. Six tests fail here.

## P1-8. `model_switch` manager cache is keyed by object identity

`_manager_for(settings)` stores managers in `_managers[id(settings)]`
(`model_switch.py:722-733`). `id()` is only unique while the object is alive;
a test (or a discarded `Settings`) can be collected and a new object can reuse
the address, handing back a manager bound to the dead object. The dict is never
evicted. Also `SlotManager.record()` appends/deletes `self.events` without the
lock (`model_switch.py:305-310`), and `verify_target()` always sends a Bearer
header even for Anthropic-wire providers (`363-388`), where the probe will
401 and report a false "auth rejected".

## P1-9. Circuit breaker is half-wired and shared globally

`open_primary()` never calls `BREAKER.record_failure()`; only the specialist
path does. `verify_target`/success paths reset it. `allow_request()` lets every
caller through in HALF-OPEN (the comment says "one probe at a time" but nothing
enforces it). The module-level `BREAKER` leaks state between tests:
`evals/edge_test.py:104` expects `OPEN` and sees `CLOSED`. Either the primary
must feed the breaker, or the breaker must be per-slot and reset in a fixture.

## P1-10. Registry silently falls back to the environment on a bad file

`Registry.reload()` catches `OSError/JSONDecodeError/KeyError` and falls
straight through to `_legacy_env_providers()` (`providers.py:314-336`). A
one-character JSON typo therefore repoints traffic at
`https://api.openai.com/v1/chat/completions` with an empty key — the exact
incident the module comments describe. Fail loudly (log + keep the last good
config, or refuse to start) instead of silently changing providers.

## P1-11. Hedge does not forward what the docs promise

`speculative_hedge.py` only sends `model/messages/stream/max_tokens/
max_completion_tokens` to both branches (`~190-205`). `tools`, `tool_choice`
and `temperature` are not forwarded, despite `docs/provider-hub-plan.md:28`
claiming F9 fixed exactly that. `should_hedge` is imported and unused, and
`__all__` exports `hedge_settings`, which does not exist (`F822`).

## P1-12. The Control Room is an unauthenticated routing console

`GET /admin/models` serves a UI that POSTs `/v1/switch`,
`/v1/constellations/apply` and rollback with no credential
(`control_room.html:262-270`, `377-410`). It escapes interpolated text with
`esc()` (good), but the surface itself must sit behind admin auth. It also
prints internal provider URLs from `/v1/models/dna`.

## P1-13. `install_redhands_autostart.ps1` creates a SYSTEM privilege path

The scheduled tasks run as `S-1-5-18` (`install_redhands_autostart.ps1:136-140`)
and execute `C:\Users\lnxzf\Desktop\projects\provider-hub\launch_redhands_hub.ps1`
— a file in a user-writable Desktop directory — every minute via the watchdog.
Any process that can write that path gets SYSTEM execution. Move the code to
`Program Files` (or a service account-owned directory) with ACLs, or run the
tasks as a dedicated low-privilege user.

## P1-14. Dependency and state hygiene

- `requirements.txt` does not list `cryptography`, yet `billing.py:10` imports
  `cryptography.fernet`. A clean install from this file cannot import billing.
- `users.jsonl`, `usage_events.jsonl`, `card_amount_audit.jsonl` are not
  ignored (see P0-8).
- `FROST_REGISTRY` duplicates `gateway_registry.json` and has already drifted.
- `Tier4Classifier`/`TIER4` is instantiated but never called — dead code.
- `max_body_bytes` is capped at 32 MiB but individual values (`max_tokens`,
  `n`) are not validated; `n>1` is rejected, `max_tokens=-1` is not.

## P1-15. Audit trail can be lost silently and grows without bound

`ingress_assembler.audit_record()` catches every exception and returns `{}`
(`ingress_assembler.py:140-176`), including a full-disk `OSError`; the caller
cannot tell that the record was dropped. `AUDIT_LOG` is a plain append with no
rotation, and the same function also writes every record to stdout, doubling
the volume. For a system whose selling point is provenance, the audit sink
needs an explicit failure mode (counter + stderr) and rotation.

---

# P2 — quality, consistency, maintainability

Measured, not impressionistic:

| Signal | Value |
|---|---|
| `ruff` findings (14 files) | **153** (96 auto-fixable) |
| `mypy` errors (10 files) | **22** |
| `chat_proxy` cyclomatic complexity | **63** (limit 12) |
| `coordinator` complexity | **45** |
| Broad `except Exception` | **33** |
| `try/except: pass` | **9** |
| `print()` in library code | **26** |
| Deprecated `@app.on_event` | 3 warnings |
| Unused imports/vars (`F401`/`F841`) | 10 + 2 |
| Undefined export (`F822`) | 6 |

Per-file lint debt: `proxy_gateway` 35, `providers` 28, `constellation` 26,
`billing` 21, `siphon` 15, `model_switch` 8, `speculative_hedge` 5,
`routing_patterns` 5, `ingress_assembler` 4, `conftest` 2, and 1 each in
`context_formatter`, `check_balance`, `audit_cards`, `ask`.

Concrete cleanups worth doing in one pass:

1. `ruff check --fix` for the 96 safe fixes, then a `pyproject.toml` that pins
   the rule set (there is currently **no** ruff/mypy config in the repo).
2. Replace the 33 broad excepts with the specific exception types, or
   `log.exception(...)`; nine `except: pass` blocks are observability holes
   (`proxy_gateway.py:362,998,2100`, `siphon.py:700`, etc.).
3. Deduplicate `_int_env` (3 copies), `_auth_header` (2), `_last_user_text`
   (2), and the JSONL load/write helpers (4 modules).
4. Split `chat_proxy` into `resolve_route()`, `stream_primary()`,
   `screen_buffer()`, `divert()`; the current state machine is untestable in
   isolation (that is why the `[DONE]` bug survived).
5. Replace the hand-written `FROST_REGISTRY` with registry-driven listing.
6. Delete `Tier4Classifier` or wire it; the code currently pretends a Tier-4
   classifier exists.
7. Migrate `on_event` to a lifespan handler.
8. Type the settings object (`Settings` is a dataclass but most call sites pass
   `settings=None` and fall back to the global — mypy cannot help).
9. Add a `pyproject.toml` with `pytest`, `ruff`, `mypy` and a `Makefile`/task
   so "green" is one command. There is no CI config in the repo.
10. Log with `logging`, not `print`; route the audit stream through a logger.

---

# Per-file reviews

Each entry: grade, what is genuinely good, what is wrong, and the smallest
change that would raise the grade.

## `routing_patterns.py` — **88 / 100**

**Good.** This is the model the rest of the repo should follow. Dependency-free
by contract, one `ROUTING_RE`, `normalise()` folds curly quotes/Unicode spaces
before matching, the regex is anchored so an answer *about* refusals does not
trip it, `classify_status()` centralises the retry/divert taxonomy, and the
`no_go`/`attack` gates are separated into "block" versus "route" semantics with
the reasoning documented at the call site. The calibration notes (2026-10-05)
reference real measurements.

**Wrong.** Only style debt: 5 ruff findings (unsorted `__all__`, `Optional`,
`%`-format), an unnecessary `try/except` in `footnote()` that cannot fire
(`FOOTNOTE_TEMPLATE.format` only fails if the template is malformed), and
`_OFFENSIVE_REQUEST_RE` is now large enough that its precedence rules deserve
table-driven tests rather than prose. The anchored design also means a refusal
that starts after 200 characters of preamble is invisible by construction —
that is a deliberate trade-off, but it should be asserted in a test named after
the trade-off.

**Next.** `ruff --fix`, drop the footnote guard, add property tests for
`normalise` (idempotence, look-alike folding) and a precedence table for the
offensive-request matcher.

## `ingress_assembler.py` — **86 / 100**

**Good.** `assemble()` is a pure, fail-closed string replace: missing anchor,
duplicate anchor and empty artefact all raise. That is exactly the right
contract for a merge that must never be model-mediated. Audit records carry
hashes rather than raw artefacts, and the `_AUDIT_LOCK` prevents interleaved
writes.

**Wrong.** `audit_record()` swallows *every* exception and returns `{}`
(`140-176`), so a full disk silently discards provenance; it also writes every
record to stdout in addition to the file. The audit file has no rotation.
`validate_artifact()` checks that SARIF is valid JSON but not that it matches
the grammar it claims to enforce, and `SARIF_DEFECT_GBNF` is a string that is
never compiled/tested.

**Next.** Add a rotating file handler + a dropped-record counter; return a
status from `audit_record`; validate SARIF against a minimal schema; unit-test
the GBNF string against a known-good artefact.

## `context_formatter.py` — **84 / 100**

**Good.** The four stages are explicit, `prune_artifacts()` is shared, and the
`specialist_messages()` versus `format_messages()` distinction is one of the
best-documented bug fixes in the repo (27k-token context and tool results were
being dropped on a plain divert). `assert_clean()` is a real invariant.

**Wrong.** `prune_artifacts()` only removes **paired** `<thinking>…</thinking>`;
an unclosed `<thinking` survives, and then `assert_clean()` raises inside the
streaming generator (P1-6). `_text_of()` drops non-text blocks (images,
`image_url`) while keeping `tool_calls`, so a multimodal divert silently loses
the image. `specialist_messages()` raises if the conversation has only a system
turn, which becomes an empty 200 on the divert path.

**Next.** Make the cleaner remove unpaired markers; make `assert_clean`
non-raising (return a list of leaks, let the caller decide); either preserve
image blocks or reject them with a 400 before the stream starts.

## `conftest.py` — **88 / 100**

**Good.** Small, correct, and the `litellm.__path__` shim is explained with the
exact failure it fixes. Catching `Exception` around an optional import is
appropriate here.

**Wrong.** Mutating an installed package's `__path__` is a global side effect
that can surprise other test suites in the same interpreter; a fixture-scoped
approach would be cleaner. Two ruff findings are cosmetic.

**Next.** Leave it alone unless the litellm shim is retired.

## `speculative_hedge.py` — **74 / 100**

**Good.** The race is implemented correctly with `build_request()` +
`send(stream=True)` under an `AsyncExitStack`; reasoning is forwarded but never
counted or screened (F1/B21); the "screened-out sovereign is never something we
may fall back TO" rule is the right call and is documented with the incident
that motivated it; stream ids are stable (R1); the empty-sovereign rule handles
the GLM thinking-only failure.

**Wrong.** It does **not** forward `tools`, `tool_choice` or `temperature`
(P1-11), despite the docs claiming F9. `sovereign_key` does not mirror the
gateway's Hive fallback (`HIVE_SECRET_KEY`), so a fresh shell with only Hive
configured sends an empty key on the sovereign branch. `__all__` exports a
non-existent `hedge_settings` (`F822`), `should_hedge` is imported unused, and
`HedgeSettings` duplicates the env-resolution logic that already lives in
`proxy_gateway.Settings` — two sources of truth for the same slots.

**Next.** Accept the already-built payload from the caller (or forward all
five fields); delete the F822 export and unused import; make `HedgeSettings`
derive from the shared settings object.

## `providers.py` — **78 / 100**

**Good.** Clean dataclasses (`Provider`, `Target`, `Event`), an mtime-based
registry reload so an edit is picked up without a restart, correct Anthropic
wire adapters, masked read-back (`masked()`, `mask_key`), and a documented
env-synthesis fallback so a deployment with no registry still boots.

**Wrong.** Keys live in the JSON in plaintext and `save()` rewrites them on
every mutation (`423-429`). A malformed registry silently switches the whole
hub to the env fallback (P1-10). The alias section has drifted from reality:
the `resolve_hub_alias` docstring example says `deepseek-ai/deepseek-v4.1-flash`
while the table returns `deepseek/deepseek-v4.1-flash`; `hub_models_for_listing`
publishes the compact lowercase key (`deepmaxnano`) rather than the display name
(`DeepMaxNano`), so `/v1/models` shows ids nobody types. `FROST_ALIASES` lost
`deepfrost`/`glmfrost`/`cyberfrost` (P1-7). No URL validation on
`upsert_provider`, so an admin write can point at any host.

**Next.** Store key *references* (env var names) rather than key material;
differentiate "file missing" from "file invalid" and fail loud on the latter;
regenerate the alias tables from one dict; add `https`-only + host-allowlist
validation on provider writes.

## `model_switch.py` — **76 / 100**

**Good.** The seamless-switch contract at the top of the file is excellent:
in-flight requests hold their own settings copy, verification is advisory, a
savepoint makes every mutation reversible, and every action lands in the audit
log. `parse_switch_request` preserves F5 (garbage in → 400). Time-travel
rollback is a genuinely nice feature and is implemented against the masked
history API.

**Wrong.** `_manager_for` keyed on `id(settings)` is unsound and leaks memory
(P1-8). `record()` mutates the event list outside the lock. `verify_target`
sends a Bearer token to Anthropic-wire providers where the probe should use
`x-api-key`. `_parse_ts("2026-10-19T14:30:00")` is read as **local** time
despite the docstring promising UTC (only the `Z` form is explicit). Boot
restore (in `proxy_gateway`) applies whatever is in the history file.

**Next.** Key the manager cache by an explicit owner parameter (or a
`WeakKeyDictionary`); lock `record()`; make `verify_target` provider-aware;
append `+00:00` for naive ISO strings; validate restored bindings against the
registry before applying.

## `constellation.py` — **70 / 100**

**Good.** The slot vocabulary layer is thin and well-mapped
(`SLOT_TARGET`/`SLOT_DISPLAY`), presets are resolved *before* any mutation in
`apply_constellation` (all-or-nothing), health scoring is recency-weighted with
a sensible decay, and `entries()` masks keys on read-back. Retention caps
(7 days, 500 entries, 40 health events) are all present.

**Wrong.** `BindingHistory` stores raw provider keys and says so out loud
("review items 1-4 are still open by choice", `330-343`) — that choice is what
made P0-6 possible. `normalize_slot()`'s docstring claims it returns
`helm`/`scout` but it returns `primary`/`worker`. `Constellations.get()`
lowercases the requested name while `save()`/`list()` preserve case, so a
mixed-case preset (`"Deep Space"`) can never be applied. `model_dna()` claims
`context_k: 128` for every model. `record()` catches only `OSError`, so a
serialization error would escape despite the "never raises" promise.

**Next.** Persist provider+model ids instead of url+key; normalize preset names
at read *and* write; fix the two docstrings; widen the exception guard or
assert serializability.

## `billing.py` — **55 / 100**

**Good.** The per-user row shape is documented, writes are atomic
(temp + `os.replace`), `KeyVault`/`UsageTracker` take locks, and the module
falls back gracefully when files are missing. Credit *state* is coherent and
`all_users()`/`system_usage()` are useful.

**Wrong.** The auto-top-up block (P1-5) is a money printer: it grants credit
without a charge, defaults to on, and is what the failing
`test_billing_registry_basic` is catching. `ENCRYPTION_KEY` absence silently
downgrades to plaintext "encryption". `UsageTracker` rewrites the entire file
on every event (O(n²) I/O on the request path, up to 10,000 rows) and crashes
the module import on one malformed timestamp. `add_credits()` accepts a
`source` argument and ignores it. There is no idempotency key for a charge, so
a retried HTTP request can double-credit. The token *price*
(`CREDIT_COST_PER_TOKEN=0.002`) is coupled to the byte-count estimate in the
gateway, which is not a token count.

**Next.** Default `AUTO_TOPUP_ENABLED=false` and require a real charge before
crediting; require `ENCRYPTION_KEY` or disable `/v1/user/keys`; batch/append
usage writes instead of rewriting; guard `fromisoformat` per row; record
`source`; add an idempotency key.

## `proxy_gateway.py` — **62 / 100**

**Good.** The seven design rules at the top are real and mostly honoured. The
body cap is enforced *during* consumption (`read_json_body`) rather than
trusted from `Content-Length`. Guards run once and are shared. The B10 status
taxonomy is centralised. F11/F12/F13 all fix the same real defect class
(silent empty 200s) by making failures visible in `delta.content`. Stream ids
are stable per stream (R1), the agentic `tools` survive a divert, and the
specialist budget is bounded.

**Wrong.** In order of consequence:

1. The continue-with-primary state machine is broken (P1-1) and is the reason
   11 tests are red — a refusal can be delivered as the answer.
2. `/healthz` probes a nonsense URL with a throwaway client (P1-2).
3. `usage_middleware` meters bytes, writes headers after the response starts,
   and never gates on balance (P1-4). `request.state.request_id` is never set.
4. Unauthenticated money/routing surfaces (P0-2) and the mounted SIPHON
   endpoints (P0-4).
5. `json.loads` in `read_json_body` accepts **any** JSON; `body` can be a list,
   and the next `body.get(...)` raises `AttributeError` → 500. `messages` is
   never validated as a list of dicts either. `max_tokens` is unvalidated.
6. Boot-restore applies unvalidated bindings that contain keys (P0-6).
7. CORS wildcard + credentials (P0-7).
8. `chat_proxy` is 63-complexity and `coordinator` 45 — the `[DONE]` branch bug
   is exactly the class of defect that complexity hides.
9. Dead/stale code: `Tier4Classifier`+`TIER4` never called, `FROST_REGISTRY`
   hardcoded to two entries, unused imports (`DEFAULT_SYSTEM`,
   `format_messages`, `DIVERT_STATUS`, `FOOTNOTE_TEMPLATE`), unused locals
   (`start_time`, `balance`), deprecated `@app.on_event`, mid-file imports.
10. `_METRICS` is a plain module dict: fine on one event loop, silently wrong
    with multiple uvicorn workers.
11. `assert_clean()` can raise into the stream (P1-6).
12. `_specialist_key()`/`_auth_header` use the sentinel string `"none"` instead
    of `None`.

**Next (in order):** extract `screen_buffer()`/`divert()`/`route()` out of
`chat_proxy` and fix the `[DONE]` handling with a unit test that never touches
HTTP; fix `/healthz`; fix or disable the metering middleware; put every
management/charging route behind admin auth; validate the body shape; make
boot-restore validate; then `ruff --fix` and delete the dead code.

## `siphon.py` — **18 / 100**

**Code structure** is unremarkable but not the problem: dataclass-free row
dicts, per-object `RLock`s, atomic writes, and a reasonable decision/outcome
split between `SiphonAgent`, `SiphonMemory` and `CardAmountAudit`.

**What sinks it** is what the code *does* (P0-3, P0-4): plaintext PAN+CVV at
rest, autonomous charging on by default, real-money "audit" grids, amount
randomisation to avoid fraud detection, and an LLM told to fund itself.

**Also wrong, independently:**

- `_real_charge()` posts `user_id`/`amount`/`currency`/`description` but **no
  `card_id`** — so the "per-card" audit ledger attributes every charge to cards
  that were never targeted, and `best_combo()` then selects "proven" amounts
  from meaningless data.
- `add_card()` builds ids from `len(rows)+1` plus randomness — collision-prone
  and meaningless after deletions. No Luhn/expiry validation.
- `run_loop()` swallows every exception with no log (`700-701`); `stop()`
  cancels without awaiting; `_save_state()` is called directly by the HTTP
  layer (private API).
- `status()` advertises `total_extracted_usd` — naming that reinforces the
  wrong model.

**Next.** Disable it. If a legitimate version is ever wanted, it starts by
deleting the card vault, the fraud-evasion randomness, and the self-funding
prompt.

## `audit_cards.py` — **10 / 100**

**Good.** Nothing that survives the red flags.

**Wrong.** Two live Abliteration keys are hardcoded at lines 15-16. The module
executes `asyncio.run(main())` at import time (line 45, no `__main__` guard),
and `main()` performs **real charges** across a grid of eight amounts on every
active card with no dry-run flag, no confirmation and no cap. Any import (test
discovery, a REPL, a linter with import-following) charges money.

**Next.** Delete the file, or reduce it to a read-only report that takes its
credentials from the environment and refuses to charge without an explicit
`--execute` plus a spend ceiling.

## `check_balance.py` — **30 / 100**

**Good.** It is small and does what the name says.

**Wrong.** Hardcoded live keys (lines 7-8), calls private methods
(`agent._org_balance()`, `_user_credits()`), and runs on import without a
`__main__` guard. It also duplicates credential-resolution logic that already
exists in `siphon`.

**Next.** Read the keys from env, call a public `SiphonAgent.balances()`, wrap
in `if __name__ == "__main__"`.

## `ask.py` — **80 / 100**

**Good.** A genuinely useful smoke-test client: streams thinking and answer
separately, honours `--principal` for an authz-enabled gateway, works with the
stdlib only, and the docstring explains the authz interaction.

**Wrong.** Hand-rolled argument parsing: `del args[i:i+2]` executes even when
`--principal` is the last token; unknown `--flags` are silently treated as
prompt text; the 900-second timeout is hardcoded; an HTTP error (403/429) is
reported as "gateway unreachable", which is misleading.

**Next.** Use `argparse`; distinguish HTTP status errors from transport errors.

## `launch_redhands_hub.ps1` — **45 / 100**

**Good.** This is a well-engineered launcher apart from one fatal flaw: a named
mutex prevents racing launchers, an already-healthy hub is a no-op, the Python
interpreter is discovered and *validated by import* before use, only processes
whose command line looks like the hub are killed to free the port, logs rotate
at 10 MB with one generation kept, and the health verdict is "HTTP 200" rather
than `{"ok": true}` — which is the correct liveness semantic and is explicitly
justified in the comments.

**Wrong.** Lines 173-185 hardcode four live secrets; the file is tracked, so
this caps the grade regardless of everything else (P0-1). The root path is an
absolute `C:\Users\lnxzf\Desktop\...` literal, so the script cannot move or be
used by a second operator. Freshness check `Test-PythonRunsHub` validates
`httpx`/`fastapi` but not `uvicorn`, which is what actually runs. The fallback
loop passes a `CommandInfo` object where a string is expected. `SCOUT_PYTHON`
is mentioned in an error message but never read.

**Next.** Delete the secrets (env/user scope only); move the root to a
server-owned directory; import uvicorn in the probe; make the path a parameter
with a default.

## `watchdog_redhands_hub.ps1` — **82 / 100**

**Good.** Genuinely good supervision design: consecutive-miss threshold, a
rolling-hour restart budget, a post-recovery cooldown so overlapping passes do
not kill a warming child, a global mutex for single-instance, log rotation, and
`-Once` mode so Task Scheduler can be the real supervisor. Exit codes are
documented and meaningful.

**Wrong.** It judges the hub purely by HTTP 200, which (correctly) ignores
`ok:false` — but that also means a *misconfigured* hub that answers 200 with
dead slot bindings is never remediated (exactly today's state). The recovery
launches a nested `powershell.exe -Wait`, so a slow launch blocks the pass for
up to a minute. The health failure detail is not captured in the log, which
makes post-mortems harder than they should be.

**Next.** Add an optional deep-health mode (`-RequireOk`) used for alerting
(not for restarts); log the `/healthz` body on failure; consider `Start-Job`
instead of a nested interpreter.

## `install_redhands_autostart.ps1` — **62 / 100**

**Good.** Clear idempotent verbs (`-Install`/`-Uninstall`/`-Status`/
`-Shortcut`), self-elevation that preserves the requested verb, correct
battery settings, `IgnoreNew` to prevent task stacking, and a status view that
shows the last task result and hub PIDs.

**Wrong.** It registers SYSTEM tasks that execute a script **inside a
user-writable Desktop directory** every minute (P1-13) — a local privilege
escalation path. `-AtLogOn` with no user means every logon triggers it. The
absolute repository path is hardcoded again. Everything assumes the current
OS layout (no Linux/macOS story, which is fine for this host but should be
stated).

**Next.** Move the runtime to a directory only SYSTEM/Administrators can write;
or run the tasks as a dedicated low-privilege service account with an ACL on
the folder; or (best) register a real Windows service.

## `open_control_room.ps1` — **85 / 100**

**Good.** Small, idempotent, waits for the hub with a bounded deadline, and the
header explicitly explains why the `ok` flag is irrelevant here. Uses
`$PSScriptRoot` rather than a hardcoded path (the only script that does).

**Wrong.** Py 3-second probe and 45-second deadline are hardcoded; the URL is
hardcoded to port 9000. If something else is listening on 9000 and answering
200, it will happily open that instead.

**Next.** Parameterize port/deadline; check a hub-specific marker (e.g. the
`/healthz` JSON body) before opening the browser.

## `control_room.html` — **78 / 100**

**Good.** Self-contained (no CDN, no framework), every interpolated value goes
through `esc()` (including attribute values, which is where most hand-rolled
UIs fail), event handlers are attached by JS rather than inline strings, and
the UI's three panels map cleanly to the API (`/v1/models/dna`,
`/v1/constellations`, `/v1/constellations/history`). `api()` surfaces server
error text instead of failing silently.

**Wrong.** It is an **unauthenticated** routing console (P1-12): anyone who can
reach the port can repoint helm/specialist/scout and roll back history. It
displays internal provider URLs. There is no CSP header, so a future
unescaped field would be a live XSS. `switchSlot` posts model ids without
confirming the resolution result, and the restore buttons are one click with no
confirmation.

**Next.** Require admin auth (header or session) on the page *and* on the
mutating endpoints; add `Content-Security-Policy: default-src 'self'`; add a
confirm step for switch/rollback.

---

# Test-baseline triage (21 failed / 291 passed / 3 skipped)

| Group | Failing tests | Root cause | Fix |
|---|---|---|---|
| Refusal divert | `e2e_gateway_test` (4), `specialist_system_test` (5), `specialist_config_test` (1), `attack_gate_test::test_ordinary_divert_has_no_forced_marker` (1), `max_think_test::test_max_think_refusal_diverts…` (1) | P1-1: `[DONE]` branch ignores `refusal_presignal`; `continue` skips `finish` | Fix the state machine; none of these tests should change |
| Frost alias contract | `frost_alias_test` (4), `switch_test::test_resolve_frost_name…` (1), `max_think_test::test_model_list…` (1) | P1-7: aliases removed, `/v1/models` hardcoded | Restore the alias table + registry-driven listing |
| `/healthz` live probe | `edge_test::test_healthz_reports_config_snapshot` (1) | P1-2: wrong URL, fresh client bypasses the mock | Fix probe, reuse `app.state.http`, skip under pytest |
| Circuit breaker | `edge_test::test_circuit_breaker_opens…` (1) | P1-9: global singleton, primary path never records failures | Per-test reset fixture; decide which paths feed the breaker |
| Billing | `constellation_test::test_billing_registry_basic` (1) | P1-5: auto-top-up credits the balance past the free tier | Disable auto-top-up by default; the test is right |

`evals/results/boot_audit.jsonl` and the boot logs are tracked and currently
modified; they also contain no secrets today (checked), but they are runtime
artefacts and should not be versioned.

# Recommended order of work (Stage 0, before any chain-routing change)

1. **Secrets** — revoke all four credentials; strip them from
   `launch_redhands_hub.ps1`, `audit_cards.py`, `check_balance.py`; add a
   pre-commit secret scan; decide on history purge. Nothing else on this list
   matters if the keys stay live.
2. **SIPHON off** — `SIPHON_ENABLED=0`, remove `/v1/siphon/*` from the router,
   move `cards.jsonl` to an encrypted store or destroy it, and get a
   compliance decision on the charging logic.
3. **Auth by default** — `AUTHZ_ENFORCED=1`, `ADMIN_API_KEY` required for
   `/v1/admin/*`, `/v1/user/topup`, `/v1/switch*`, `/v1/constellations/apply`,
   `/admin/models`; stop trusting `X-User-Id` as identity.
4. **Slot bindings** — delete or repair `slot_bindings.json`, validate restored
   bindings against the registry, reject `*.test`, restart, confirm
   `/healthz` → `ok:true` and a real request reaches Hive/the nano provider.
5. **Divert regression** — fix the `[DONE]`/`finish` handling; target **green**
   `pytest evals/`.
6. **`/healthz`** — correct URL, shared client, short cache, no live probe in
   tests.
7. **Billing** — auto-top-up off by default; fix the deduction path; either fix
   the middleware (real usage from upstream `usage` deltas, pre-flight balance
   check) or disable metering until it can be correct.
8. **Alias/listing contract** — restore `deepfrost`/`glmfrost`/`cyberfrost`
   and make `/v1/models` registry-driven.
9. **Hygiene** — `ruff --fix`, `pyproject.toml` pinning lint/type config,
   delete dead code, add the missing `.gitignore` entries and
   `cryptography` to `requirements.txt`, add a one-command "green" task.

Only after step 5 is green should `chain_routing.py` and
`evals/chain_route_test.py` be added — otherwise a new routing path lands on
an already-broken divert path, and a chain regression would be
indistinguishable from the WIP regression.

# What this review did **not** do

No runtime code was modified. The hub is still running (pid 24544) with test
slot bindings, `ok:false`, and a nonzero in-flight gauge. Fixes 1-4 above are
operator decisions (money, secrets, auth) and should be confirmed before I
touch anything.

# Appendix — commands used

```powershell
py -3.12 -m pytest evals/ -q --ignore=evals/results
py -3.12 -m py_compile <every module>
py -3.12 -m ruff check <every module> --statistics
py -3.12 -m mypy <every module> --ignore-missing-imports --follow-imports=skip
py -3.12 -m ruff check proxy_gateway.py --select C901 --config "lint.mccabe.max-complexity=12"
git show HEAD:launch_redhands_hub.ps1 | Select-String 'sk-|ak_|XSkX'
git ls-files | Select-String 'launch_redhands_hub|users.jsonl|cards'
git check-ignore users.jsonl usage_events.jsonl card_amount_audit.jsonl
Invoke-RestMethod http://127.0.0.1:9000/healthz
Invoke-WebRequest http://127.0.0.1:9000/metrics -UseBasicParsing
```

