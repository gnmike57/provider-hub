1 + # Architecture — Interception Gateway 

2 + 

3 + How the gateway, hedger, and assembler fit together. 

4 + Code references are to `reference-implementation/`. 

5 + 

6 + --- 

7 + 

8 + ## 1. System overview 

9 + 

10 + ``` 

11 +                         ┌────────────────────────────────────────────────┐ 

12 +   client ── HTTP/SSE ──▶ │             proxy\_gateway.py (FastAPI)         │ 

13 +                         │                                                │ 

14 +                         │  1. authz (F9)                                 │ 

15 +                         │  2. n>1 rejected (E6)                          │ 

16 +                         │  3. open primary (retry 408/429 — B10)         │ 

17 +                         │  4. ring-buffer state machine (B7/B8)          │ 

18 +                         │        │                                       │ 

19 +                         │      clean                                     │ 

20 +                         │        │                                       │ 

21 +                         │   passthrough                                  │ 

22 +                         │   + finish/\[DONE]                              │ 

23 +                         │                                                │ 

24 +                         │                                                │ 

25 +                         │                    fallback\_stream()           │ 

26 +                         │                    format → specialist         │ 

27 +                         │                    → footnote → audit          │ 

28 +                         └────────────────────────────────────────────────┘ 

29 + ``` 

30 + 

31 + | Endpoint | Path | Purpose | 

32 + |---|---|---| 

33 + | `POST /v1/chat/completions` | streaming ring-buffer | drop-in OpenAI-compatible proxy | 

34 + | `POST /v1/execute` | planner → worker → `assemble()` | Part IV deterministic assembly | 

35 + | `GET /healthz` | config + runtime snapshot | liveness / introspection | 

36 + | `GET /metrics` | Prometheus text (F26) | counters + warm gauges | 

37 + 

38 + --- 

39 + 

40 + ## 2. Module map 

41 + 

42 + | Module | Responsibility | Key exports | 

43 + |---|---|---| 

44 + | `routing\_patterns.py` | \*\*Single source of truth for routing logic\*\* (F3), dependency-free | `is\_routable`, `should\_hedge`, `tier2\_decision`, `normalise` | 

45 + | `context\_formatter.py` | Format context before the specialist sees it | `format\_messages`, `DEFAULT\_SYSTEM`, `assert\_clean` | 

46 + | `ingress\_assembler.py` | Deterministic (non-LLM) merge + audit records | `assemble`, `audit\_record`, `SLOT` | 

47 + | `proxy\_gateway.py` | FastAPI app: buffering, routing, metrics, endpoints | `app`, `fallback\_stream` | 

48 + | `speculative\_hedge.py` | Speculative dual-dispatch (B9/B11 fixes) | `hedge\_stream` | 

49 + | `litellm/routing\_callback.py` | Non-streaming repair inside LiteLLM | `RoutingFootnoteCallback` | 

50 + 

51 + \*\*Single-source invariant:\*\* `grep -rn 'ROUTING\_RE = ' reference-implementation/` must return 

52 + exactly one hit. The LiteLLM callback imports `is\_routable`/`format\_messages` rather than 

53 + re-declaring them — duplicated logic is the root cause of defects B20, B21, E1, E2, E3. 

54 + 

55 + 

56 + --- 

57 + 

58 + ## 3. Streaming state machine (`/v1/chat/completions`) 

59 + 

60 + A single pass over one `aiter\_lines()` iterator (B7: never re-enter a broken iterator). 

61 + States: `BUFFERING → {ROUTED, PASSTHROUGH, COMPLETE}`. 

62 + 

