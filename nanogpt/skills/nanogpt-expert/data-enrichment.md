# Hunter.io enrichment & Data API (verified)

> Sources: `sources/docs/api-reference__endpoint__data-api.md` (61 "hunter" mentions),
> `sources/docs/api-reference__endpoint__data-extraction.md`,
> `sources/manifests/agent-capabilities.json`.
> **Note:** neither OpenAPI spec (`openapi.json`, `openapi-site.json`) contains any Hunter path —
> these endpoints are documented only in the prose docs and the agent-capabilities manifest.

Hunter is billed through **NanoGPT**. You authenticate with your NanoGPT API key only —
**never pass a separate Hunter API key** (for `GET`, `api_key`/`apiKey` params are stripped;
for `POST`, they are not forwarded).

## The 8 Hunter tools

| Catalog ID | Data API path | Direct endpoint | Methods | Provider | Pricing |
|---|---|---|---|---|---|
| `hunter.discover` | `POST /api/v1/data/hunter/discover` | `/api/v1/hunter/discover` | POST | Hunter | **Free** |
| `hunter.email_count` | `/api/v1/data/hunter/email-count` | `/api/v1/hunter/email-count` | GET, POST | Hunter | **Free** |
| `hunter.domain_search` | `/api/v1/data/hunter/domain-search` | `/api/v1/hunter/domain-search` | GET, POST | Hunter | Hunter **search**-credit + NanoGPT markup |
| `hunter.email_finder` | `/api/v1/data/hunter/email-finder` | `/api/v1/hunter/email-finder` | GET, POST | Hunter | Hunter **search**-credit + markup |
| `hunter.email_verifier` | `/api/v1/data/hunter/email-verifier` | `/api/v1/hunter/email-verifier` | GET, POST | Hunter | Hunter **verification**-credit + markup |
| `hunter.person_enrichment` | `/api/v1/data/hunter/people/find` | `/api/v1/hunter/people/find` | GET, POST | Hunter | Hunter **enrichment**-credit + markup |
| `hunter.company_enrichment` | `/api/v1/data/hunter/companies/find` | `/api/v1/hunter/companies/find` | GET, POST | Hunter | Hunter **enrichment**-credit + markup |
| `hunter.combined_enrichment` | `/api/v1/data/hunter/combined/find` | `/api/v1/hunter/combined/find` | GET, POST | Hunter | Hunter **enrichment**-credit + markup |

