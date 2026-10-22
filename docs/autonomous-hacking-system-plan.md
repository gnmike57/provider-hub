# Autonomous Hacking System — Plan & Implementation Record (2026-10-22)

Referenced by `docs/constellation-hub-plan.md` roadmap item 4. Status:
**phase 1 (the Arsenal surface) implemented**; phases 2-3 open.

## Directive

The REDHANDS brain (the Abliterated V2 Large under the `redhands.py` persona,
chain 3 `ABLITV2L>SUB-GLM/DEEP` / `X-Max-Offense: 1`) gains HANDS: classic
offensive tooling (nmap/sqlmap/ffuf) runnable against authorized targets only.

## Phase 1 — the Arsenal surface (DONE, 2026-10-22)

* `arsenal.py`: the tool registry (`TOOLS`: nmap, sqlmap, ffuf), the target
  allowlist (`ARSENAL_ALLOWED_TARGETS`, default = loopback + the gx10 vuln-lab
  range `100.67.13.78` / `192.168.0.230` / `gx10.ayu-sidewinder.ts.net`),
  list-argv command building (NO shell; every arg safe-charset checked), and
  `run_tool()` — bounded (`ARSENAL_TIMEOUT_S`, 5..600s), output-capped,
  **never raises** (missing binary / bad target / timeout are structured
  errors). One LIVE pin: nmap is installed on the operator PC
  (`C:\Program Files (x86)\Nmap`), sqlmap + ffuf likewise.
* `proxy_gateway.py`: `GET /v1/arsenal/tools` + `POST /v1/arsenal/run` —
  admin-authed (`X-Admin-Key`, 403 fail-closed), kill switch
  `ARSENAL_ENABLED=0` → 501, metrics `arsenal_total` / `arsenal_ok_total` /
  `arsenal_blocked_total`, and the REDHANDS association (the response
  records `redhands: true` when the request carried `X-Max-Offense: 1` or
  the hub runs `SPECIALIST_SYSTEM_MODE=redhands`).
* `evals/arsenal_test.py` (7 tests): command shapes (nmap `-p` from
  host:port, sqlmap `--batch`, ffuf `-w` requirement), rejections (unknown
  tool / off-allowlist host / URL-tool mismatch / injection-shaped args),
  never-raises, the endpoint auth/kill-switch/metrics/redhands behaviour, and
  one LIVE nmap pin against loopback (skipped when nmap is absent).

## Phase 2 — brain-driven chaining (OPEN)

The chain-3 helm decomposes an engagement into tool runs: the REDHANDS
system prompt learns the `/v1/arsenal/run` contract (a tool-call-style
loop, mirroring `/v1/computer`), so the brain plans scan → fuzz → exploit
against a named vuln-lab target and synthesises the findings. Reuses the
conductor fan-out + completion-contract verification machinery.

## Phase 3 — the Arsenal stack on the gx10 (OPEN)

Containerised nmap/sqlmap/ffuf beside `.staging/vuln-lab/` (the practice
range: juice-shop :8100, dvwa :8101, nginx-alias :8102…; see
`.staging/vuln-lab/docker-compose.yml`), so the tools run next to the
targets on the box and the surface only orchestrates over the tailnet.

## Verification

* `py -3.12 -m pytest evals/arsenal_test.py -q` → 7 passed (2026-10-22).
* Live: `nmap -Pn -p 9000 127.0.0.1` through the surface answers with the
  open hub port.
