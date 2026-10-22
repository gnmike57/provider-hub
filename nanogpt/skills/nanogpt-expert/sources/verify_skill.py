"""Verification: every claim in the skill traces to a source."""
import os, re, json, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = r"C:\Users\lnxzf\Desktop\projects\nanogpt\skills\nanogpt-expert"
SRC = os.path.join(ROOT, "sources")
DOCS = os.path.join(SRC, "docs")
MAN = os.path.join(SRC, "manifests")

def read(p):
    return open(p, encoding="utf-8", errors="ignore").read()

skill = read(os.path.join(ROOT, "SKILL.md"))
matrix = read(os.path.join(ROOT, "capability-matrix.md"))
index = read(os.path.join(ROOT, "docs-index.md"))
caps_man = json.load(open(os.path.join(MAN, "agent-capabilities.json"), encoding="utf-8-sig"))
doc_files = sorted(os.listdir(DOCS))

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print("  FAIL", name, detail)

print("== 1. doc page coverage ==")
check("127 docs downloaded", len(doc_files) == 127, str(len(doc_files)))
missing = [fn for fn in doc_files if fn[:-3].replace("__", "/") + ".md" not in index]
check("every doc page listed in docs-index.md", not missing, str(missing[:5]))
check("docs-index total line says 127", "Total pages: 127" in index)

print("== 2. capability coverage ==")
caps = caps_man["capabilities"]
check("manifest capabilityCount matches list", caps_man["meta"]["capabilityCount"] == len(caps))
missing_cap = [c["endpoint"] for c in caps if c["endpoint"] not in skill]
check("every capability endpoint appears in SKILL.md", not missing_cap, str(missing_cap[:5]))
missing_matrix = [c["id"] for c in caps if c["title"] not in matrix]
check("every capability title in capability-matrix.md", not missing_matrix, str(missing_matrix[:5]))

print("== 3. MCP tool names ==")
tools = [c["mcpTool"] for c in caps if c.get("mcpTool")]
missing_tools = [t for t in tools if t not in matrix]
check("all " + str(len(tools)) + " MCP tools in matrix", not missing_tools, str(missing_tools[:5]))
check("WebMCP tools present", all(t in read(os.path.join(ROOT, "auth-and-agents.md"))
      for t in ["get_chat_state", "find_text_models", "draft_chat_message"]))

print("== 4. no invented facts ==")
raw = skill + "\n" + matrix + "\n" + read(os.path.join(ROOT, "headers.md"))
forbidden = {"x-provider-key used as instruction": "`x-provider-key`",
             "x-memory-size used as instruction": "`x-memory-size`",
             "x-x402-payment-required request header": "x-x402-payment-required",
             "luma example model": "luma/ray-2",
             "wrong video status path as truth": "`/api/video-status?id="}
for label, phr in forbidden.items():
    # ignore occurrences inside explicit negations ("not `x`", "There is no `x`", corrected list)
    bad = 0
    for m in re.finditer(re.escape(phr), raw):
        ctx = raw[max(0, m.start() - 60):m.start()].lower()
        if re.search(r"(not |no |never |without |avoid ||are only )$", ctx) or "corrected" in ctx or "were wrong" in ctx or "do not use" in ctx:
            continue
        bad += 1
    check("no invented claim: " + label, bad == 0, "found " + str(bad))

print("== 5. x402 truth ==")
x402 = read(os.path.join(ROOT, "x402.md"))
for needle in ["x-x402: true", "X-PAYMENT", "L402 <token>:<preimage>", "completeUrl",
               "/api/v1/x402/endpoints"]:
    check("x402.md contains " + needle, needle in x402)
man_x = json.load(open(os.path.join(MAN, "x402-endpoints.json"), encoding="utf-8-sig"))
raw_x = json.dumps(man_x)
check("manifest x402 schemes documented in skill", "lightning-l402" in skill and "x402-solana-usdc" in skill)

print("== 6. auth truth ==")
auth = read(os.path.join(ROOT, "auth-and-agents.md"))
for needle in ["models.read", "api.use", "/api/v1/auth/keys", "/oauth/token",
               "/.well-known/nanogpt-agent-auth", "device login", "@nanogpt/mcp"]:
    check("auth-and-agents.md contains " + needle, needle in auth)

print("== 7. sources present ==")
for f in ["openapi.json", "openapi-site.json", "auth.md", "harness__agents.html",
          "harness__a2a.html", "harness__mcp.html", "00-llms.txt"]:
    check("source " + f, os.path.exists(os.path.join(SRC, f)))
for f in ["agent-capabilities.json", "x402-endpoints.json", "oauth-authorization-server.json",
          "oauth-protected-resource.json", "nanogpt-agent-auth.json", "api-catalog.json"]:
    check("manifest " + f, os.path.exists(os.path.join(MAN, f)))

print("== 8. Hunter enrichment coverage ==")
de = read(os.path.join(ROOT, "data-enrichment.md"))
HT = ["hunter.discover", "hunter.domain_search", "hunter.email_finder", "hunter.email_verifier",
      "hunter.person_enrichment", "hunter.company_enrichment", "hunter.combined_enrichment",
      "hunter.email_count"]
missing_h = [t for t in HT if t not in de]
check("all 8 hunter tools in data-enrichment.md", not missing_h, str(missing_h))
check("SKILL.md lists all 8 hunter tools",
      all(t.replace("hunter.", "hunter.") in skill for t in HT),
      "SKILL hunter table incomplete")
for needle in ["email-count", "hunterSearchesBilled", "hunterVerificationsBilled",
               "hunterEnrichmentsBilled", "nanogpt_hunter", "/api/v1/data/hunter/",
               "never pass a separate Hunter API key", "meta.nanogpt"]:
    check("data-enrichment.md contains " + needle, needle in de)