63 + ``` 

64 + BUFFERING 

65 +   ├─ finish\_reason == "timeout" or delta.error           → ROUTED    (Tier 1) 

66 +   ├─ delta.reasoning, BUFFER\_REASONING=0                  → forward now, 

67 +   │                                                        do NOT count  (B21) 

68 +   ├─ delta.content                                        → append, count tokens 

69 +   │     ├─ is\_routable(buffer) within 200-char window     → ROUTED    (Tier 3) 

70 +   │     └─ content\_tokens ≥ BUFFER\_CONTENT\_TOKENS (25)    → PASSTHROUGH 

71 +   ├─ finish\_reason present                                → COMPLETE 

72 +   └─ stream ends                                          → COMPLETE 

73 + ``` 

74 + 

75 + Key invariants: 

76 + 

77 + - \*\*Buffered lines are held in `pending`\*\*, replayed verbatim on pass-through; `finish\_reason` 

78 +   and `\[DONE]` are always propagated to the client (B7). 

79 + - \*\*On ROUTED the buffered text is discarded\*\* — never surfaced. Reasoning already 

80 +   forwarded is deliberation, not the error itself. 

81 + - \*\*Routing is evaluated only while buffering\*\* (B8); once in pass-through the stream is opaque. 

82 + - \*\*`n>1` is rejected up front\*\* (E6) — the buffer inspects one choice stream, so extra 

83 +   choices would bypass detection entirely. 

84 + 

85 + ### Tier 2 / Tier 4 (off the critical path) 

86 + 

87 + - \*\*Tier 2\*\* (`routing\_probability`): first-token log-prob mass over single-token routing 

88 +   openers, threshold `τ` (default 0.85, unvalidated — see ledger). Not wired into the 

89 +   streaming loop; intended for non-streaming paths. 

90 + - \*\*Tier 4\*\* (`Tier4Classifier`): LLM-as-judge for routing, disabled by default, 50–180 ms — must never 

91 +   sit in front of TTFT (report §5.1). Returns `None` on failure, never `False`. 

92 + 

93 + --- 

94 + 

95 + ## 4. Diversion path (`fallback\_stream`) 

96 + 

97 + 1. `format\_messages()` — 4-stage reduction to `\[DEFAULT\_SYSTEM, latest user turn]`. 

98 + 2. `\_open\_fallback\_with\_retry()` — retries `DIVERT = {500,502,503,504}` with backoff (F6). 

99 +    A 503 is \*capacity\*. 

100 + 3. Audit record emitted \*\*before\*\* the call (`audit\_record`, mode=`stream`). 

101 + 4. Specialist SSE forwarded verbatim, then a provenance footnote delta, `finish="stop"`, `\[DONE]`. 

102 + 5. `record\_success()` on completion; `record\_failure()` on transport or 

103 +    HTTP errors. 

104 + 

105 + \*\*Error taxonomy (B10)\*\* — the distinction the whole design hinges on: 

106 + 

107 + | Status | Meaning | Action | 

108 + |---|---|---| 

109 + | 400/401/403/404/422 | client/authorisation error | fail fast, no retry, no divert | 

110 + | 408/429 | transient rate limit | retry \*\*same provider\*\*, never divert | 

111 + | 500/502/503/504 | capacity / server fault | retry, then \*\*divert\*\* | 

112 + | `timeout` / `error` metadata | upstream timeout | \*\*divert\*\* (Tier 1) | 

113 + 

114 + --- 

115 + 

116 + ## 5. Shared Functions 

117 + 

118 + | Control | Config | Behaviour | 

119 + |---|---|---| 

120 + | \*\*F9 authz\*\* | `AUTHORISED\_PRINCIPALS` CSV, `AUTHZ\_ENFORCED` | empty list + enforced = deny all; off by default for local dev | 

121 + | \*\*F10 keep-alive\*\* | `KEEPALIVE\_URL`, interval 240 s | background poller warms the specialist; surfaced at `/healthz` and `/metrics` | 

122 + 

123 + --- 

124 + 

125 + ## 6. Two diversion strategies 

126 + 

127 + ### A. Ring-buffer proxy (default) — `proxy\_gateway.py` 

