# Security Policy

## Reporting Security Issues

If you discover a security vulnerability in HEALTHCRAFT, please report it
responsibly. **Do not open a public GitHub issue.**

Email: **b@thegoatnote.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment

We will acknowledge receipt within 48 hours and provide a detailed response
within 5 business days.

## Scope

HEALTHCRAFT is a research benchmark environment using **synthetic data only**.
No real patient data, PHI, or PII is present in the codebase or generated
entities.

Security considerations:
- **API keys**: Never committed to the repository. Use `.env` (gitignored).
  See `.env.example` for the required variables.
- **Docker credentials**: Default development passwords are provided via
  environment variable substitution. Override via `.env` for any non-local
  deployment.
- **Evaluation results**: Contain only synthetic data and model outputs.
  No sensitive information.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
