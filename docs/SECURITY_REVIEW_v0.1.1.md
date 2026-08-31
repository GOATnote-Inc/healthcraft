# Security Review — ED Decision Rules MCP v0.1.1

**Date:** 2026-05-11
**Scope:** `app.py`, `src/healthcraft/agents_assemble/`, `requirements.txt`, `.vercelignore`, `.gitignore`, `Dockerfile`, deployment posture at `https://mcp.thegoatnote.com/mcp`
**Reviewer:** Internal post-submission audit prior to expert review
**Methodology:** bandit static analysis, pip-audit CVE scan, secret-pattern grep across all git-tracked files, manual code review of every entry point, network and CORS posture inspection, container image audit, log-hygiene trace, deployment-time verification on production

## Summary

| Severity | Count | Status |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 1 (PHI in logs) | **Fixed in v0.1.1** |
| Low | 2 (verbose exception, defensive .vercelignore) | **Fixed in v0.1.1** |
| Informational | 4 | Documented; non-blocking |

**Net posture:** Production-ready for the v0.1 hackathon submission. No blocking findings. The Medium issue (raw request-body content written to stderr) had no known PHI exposure in practice because all callers to date were either MCP Inspector, Prompt Opinion's own backend (no PHI in synthetic patients), or curl tests with synthetic data — but the *capability* existed and is now removed.

## Findings

### M1 (Medium → Fixed) — Request body content leaked to Vercel function logs

**File:** `app.py` `_dispatch_mcp_post`
**Before:** logged the first 400 chars of the raw request body to stderr. Vercel persists stderr in function logs accessible to anyone with project read access.
**Risk:** Real callers POST FHIR Bundles containing `Patient.name`, `Patient.birthDate`, `Patient.address`, MRN, and active `Condition` codes. Any of these in the first 400 bytes of a request body would end up in production logs.
**Fix:** v0.1.1 logs only `method`, `byte count`, and User-Agent. The rule version hash and bundle SHA-256 already in the response payload provide the audit trail; no payload content needs to be persisted server-side.
**Verification:** `grep -n "body=" app.py` returns no match in the log statement.

### L1 (Low → Fixed) — Exception messages from `tools/call` returned to caller

**File:** `src/healthcraft/agents_assemble/streamable_http_server.py`
**Before:** `tools/call` exception handler returned `f"Tool error: {exc}"` to the MCP client.
**Risk:** Information disclosure. `{exc}` can include file paths, module names, or framework internals (especially for deeply-nested errors). A malicious caller probing for stack-trace details could infer the runtime, library versions, and partial source layout.
**Fix:** Caller now receives `f"Internal error executing tool '{tool_name}'. See server logs."` (deterministic, no internals). Full traceback continues to log server-side via `logger.exception()` for our own diagnostics.

### L2 (Low → Fixed) — `.vercelignore` did not explicitly exclude `.env`

**File:** `.vercelignore`
**Before:** relied on `.gitignore` (which does exclude `.env`) for Vercel build-bundle filtering.
**Risk:** Belt-and-braces. Vercel respects both `.gitignore` and `.vercelignore` for the upload bundle; relying on only one is a single point of failure. A future change to `.gitignore` could inadvertently expose `.env` to Vercel uploads.
**Fix:** v0.1.1 `.vercelignore` explicitly excludes `.env`, `.env.*`, `*.pem`, `*.key`, `credentials.json`, `secrets.json`.

## Informational findings (non-issues, documented for reviewer transparency)

### I1 — bandit B104 `hardcoded_bind_all_interfaces` (3 sites)

**Locations:** `cds_hooks_server.py:214`, `streamable_http_server.py:626`, `streamable_http_server.py:655`
**Finding:** Server default host is `0.0.0.0` (all interfaces).
**Context:** These CLI entrypoints are designed to run *behind* a reverse proxy (Vercel's edge in production; user's choice of host locally). The Vercel runtime invokes the FastAPI app via ASGI — the stdlib `0.0.0.0` bind path is never taken in production. For local stdlib use, `0.0.0.0` is the documented binding so containers expose the port; users on bare metal who want loopback-only can pass `--host 127.0.0.1`.
**Disposition:** Accepted as designed. No code change.

### I2 — pip-audit CVEs in dev/test environment

**Finding:** `pip-audit` against the local `.venv` flags 9 CVEs across 6 packages (`cryptography`, `pip`, `pygments`, `pytest`, `requests`, `urllib3`).
**Context:** None of these are runtime dependencies. `requirements.txt` — the manifest Vercel installs in production — declares only `pyyaml>=6.0`, `jsonschema>=4.0`, `fastapi>=0.110`. The flagged packages are dev/test (`pytest`) or transitive deps of the local sandbox only.
**Disposition:** No production exposure. Local `.venv` should periodically `pip install --upgrade` to clear dev-env CVEs, tracked separately.

### I3 — CORS `Access-Control-Allow-Origin: *` on a POST endpoint

**Finding:** Browsers can POST to `/mcp` from any origin.
**Context:** This MCP server is **explicitly designed for public access** during the v0.1 hackathon. It performs **no state mutation** (every tool is read-only deterministic scoring against caller-supplied inputs), holds **no user-tied session state**, and **persists nothing** about callers. The only authoritative writes happen to the in-memory `WorldState` at module import time (rule library), never per-request. There is no CSRF vector because there is no authenticated session to ride. Auth-required endpoints (planned for v0.2) will tighten CORS accordingly.
**Disposition:** Accepted as designed; documented in `.well-known/oauth-protected-resource` with `auth_required: false`.

### I4 — Dockerfile uses `python:3.11-slim` floating tag (not pinned to digest)

