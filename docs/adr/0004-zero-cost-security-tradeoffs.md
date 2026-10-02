# ADR 0004: Security controls within a zero-cost budget

- Status: accepted (2026-10-02)

## Context

VigilWatch is a public demo: anyone can open the dashboard and register a URL, and a Lambda
then fetches that URL on a schedule. That is a server-side request forgery (SSRF) and abuse
surface. Several standard controls (WAF, customer-managed KMS keys, CloudFront access logs,
custom TLS certificates) cost money every month.

## Decision

Controls adopted:

- **SSRF guard** (`lambda/common/urlguard.py`): http/https only; no userinfo; URL length <= 2048;
  valid port; every resolved address must be globally routable (rejects loopback, RFC 1918,
  link-local including 169.254.169.254, CGNAT 100.64/10, multicast, unspecified, IPv4-mapped
  IPv6). Applied on registration and again before every probe, because DNS can change.
- **No redirects** are followed, so a public URL cannot bounce the probe to an internal one.
- **Endpoint cap** (`max_endpoints`, default 10) and **API throttling** (5 rps, burst 10).
- **Least-privilege IAM** per function, enforced by `terraform test`.
- **Private S3 + OAC**, HTTPS only, CSP/HSTS/frame/nosniff headers, CORS limited to the dashboard.
- **Keyless CI** via GitHub OIDC, saved plans, manual approval, gitleaks and trivy.

Accepted risks (listed in `.trivyignore`):

- No authentication; anyone can add a URL (bounded by the cap and throttling).
- No WAF (minimum $5/month).
- AWS-owned or AWS-managed encryption keys instead of customer-managed KMS keys ($1/key/month).
- SNS topic not encrypted, because CloudWatch alarms cannot publish to a topic using the
  AWS-managed `aws/sns` key. Alerts contain URLs and status codes, no secrets.
- Default CloudFront certificate (no custom domain), so the TLS policy is AWS's default.
- Residual DNS-rebinding window between validation and connect. The functions are not in a
  VPC, and the only private target that exists there (the Lambda runtime API) is blocked by
  the guard. Impact is low.

## Consequences

The demo can stay public and free. If the project gets a budget, the first additions should be
Cognito auth (removes anonymous registration) and WAF rate-based rules.
