# Security Policy

## Reporting Security Issues

If you discover a security vulnerability in this project, please report it
responsibly. **Do not open a public GitHub issue.**

**Email:** `b@thegoatnote.com`

For sensitive reports, request a PGP key from the same address.

### What to include

- Affected component (e.g. `app.py`, `src/healthcraft/agents_assemble/...`, MCP wire protocol, deployment configuration)
- Vulnerability class (e.g. authentication bypass, injection, information disclosure, supply-chain)
- Steps to reproduce against `https://mcp.thegoatnote.com/mcp` (preferred) or a self-hosted instance
- Potential impact (confidentiality, integrity, availability)
- Suggested remediation, if any
- Whether you are seeking public credit or wish to remain anonymous

### Disclosure timeline

| Day | Action |
|---|---|
| 0 | Acknowledgment of receipt (within 48 hours) |
| 1–5 | Triage, severity classification, and detailed response with remediation plan |
| 1–30 | Fix development and deployment (Critical / High); 1–90 days for Medium / Low |
| Fix + 7 days | Coordinated public disclosure (CVE assignment if applicable, GitHub Security Advisory, CHANGELOG entry) |

We follow a **90-day coordinated disclosure window** by default and will work with the reporter to extend if a fix legitimately requires more time. Reporters who wait for our acknowledgment before public disclosure receive credit in the advisory.

### Severity classification

We use a simplified CVSS-aligned matrix:

| Severity | Examples |
|---|---|
| Critical | Remote code execution; auth bypass leading to PHI exposure; cryptographic key compromise |
| High | Persistent denial of service; PHI persistence in unauthorized location; injection allowing data exfiltration |
| Medium | Information disclosure of internal details; rate-limit bypass; PHI leakage via logs (see M1 in security review) |
| Low | Lack of defense-in-depth header; configuration finding without active exploit; verbose error messages |
| Informational | Hardening opportunities; coding-style concerns with weak security implications |

## Scope

### In scope (v0.1.x)

- **Production endpoint:** `https://mcp.thegoatnote.com/mcp` and `https://mcp.thegoatnote.com/.well-known/oauth-protected-resource`
- **Backup endpoint:** `https://healthcraft-mcp.vercel.app/mcp`
- **Source code:** files under `src/healthcraft/agents_assemble/`, `app.py`, `requirements.txt`, `vercel.json`, `.vercelignore`, `.gitignore`
- **MCP wire protocol compliance:** initialize, tools/list, tools/call, notifications, batch, ping
- **Documentation accuracy** in `docs/SECURITY_REVIEW_v0.1.1.md`, `docs/COMPLIANCE.md`, `docs/PRE_DEPLOYMENT_CHECKLIST.md`, `MODEL_CARD.md`

### Out of scope

- Self-hosted forks not deployed by the maintainers
- Vulnerabilities in upstream dependencies that are not exploitable in this server's deployment (report those upstream)
- Issues that require physical access to the deploying organization's infrastructure
- Social engineering attacks against maintainers
- Findings that violate the project's stated open-access posture (CORS `*`, public `/mcp` endpoint, `auth_required: false` in v0.1) without demonstrating a security impact beyond the documented design

## Data handling

This software is a **research / hackathon / demonstration project**. It is **not currently configured for use with real PHI**:

- The reference deployment at `mcp.thegoatnote.com` accepts caller-supplied FHIR Bundles but does not retain them. SHA-256 hashes appear in responses for audit reproducibility; original bundle content is not logged or persisted.
- Per the security review in `docs/SECURITY_REVIEW_v0.1.1.md`, request body content is **never** written to the observability log stream as of v0.1.1.
- See `docs/COMPLIANCE.md` for the HIPAA Security Rule §164.312 technical safeguards mapping and `docs/PRE_DEPLOYMENT_CHECKLIST.md` for what an organization must complete before using this software in a regulated clinical setting.

### Hardening posture (v0.1.1)

| Control | Status | Evidence |
|---|---|---|
| TLS 1.3 + HSTS | Live | `curl -sI ... | grep -i hsts` |
| OWASP hardening headers (nosniff, DENY, no-referrer, CSP) | Live | Same curl |
| Body size cap (5 MB) → 413 | Live | Raw-socket test in audit |
| `[MCP-IN]` log line contains no PHI | Live | Source-level invariant test |
| `tools/call` exception returns generic message | Live | Source-level invariant test |
| `.env` excluded from git AND Vercel upload | Live | `.gitignore` + `.vercelignore` |
| `/.well-known/oauth-protected-resource` declares posture | Live | RFC 9728 document served |
| MCP Inspector exit 0 | Verified | Anthropic's official tool |

## Hall of Fame

Reporters of confirmed vulnerabilities will be acknowledged here, with permission.

*(empty — v0.1.1 audit was conducted internally)*

## Supported versions

| Version | Supported | Notes |
|---------|-----------|-------|
| 0.1.1 | Yes | Current release; includes excellence audit fixes (F1-F8) and security audit fixes (M1, L1, L2) |
| 0.1.0 | No — upgrade to 0.1.1 | Original hackathon submission |
| < 0.1.0 | No | Pre-release |

## Related documents

- `docs/COMPLIANCE.md` — HIPAA Security Rule + SOC 2 Trust Service Criteria control mapping
- `docs/SECURITY_REVIEW_v0.1.1.md` — per-finding security review (3 findings, all fixed)
- `docs/PRE_DEPLOYMENT_CHECKLIST.md` — what an organization must complete before clinical deployment
- `src/healthcraft/agents_assemble/MODEL_CARD.md` — FDA CDS classification, intended use, out-of-scope use, privacy guardrails
- `tests/test_agents_assemble/test_excellence_audit.py` — 22 pinned tests covering every security control claimed above

## Legacy note

The original `HEALTHCRAFT` project name in earlier versions of this document referred to the broader Emergency Medicine RL Training Environment. The current v0.1.1 release scope is the MCP server in `src/healthcraft/agents_assemble/`; the broader project remains research code as described in the project root `README.md`.