**File:** `src/healthcraft/agents_assemble/docker/Dockerfile`
**Finding:** Base image is `FROM python:3.11-slim` — a floating tag, not a content-addressable digest.
**Context:** Vercel doesn't build this Dockerfile (Vercel uses uv + requirements.txt). The Dockerfile is provided for users who want to self-host. Pinning to a digest hurts long-term reproducibility unless paired with an automated bump (Dependabot, Renovate). For the v0.1 release we accept the freshness tradeoff.
**Disposition:** Roadmap item for v0.2 (Renovate config + digest pin).

## Verified posture summary

| Control | Status | Evidence |
|---|---|---|
| Non-root container user | **PASS** | `Dockerfile:34` `USER superpower` (uid 10001) |
| Minimal base image | **PASS** | `python:3.11-slim` |
| `.env` excluded from git | **PASS** | `.gitignore:.env` |
| `.env` excluded from Vercel upload | **PASS** | `.vercelignore:.env` (v0.1.1) |
| No secrets in git history | **PASS** | `git ls-files \| xargs grep -lE "AIza\|sk-\|sso-key\|BEGIN.*PRIVATE KEY"` returns empty |
| No shell injection | **PASS** | `grep -E "os.system\|shell=True\|eval\|exec\|pickle.load"` returns empty across `src/agents_assemble/` and `app.py` |
| No PHI in logs | **PASS (v0.1.1)** | request body content removed from `[MCP-IN]` log line |
| No exception detail in error responses | **PASS (v0.1.1)** | `tools/call` exception → generic message; full traceback only server-side |
| HSTS | **PASS** | `strict-transport-security: max-age=63072000` (Vercel edge) |
| X-Content-Type-Options | **PASS (v0.1.1)** | `nosniff` |
| X-Frame-Options | **PASS (v0.1.1)** | `DENY` |
| Content-Security-Policy | **PASS (v0.1.1)** | `default-src 'none'; frame-ancestors 'none'` |
| Referrer-Policy | **PASS (v0.1.1)** | `no-referrer` |
| Request body size cap | **PASS (v0.1.1)** | 5 MB hard limit; over-limit returns 413 before body read |
| Unknown-tool refusal | **PASS** | clean JSON-RPC `-32602` error, no crash |
| TLS posture | **PASS** | Let's Encrypt cert via Vercel edge, valid through Aug 9 2026 |
| FHIR Bundle SHA-256 in audit trail | **PASS** | Every `applyDecisionRule` response includes `sharp.trace[].bundleSha256` |
| Rule version SHA-256 in audit trail | **PASS** | Every response includes `ruleVersion` (full) + `ruleVersionShort` |
| MCP spec compliance | **PASS** | Anthropic's MCP Inspector exit 0 for `tools/list` against prod URL |
| SMART v2 scope discipline | **PASS** | 5 narrow `patient/Resource.rs` scopes; no wildcards, no system-scope, no `.write` |
| Open-access disclosure | **PASS (v0.1.1)** | `/.well-known/oauth-protected-resource` documents `auth_required: false` with v0.2 roadmap |

## Threat model (informal)

| Threat | Mitigation |
|---|---|
| Caller exfiltrates other tenants' data | Server has no tenants and no per-caller state. Tools score only the variables/bundle the caller themselves supplies in the same request. |
| Caller injects malicious FHIR Bundle to execute code | All bundle parsing goes through `json.loads` and field access via `.get()`. No `eval`, `pickle`, dynamic import, or shell. No URL fetching (no SSRF). |
| Caller exhausts function memory | 5 MB body cap + Vercel's per-invocation memory limit (1024 MB configured). |
| Caller floods server with requests | Vercel platform DDoS protection at edge. App-level rate-limit deferred to v0.2 (Vercel Rate Limit API or middleware). |
| Caller poisons audit trail | Rule version + bundle SHA-256 are computed server-side per request, never accepted from caller input. |
| Caller leaks PHI back through logs | v0.1.1 log line carries only method + byte count + UA. No body content. |
| Caller infers internals via error messages | v0.1.1 exception handler returns generic message; full traceback only on server-side log. |
| Caller bypasses rule version | Each response carries the canonical SHA-256 of the rule definition at the time it was scored. Reproducible offline. |
| Supply chain — malicious dep | 3 runtime deps, all from PyPI top-tier maintainers (pyyaml, jsonschema, fastapi). `pip-audit` flags zero CVEs against this set. |
| Supply chain — malicious base image | Roadmap to digest-pin Dockerfile in v0.2; Vercel runtime doesn't use the Dockerfile. |

## Roadmap to v0.2 (security-driven)

1. OAuth 2.1 Resource Server posture per [MCP June 2025 spec](https://auth0.com/blog/mcp-specs-update-all-about-auth/) — PKCE, Dynamic Client Registration, RFC 8707 Resource Indicators.
2. App-level rate limiting (Vercel Rate Limit API).
3. Pin Dockerfile base image to digest + Renovate auto-bumps.
4. Container scanning in CI (Trivy or Grype).
5. SAST in CI (Semgrep or CodeQL).
6. Regular `pip-audit` in CI with failure on new CVEs.
7. SBOM generation (cyclonedx).

## Sources

- [MCP Security Best Practices (Anthropic)](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [OWASP MCP Server Development Guide](https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/)
- [MCP June 2025 spec — OAuth 2.1 + Resource Servers](https://auth0.com/blog/mcp-specs-update-all-about-auth/)
- [SMART App Launch v2.2.0 — Best Practices](https://hl7.org/fhir/smart-app-launch/best-practices.html)
- [RFC 9728 — Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728)
- bandit `1.9.x` (Python AST security linter)
- pip-audit `2.x` (vuln scanner)
