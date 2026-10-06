# Security

This document describes V1 operational controls. It is not a compliance
certification, pentest report, or claim that the HTTP headers below “make the
app secure”.

## Threat assumptions

VeraPolitica publishes reviewed official political and civic records. V1 assumes:

- Citizen visitors are unauthenticated and read-only.
- Editorial writes use a shared admin API key, not per-user accounts.
- Official source endpoints may be slow or unavailable; the public site must
  still serve already published data.
- Attackers may probe `/admin`, forge `Host`/`Origin`/`X-Forwarded-*`, and try
  to read stack traces or secrets from errors and logs.

Out of scope for V1: OAuth, citizen accounts, billing, analytics trackers,
recommendation, and enterprise IAM.

## Admin API-key model

`/admin/*` uses HTTP Bearer authentication with `VERAPOLITICA_ADMIN_API_KEY`.
Comparison is constant-time (`secrets.compare_digest`). Missing or invalid
tokens return 401. The token is never accepted from query strings or bodies.

This is an initial operational control for a small editorial team. It is not a
multi-user identity system. Rotate the key if it leaks. Do not put the key in
frontend production pages. The `/demo/` UI embeds a presentation token and must
stay disabled in production.

## Secret handling

- `.env` is gitignored. `.env.example` has placeholders only.
- `admin_api_key` and `llm_api_key` are `SecretStr` values.
- Health, error, and release-check payloads omit DSNs, passwords, and keys.
- Logs redact bearer tokens, `VERAPOLITICA_*KEY` assignments, and PostgreSQL
  URLs. Authorization headers are not logged.
- AI audit rows must not store provider API secrets.

## HTTPS

TLS is terminated by the provider or reverse proxy. VeraPolitica does not
manage certificates in Python. Traffic is HTTP inside the private network and
HTTPS externally. Redirect HTTP→HTTPS at the proxy.

Forwarded headers are ignored unless `VERAPOLITICA_FORWARDED_ALLOW_IPS` is set
to the proxy. Do not set `*` unless you understand host/scheme spoofing.

## CORS and hosts

Production CORS is an explicit allowlist (`VERAPOLITICA_CORS_ORIGINS`). `*` is
rejected. Credentials are not enabled, so there is no credentialed wildcard
CORS.

`VERAPOLITICA_TRUSTED_HOSTS` is required in production and rejects `*`.

## Input validation

Public search, pagination, and admin bodies use bounded Pydantic/Query limits.
Unexpected exceptions return a generic 500 plus `request_id` in production. The
client body does not include stack traces, SQL, filesystem paths, or secrets.

## Publication gates

Public politician, proposal, referendum, glossary, and voting-guide payloads
expose only reviewed, published records. AI extraction can create drafts only.
AI never auto-publishes. Human review remains the publication boundary.

## Raw-source provenance

Collectors store immutable raw artifacts under `VERAPOLITICA_RAW_STORAGE_PATH`.
Production must use a persistent volume. Losing that volume loses the ability
to prove what the official source returned.

## HTTP headers

Responses set conservative `X-Content-Type-Options`, `Referrer-Policy`,
`X-Frame-Options`, `Content-Security-Policy`, and `Permissions-Policy` values
compatible with the current static citizen UI (module scripts plus official
HTTPS portrait URLs). They reduce some browser risk classes; they are not a
security guarantee.

## Rate limiting

Preferred control is provider/reverse-proxy rate limiting. There is no Redis
limiter. Search length and pagination caps bound application work. Admin
routes remain key-protected.

## Data privacy

V1 uses public institutional data. There are no tracking cookies, analytics
pixels, or citizen profiling/personalization features. The internal civic
reminder foundation is opaque operator state, not a public notification
product.

## Known limitations

- Shared admin API key, not per-editor accounts or SSO.
- Process-local safeguards are not distributed protection.
- CSP allows `'unsafe-inline'` styles for the current static CSS usage.
- Demo UI and OpenAPI can be re-enabled with configuration; production
  defaults are off, but operators must keep them off.
- Stale-job recovery marks crashed runs failed; it does not prove the
  underlying ingestion was safe.
- No claim is made about GDPR certification, ISO, or SOC 2.