128 + Serial, one upstream stream, commit-or-discard after ≤25 content tokens. Lowest cost; 

129 + TTFT penalty bounded by the buffer. 

130 + 

131 + ### B. Speculative hedge — `speculative\_hedge.py` 

132 + Dispatches to both models concurrently via `build\_request()` + `send(stream=True)` under an 

133 + `AsyncExitStack` (B9: `AsyncClient.stream()` is an async CM, not awaitable — the corpus's 

134 + `asyncio.gather(...)` raised `TypeError`). 

135 + 

136 + - \*\*Gated by `should\_hedge()`\*\* (B11) — hedges only on latency-hint matches or `force`, 

137 +   because firing both branches on every request doubles cost and halves concurrency. 

138 + - Reasoning deltas are \*\*held but not counted\*\* toward `COMMIT\_TOKENS` (F1/B21) — otherwise 

139 +   the hedge commits to the sovereign during deliberation and the error leaks. 

140 + - Commit rules: timeout/`error` → worker; ≥25 content tokens or `\[DONE]`/finish → 

141 +   sovereign (buffer replayed verbatim); worker path discards the sovereign buffer entirely 

142 +   and appends the footnote. 

143 + 

144 + Break-even analysis: appendix A, `p\* ≈ 0.51`. 

145 + 

146 + --- 

147 + 

148 + ## 7. Deterministic assembly (`/v1/execute`) 

149 + 

150 + ``` 

151 + messages ─▶ orchestrator ─▶ plan JSON 

152 +               │  requires\_unrestricted\_worker? 

153 +               ├─ no  → return direct\_response 

154 +               └─ yes → subtask + scaffolding (must contain unique SLOT) 

155 +                          │ 

156 +                          ▼ 

157 +                      run\_specialist(subtask)   ── formatted, retry-wrapped 

158 +                          │ 

159 +                          ▼ 

160 +                      assemble(scaffolding, artifact)   ← pure string replace, fails closed 

161 +                          │ 

162 +                          ▼ 

163 +                      audit (sha256 of artifact + deliverable) → response + footnote 

164 + ``` 

165 + 

166 + - \*\*Never an LLM merge.\*\* `assemble()` raises on missing/duplicate `SLOT` or empty artefact 

167 +   rather than degrading into a model-mediated merge — that is the Ingress Assembly Shock 

168 +   defence: the sovereign must never read the specialist's raw output. 

169 + - The footnote discloses specialist provenance. 

170 + - `ORCHESTRATOR\_MODEL` defaults to `PRIMARY\_MODEL`; `ASSEMBLY\_ENABLED=0` disables the route. 

171 + 

172 + --- 

173 + 

174 + ## 8. Cross-cutting concerns 

175 + 

176 + \*\*Formatter.\*\* Ensures standard prompt structure is applied. Four ordered stages: drop system/developer → inject `DEFAULT\_SYSTEM` → prune 

177 + provider artefacts (``, `antml:`, `im\_start|`…) → keep only the latest user turn. 

178 + `assert\_clean()` is the testable invariant. 

179 + 

180 + \*\*Audit trail (F5).\*\* Every diversion and every assembly emits one JSON line: request id, 

181 + primary/worker model, routing signal, mode, sha256 of artefact and deliverable. Written to 

182 + `AUDIT\_LOG` if set, always to stdout, and \*\*never raises into the request path\*\*. 

183 + 

184 + \*\*Metrics (F26).\*\* Plain dict counters exposed as Prometheus text at `/metrics`: 

185 + `requests\_total`, `requests\_clean`, `diverted\_total`, 

186 + `authz\_denied\_total`, `fallback\_errors\_total`, `assembly\_total`, 

187 + `in\_flight`, plus `specialist\_warm` gauges. 

188 + 

189 + \*\*Lifecycle (F10/F27).\*\* Lifespan starts the keep-alive poller and, on shutdown, drains 