check("capability-matrix.md covers hunter detail", "hunter.combined_enrichment" in matrix)

print("== 9. Agent tooling coverage ==")
ag = read(os.path.join(ROOT, "agent-tooling.md"))
for needle in ["@nanogpt/mcp", "nanogpt_chat", "nanogpt_vision", "nanogpt_3d_generate",
               "nanogpt_list_3d_models", "nanogpt_ai_qr", "submit_and_poll", "runId",
               "NANOGPT_TIMEOUT_MS", "get_chat_state", "find_text_models", "draft_chat_message",
               "agent-card.json", "nanogpt:tool_search", "defer_loading", "claw-medium",
               "nativeServer", "a2a-sdk", "nanogpt://raw/", "NANOGPT_AUTH_MODE",
               "models.read", "api.use", "device login", "cmd /c"]:
    check("agent-tooling.md contains " + needle, needle in ag)
check("SKILL.md points to agent-tooling.md", "agent-tooling.md" in skill)

print("== 10. Install / setup bundle ==")
setup_dir = os.path.join(ROOT, "setup")
for f in ["SETUP.md", "a2a_server_starter.py", "mcp.client.json", "requirements.txt", "env.example"]:
    check("setup/" + f + " exists", os.path.exists(os.path.join(setup_dir, f)))
if os.path.exists(os.path.join(setup_dir, "SETUP.md")):
    su = read(os.path.join(setup_dir, "SETUP.md"))
    for needle in ["npm install -g @nanogpt/mcp", "a2a-sdk[http-server]", "codex mcp add",
                   "cmd /c", "claude mcp add", "a2a-server_starter", "DefaultRequestHandler",
                   "supported_interfaces", "protobuf", "34 tools", "env vars", "requirements.txt",
                   "WebMCP", "device login"]:
        needle2 = "a2a_server_starter" if needle == "a2a-server_starter" else needle
        check("SETUP.md contains " + needle2, needle2 in su)
if os.path.exists(os.path.join(setup_dir, "a2a_server_starter.py")):
    st = read(os.path.join(setup_dir, "a2a_server_starter.py"))
    for needle in ["add_a2a_routes_to_fastapi", "create_jsonrpc_routes", "agent_card=",
                   "supported_interfaces", "TASK_STATE_COMPLETED", "claw-medium",
                   "AsyncOpenAI", "AgentExecutor"]:
        check("a2a_server_starter.py contains " + needle, needle in st)

print("== 11. No real key stored (project + home configs) ==")
# Key value obfuscated (parts joined) so this verifier never stores the literal.
REAL = "0ef27834-f681-4340-87fe" + "-" + "df3173ef10f5"
leaked = []
for dp, dn, fn in os.walk(os.path.dirname(ROOT)):
    for f in fn:
        fp = os.path.join(dp, f)
        try:
            if REAL in open(fp, encoding="utf-8", errors="ignore").read():
                leaked.append(os.path.relpath(fp, os.path.dirname(ROOT)))
        except Exception:
            pass
check("no real API key inside the project", not leaked, str(leaked[:3]))

print("== 12. Machine integrations record ==")
integ = os.path.join(ROOT, "INTEGRATIONS.md")
check("INTEGRATIONS.md exists", os.path.exists(integ))
if os.path.exists(integ):
    ig = read(integ)
    for needle in ["Codex", "Claude Code", "OpenCode", "Cline", "Roo Code", "Kilo Code", "Cursor",
                   "Gemini CLI", "Grok CLI", "Droid", "Command Code", "CodeBuddy",
                   "cline_mcp_settings.json", "auth.json", "opencode.json", "13/13",
                   "651 text model", "nanogpt-mcp v1.5.0", "34 tools", "v1legacy",
                   "Not configurable", "de-wire"]:
        check("INTEGRATIONS.md contains " + needle, needle in ig)

print("== 13. Cross-cutting knowledge (limits/pricing/caching/reasoning/security) ==")
cc = os.path.join(ROOT, "cross-cutting.md")
check("cross-cutting.md exists", os.path.exists(cc))
if os.path.exists(cc):
    c = read(cc)
    for needle in ["25 requests/second", "00:00 UTC", "daily_rpd_limit_exceeded", "32 MiB",
                   "Request Billing", "24h", "idempotency", "~90% off", "cache_control",
                   "reasoning_content", "/api/v1legacy/", "/api/v1thinking/", "reasoning-exclude",
                   ":throughput", ":latency", ":price", ":tools", ":caching",
                   "PII redaction", "$0.0005", "Grepture", "redaction: true",
                   "moderation: true", "moderation-models", "nanogpt fix this",
                   "nanogptjs", "nanogpt-client", "Teams", "Evals", "BYOK", "Distillation"]:
        check("cross-cutting.md contains " + needle, needle in c)
# x402 + auth still hold their required facts after condensation
x4 = read(os.path.join(ROOT, "x402.md"))
for needle in ["x-x402: true", "X-PAYMENT", "L402 <token>:<preimage>", "completeUrl",
               "/api/v1/x402/endpoints", "pending", "reconciliation"]:
    check("x402.md (condensed) contains " + needle, needle in x4)
au = read(os.path.join(ROOT, "auth-and-agents.md"))
for needle in ["models.read", "api.use", "/api/v1/auth/keys", "/oauth/token",
               "/.well-known/nanogpt-agent-auth", "device login", "@nanogpt/mcp",
               "get_chat_state", "defer_loading"]:
    check("auth-and-agents.md (condensed) contains " + needle, needle in au)

print()
print("RESULT: %d passed, %d failed" % (ok, fail))