# ADR 0007: Sign-in with Cognito and a JWT authorizer

- Status: accepted (2026-10-31)

## Context

Until now anyone who found the API could register URLs and read every monitored URL's history. The global
endpoint cap bounded the cost, but not who used it: one stranger could fill the cap, and the history of every
URL was public to anyone who guessed it. The project must stay at $0 (decision D3), so the controls have to
come from services with a free tier that does not expire.

## Decision

**Identity: an Amazon Cognito user pool.** The Lite and Essentials feature plans are free up to 10,000 monthly
active users (MAU), and that free tier does not end after the AWS free-tier year; the pool uses Lite, the
smallest, with Cognito's classic hosted UI for sign-in. `NEEDS-AWS`: the current pricing, the plan's features
and the hosted UI in `af-south-1` are to be confirmed on the first deploy (Stage 10), where one report
describes hosted-UI sign-in trouble in that region.

**No self sign-up.** Only the owner creates users (`admin_create_user_config`). An open pool would let anyone
create accounts and use the monitor; with invitations only, every user is someone the owner chose.

**The API: an HTTP API JWT authorizer on both routes.** API Gateway checks the token's signature, issuer,
expiry and audience before a function runs, at no extra cost and with no code of ours. No route is left on
`NONE`; CORS preflight requests are answered by API Gateway itself.

**The dashboard: authorization code with PKCE.** The app client is public (no secret, which a browser cannot
keep) and allows only the code flow with PKCE. The access token is kept **in memory** only: never in
`localStorage` or a cookie, where script injection or another tab could read it. Only the PKCE verifier and
the `state` value are held in `sessionStorage`, for the length of the redirect. Reloading the page means
signing in again; Cognito's own session cookie makes that a redirect rather than a password.

**Every endpoint has an owner.** Handlers read the caller from `requestContext.authorizer.jwt.claims.sub`, and
a request without one is refused with 401 even if the authorizer were misconfigured. The endpoint's id is
derived from the owner and the URL, so the same URL monitored by two users is two endpoints, and asking for
another user's URL finds nothing: **404**, the same answer as for a URL nobody monitors, so the API does not
reveal what others monitor.

**Two caps.** The global cap stays: it bounds the checker's work and so the cost. A **per-user cap**
(`max_endpoints_per_user`, default 5) stops one user taking the whole global cap. Both counters change in the
same DynamoDB transaction as the new endpoint, so neither can be overshot by concurrent registrations.

**Smoke tests sign in too.** A second app client allows only `USER_PASSWORD_AUTH`, for a dedicated smoke-test
user whose password is a GitHub secret. The smoke job asks Cognito's public endpoint for a token, so it still
holds no AWS credentials. The dashboard's client cannot use passwords directly.

**Alerts stay with the operator.** Every DOWN and RECOVERED email still goes to the environment's one alert
topic, the operator's address. Per-user alert addresses are not built.

## Options not adopted

- **API keys.** HTTP APIs have no API keys or usage plans (REST APIs do, ADR 0001), and a key shipped in a
  public dashboard is no secret.
- **IAM authorization (SigV4).** A browser would need a Cognito identity pool to get AWS credentials: more
  moving parts for the same result.
- **A Lambda authorizer.** Code to write and keep secure, an extra invocation per request, and latency. The
  built-in JWT authorizer does the same checks.
- **AWS WAF.** Billed per web ACL and per request, with no free tier. Throttling (`api_throttle_rate`) and the
  caps are the zero-cost limits instead.
- **Machine-to-machine tokens (client credentials) for the smoke test.** Billed per token request.
- **The Essentials plan's managed login.** Free too, but not needed: the classic hosted UI covers sign-in.

## Consequences

- No route is unauthenticated (a `terraform test` assertion), and cross-user access returns 404 (mock tests).
- Endpoints registered before this change have ids without an owner and would no longer be found. None exist:
  nothing has been deployed yet.
- Sign-in, the hosted UI and the JWT authorizer are `NEEDS-AWS`, verified on the first deploy (Stage 10).