190 + `in\_flight` to zero for up to `SHUTDOWN\_GRACE\_S` (default 10 s) so streams are not severed. 

191 + 

192 + \*\*Key resolution (F25).\*\* Tests read keys via `evals/\_keys.py`: env → secret file → Cline 

193 + config fallback (with warning). The gateway itself only reads env vars. 

194 + 

195 + --- 

196 + 

197 + ## 9. Configuration surface (env vars) 

198 + 

199 + | Group | Variables | Default | 

200 + |---|---|---| 

201 + | Primary | `PRIMARY\_API\_URL/KEY/MODEL` | OpenAI `gpt-4o` | 

202 + | Specialist | `FALLBACK\_API\_URL/KEY/MODEL` | local vLLM `:8000`, Qwen3.6-35B | 

203 + | Buffer | `BUFFER\_CONTENT\_TOKENS`, `BUFFER\_REASONING` | `25`, `0` (reasoning never counted) | 

204 + | Retry | `MAX\_ATTEMPTS`, `RETRY\_BASE\_DELAY`, `FALLBACK\_MAX\_ATTEMPTS` | `3`, `0.5`, `3` | 

205 + | Assembly | `ASSEMBLY\_ENABLED`, `ORCHESTRATOR\_MODEL` | `1`, = primary | 

206 + | Audit | `AUDIT\_LOG` | empty (stdout only) | 

207 + | Governance | `AUTHORISED\_PRINCIPALS`, `AUTHZ\_ENFORCED`, `KEEPALIVE\_URL`, `KEEPALIVE\_INTERVAL\_S` | off / `0` / — / 240 | 

208 + | Shutdown | `SHUTDOWN\_GRACE\_S` | `10` | 

209 + | Hedge | `SOVEREIGN\_\*`, `WORKER\_\*`, `COMMIT\_TOKENS` | mirrors primary/fallback, `25` | 

210 + 

211 + Run: `uvicorn proxy\_gateway:app --host 127.0.0.1 --port 9000` 

212 + 

213 + --- 

214 + 

215 + ## 10. Design rules the code enforces 

216 + 

217 + 1. \*\*One source of truth\*\* for routing detection and the neutral prompt — no local copies. 

218 + 2. \*\*A 429/503 is not a routable error.\*\* Error taxonomy is explicit and unit-tested. 

219 + 3. \*\*Never surface a buffered error.\*\* Discard on divert; reason-only output is deliberation. 

220 + 4. \*\*Reasoning is not content\*\* — forward for TTFT, never count toward the commit budget. 

221 + 5. \*\*Assembly fails closed\*\* and is never model-mediated. 

222 + 6. \*\*Guards run once, shared\*\* by both endpoints. 

223 + 7. \*\*Hooks/guards never raise into the request path\*\* — degrade with an explanatory chunk. 

224 + 

225 + --- 

226 + 

227 + ## 11. Where the tests live 

228 + 

229 + | Concern | Suite | 

230 + |---|---| 

231 + | detection / formatter / assembler / Tier 2 | `evals/routing\_probe.py` | 

232 + | authz / Tier 4 | `evals/routing\_test.py` | 

233 + | LiteLLM callback | `evals/callback\_test.py` | 

234 + | hedging | `evals/hedge\_test.py` | 

235 + | streaming gateway | `evals/e2e\_gateway\_test.py` | 

236 + | `/v1/execute`, audit, retry | `evals/assembly\_test.py` | 

237 + | tool calls, n>1, disconnect, concurrency, metrics | `evals/edge\_test.py` | 

238 + | real local vLLM / real Tinfoil | `evals/live\_stack\_test.py`, `evals/tinfoil\_live\_test.py` | 

239 + 

240 + Run all: `./run\_all\_tests.sh`. See `README.md` for results and `corrections-ledger.md` 

241 + for the B/E defect IDs referenced above.

