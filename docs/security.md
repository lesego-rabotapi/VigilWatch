# Security

What VigilWatch protects, from whom, which control does it, and the test that proves each control. Risks
accepted on purpose are listed at the end with their reason. Decisions: ADR 0004 (zero-cost security),
ADR 0007 (sign-in), ADR 0009 (pipeline).

## Threat model

**What is protected:** each user's monitored URLs and their history (private to that user), the alert
channel, the AWS account and its bill (the project must stay at $0), and the pipeline that can change prod.

| Actor | What they could try | Main defence |
|---|---|---|
| An anonymous visitor | Register URLs, read any URL's history | Every route needs a Cognito token; self sign-up is off |
| Another user | Read or overwrite someone else's endpoints by guessing URLs or ids (IDOR) | Ids derive from the owner; another user's URL is a 404 |
| Someone with a stolen token | Use it from elsewhere | Tokens live one hour, in memory only, never in storage a script could read |
| A malicious URL (SSRF) | Make the checker probe internal or metadata addresses | URLs are resolved and refused unless every address is public |
| A cost attacker | Fill the monitor, flood the API | Global and per-user caps, API throttling, invitation-only accounts |
| Someone who can push to the repository or open a pull request in it | Use the pipeline to change or read prod | OIDC roles trusted for `main` and the reviewed `production` environment only; pull requests get a read-only role |

## Controls

| Control | What it does | Proven by |
|---|---|---|
| JWT authorizer on every route | API Gateway checks the token's signature, issuer, expiry and audience before any function runs; no route is on `NONE` | `terraform/modules/api/tests/api.tftest.hcl` |
| The functions check the caller too | A request that reaches a function without a plain subject is refused with 401 | `tests/unit/test_auth.py`, `tests/mock/test_owner_scoping.py` |
| Owner-scoped endpoints (no IDOR) | The id derives from the owner and the URL, and the owner on the item is checked: another user's URL is a 404, the same answer as an unmonitored URL | `tests/mock/test_owner_scoping.py` |
| A per-user cap and the global cap | Both counters change in the endpoint's own transaction, so concurrent registrations cannot pass either | `tests/mock/test_atomic_cap.py`, `tests/mock/test_owner_scoping.py` |
| Invitation-only accounts, code flow only | Self sign-up is off; the dashboard's client has no secret, allows only the code flow, and redirects only to the dashboard | `terraform/modules/auth/tests/auth.tftest.hcl` |
| PKCE, token in memory | The dashboard signs in with PKCE and a checked `state`; the access token is kept in memory only, never in `localStorage`, `sessionStorage` or a cookie | `frontend/tests/auth.test.js`, `frontend/tests/app.test.js` |
| SSRF guard | Only http and https; every resolved address must be public; no credentials in URLs; redirects are not followed | `tests/unit/test_urlguard.py`, `tests/unit/test_probe.py` |
| Input validation at the edges | Lengths, ports, status codes and bodies are checked at their boundaries | `tests/mock/test_input_boundaries.py` |
| Errors without internals | Known errors carry a stable code; anything else is a generic 500 with only the request id | `tests/mock/test_error_codes.py` |
| Functions with least privilege | Each function's role allows exactly the calls it makes, proven by running it under those policies | `tests/mock/test_iam_policies.py`, `terraform/modules/compute/tests/compute.tftest.hcl` |
| Content-Security-Policy and security headers | No inline script, `connect-src` limited to the API and Cognito, frames refused, HSTS; server data is written with `textContent` | `terraform/modules/frontend/tests/frontend.tftest.hcl`, `frontend/tests/view.test.js` |
| A private dashboard bucket | Reached only through CloudFront's origin access control | `terraform/modules/frontend/tests/frontend.tftest.hcl` |
| API throttling | A rate and burst limit on every route bounds request charges | `terraform/modules/api/tests/api.tftest.hcl` |
| Keyless, account-checked deploys | OIDC roles, no stored AWS keys; every job checks the account before any AWS call | `tests/test_workflows.py` |
| Write access only from `main` or reviewed prod | The deploy role trusts `main` and the `production` environment; pull requests and drift use a read-only role | `tests/test_terraform_layout.py` |
| Gates that cannot pass by skipping | A skipped or missing smoke test fails the deploy; release records follow what really runs | `tests/test_pipeline_scripts.py`, `tests/unit/test_check_junit.py` |
| Secrets stay secret | The smoke password is a GitHub secret, never printed; a refused sign-in never repeats it; no deployed address in test code | `tests/test_workflows.py`, `tests/unit/test_e2e_harness.py`, `tests/test_e2e_policy.py` |

## Accepted risks

- **No AWS WAF.** It is billed per web ACL and per request. Throttling, the caps and invitation-only accounts
  are the zero-cost limits instead (ADR 0004, ADR 0007).
- **The read-only role can read prod state.** Pull request plans use it, so anyone who can push a branch can
  read prod's Terraform state. Forks cannot. A dev-only role is the fix if collaborators join (ADR 0009).
- **Every alert goes to the operator.** DOWN and RECOVERED emails go to the environment's one topic, so the
  operator sees every user's monitored URLs in alerts. Per-user alert addresses are not built (ADR 0007).
- **No multi-factor authentication.** Accounts are invitation-only and the data is uptime of public URLs;
  Cognito's TOTP can be turned on later if that changes.
- **A password client for the smoke tests.** It allows `USER_PASSWORD_AUTH` for one test user whose password
  is a GitHub secret. The dashboard's own client cannot take passwords.
- **Reloading the page signs out.** The token is in memory only; Cognito's session makes signing in again a
  redirect. Refresh tokens are not used in the browser.
- **One region.** The checker, the API and the alarms share `af-south-1` (ADR 0006).
- **Unverified on AWS (`NEEDS-AWS`).** The Cognito plan's price and features, the hosted UI in `af-south-1`,
  the JWT authorizer's behaviour and the access log's `integrationStatus` are to be checked on the first
  deploy (Stage 10).