What each does (manifest summary: "Find and verify professional emails, enrich people and
companies, and inspect domain email counts"):
- **domain-search** — find all emails at a domain.
- **email-finder** — most likely email for a named person at a company/domain.
- **email-verifier** — verify deliverability of a single email address.
- **discover** — domain/lead discovery. Free.
- **email-count** — count emails on a domain. Free.
- **people/find** (person_enrichment) — enrich a person profile.
- **companies/find** (company_enrichment) — enrich a company profile.
- **combined/find** (combined_enrichment) — combined person+company enrichment.

## Calling conventions

### 1. Direct REST (path-style) — simplest
```bash
# GET: params forwarded except api_key, apiKey, endpoint, path
curl "https://api.nano-gpt.com/api/v1/hunter/domain-search?domain=example.com" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"

# POST: JSON body params are forwarded
curl https://api.nano-gpt.com/api/v1/hunter/domain-search \
  -H "Authorization: Bearer $NANOGPT_API_KEY" \
  -H "Content-Type: application/json" -d '{"domain": "example.com"}'
```

### 2. Generic dispatch (single entry point)
```bash
curl "https://api.nano-gpt.com/api/v1/hunter?endpoint=domain-search&domain=example.com" \
  -H "Authorization: Bearer $NANOGPT_API_KEY"

# POST: select target with `endpoint` or `path`; nested `params` object also supported
curl -X POST https://api.nano-gpt.com/api/v1/hunter \
  -H "Authorization: Bearer $NANOGPT_API_KEY" -H "Content-Type: application/json" \
  -d '{"endpoint": "domain-search", "params": {"domain": "example.com"}}'
```

### 3. Data API (unified, discoverable)
```bash
curl https://api.nano-gpt.com/api/v1/data/hunter/domain-search \
  -H "Authorization: Bearer $NANOGPT_API_KEY" -H "Content-Type: application/json" \
  -d '{"domain": "example.com"}'

curl https://api.nano-gpt.com/api/v1/data \
  -H "Authorization: Bearer $NANOGPT_API_KEY" -H "Content-Type: application/json" \

## Request parameters (manifest schema)

`endpoint`, `domain?`, `company?`, `email?`, `full_name?`, `first_name?`, `last_name?`

Mapping: `domain` → domain-search / email-count; `full_name`+`first_name`+`last_name`
(+`domain`/`company`) → email-finder; `email` → email-verifier; `company` → company/combined
enrichment. Query params are forwarded verbatim (except the four stripped names), so Hunter's own
params work too.

## Response shape (verified)

```json
{
  "data": {},
  "meta": {
    "nanogpt": {
      "endpoint": "domain-search",
      "hunterSearchesBilled": 1,
      "hunterVerificationsBilled": 0,
      "hunterEnrichmentsBilled": 0,
      "costUsd": 0.01
    }
  }
}
```
`data` is Hunter's own response (pass-through). `meta.nanogpt` is the NanoGPT billing wrapper — it
reports which credit type was consumed (searches vs verifications vs enrichments) and `costUsd`.

## Aliases accepted by the generic `endpoint`/`path` selector

`hunter.domain-search`→`hunter.domain_search`, `hunter.email-finder`→`hunter.email_finder`,
`hunter.email-verifier`→`hunter.email_verifier`, `hunter.people.find`/`hunter.person`→`hunter.person_enrichment`,
`hunter.company`/`hunter.companies.find`→`hunter.company_enrichment`,
`hunter.combined.find`→`hunter.combined_enrichment`, `hunter.email-count`→`hunter.email_count`.

## MCP

One tool: **`nanogpt_hunter`** (status `available`, auth `api_key_or_session`, sync). Wraps
`GET /api/v1/hunter`, so pass `endpoint` plus the tool's params through it.

## Data API wrapper behavior (applies to all 8)

- Discovery: `GET /api/v1/data` (alias `GET /api/v1/data/endpoints`) lists the full catalog of 20
  endpoints (`meta.providers` = `Apify`, `Firecrawl`, `Hunter`, `NanoGPT`).
- `GET` on a non-GET tool returns its metadata object instead of dispatching.
- Wrapper errors: `400 invalid_json` / `invalid_body` / `missing_endpoint`, `404 unknown_endpoint`,
  `405 method_not_allowed`, `500 unsupported_data_endpoint`. Shape:
  `{"error":{"message":"...","type":"invalid_request_error","code":"unknown_endpoint"}}`.
- Catalog response cacheable (`Cache-Control: public, max-age=300, stale-while-revalidate=3600`).
- Base: `https://api.nano-gpt.com/api/v1/data` (local: `http://localhost:3000/api/v1/data`).

## Billing caveats (from the Data Extraction guide)

- Responses include data **plus** NanoGPT billing metadata.
- Partial results may still be billed if usable data was produced before a failure.
- x402 accountless is available on some Data API paths (`web/search`, `url/scrape`) but **not**
  documented for Hunter paths — use `GET /api/v1/x402/endpoints` as the source of truth.

## Live verification (zero-cost + one 1-credit call)

Observed against the real API. Two documented facts were incomplete and are corrected here.

| Call | Route | Result | Billing |
|---|---|---|---|
| email-count `stripe.com` | direct GET `/api/v1/hunter/email-count` | 200, `data.total=3964` + department/seniority breakdown | `costUsd: 0` |
| email-count `openai.com` | generic GET `?endpoint=email-count` | 200, `data.total=1923` | 0 |
| email-count `github.com` | body dispatch `POST /api/v1/data` | 200, `data.total=4442` | 0 |
| discover `nano-gpt` | direct POST `/api/v1/hunter/discover` | 200, `data[]` with `domain`, `organization`, `emails_count` | `costUsd: 0` (free, confirmed) |
| domain-search `nano-gpt.com` | direct GET `/api/v1/hunter/domain-search` | 200, `meta.results=3` | `hunterSearchesBilled: 1, costUsd: 0.02695` (confirmed) |

**All three dispatch styles work** (direct path, generic `?endpoint=`, and Data API body-style).

### Real response shape (richer than the docs show)

The docs show a minimal `{data, meta:{nanogpt}}`. The live envelope is:

```json
{
  "data": { ... hunter payload ... },
  "meta": {
    "results": 3, "results_approximate": false, "limit": 10, "offset": 0,
    "params": {"domain": "nano-gpt.com", "company": null, "type": null,
               "seniority": null, "department": null, "decision_maker": null},
    "nanogpt": {"provider": "hunter", "endpoint": "domain-search",
                "hunterSearchesBilled": 1, "hunterVerificationsBilled": 0,
                "hunterEnrichmentsBilled": 0, "costUsd": 0.02695}
  },
  "status": 200
}
```

Undocumented-but-real fields confirmed live: **`meta.params`** (echoes the resolved params),
**`meta.nanogpt.provider`** = `"hunter"`, **`meta.results` / `limit` / `offset`** (pagination, same
shape Hunter uses), **top-level `status`**, and **`results_approximate`**. List-style tools
(`discover`, `domain-search`) return `data` as an **array**; count-style (`email-count`) returns
`data` as an **object** with `total` + `department` + `seniority` breakdowns.

The `email-count` breakdown confirms these are real Hunter semantics:
`data` = `total`, `personal_emails`, `generic_emails`, `department{}`, `seniority{}`.
  -d '{"endpoint": "hunter.domain_search", "input": {"domain": "example.com"}}'
```