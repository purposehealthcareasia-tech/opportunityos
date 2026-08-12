# Email-Route Executor — Configuration & Production Cutover

**Status in preview: DRY-RUN by default. Local sink writes to `email_outbox`. Live path is WIRED (2026-08-12) but activation requires setting env + re-publish.**

## Environment (set in the Emergent deploy platform; changes require RE-PUBLISH)

| Variable | Values | Purpose |
| --- | --- | --- |
| `EMAIL_ROUTE_DRY_RUN` | `true` \| `false` | **Master flip.** Defaults to `true`. Only the exact lowercase string `"false"` flips to live — near-miss values (`"False"`, `"0"`, `"no"`, etc.) all stay dry-run. Read at **call-time** via `os.environ.get` inside `domains/email_route/__init__.py::_dispatch_mode()` — but the deploy platform still needs a re-publish to inject a new value into the worker. |
| `EMAIL_ROUTE_PROVIDER` | `resend` \| `sendgrid` | Selects the transport in live mode. Default `resend`. Unknown values fall back to `resend` with a warning log. |
| `RESEND_API_KEY` | `re_…` | Resend API key. Read at **import-time** by `integrations/email/resend_provider.py::configure()` → **RE-PUBLISH required to change**. |
| `RESEND_FROM_EMAIL` | RFC-5321 mailbox | The `From:` address. Must be on a Resend-verified domain with valid SPF + DKIM (see below). No code-side domain validation — trust is entirely on Resend's DNS-verification side. |
| `RESEND_WEBHOOK_SECRET` | Svix signing secret | Optional. Only needed if consuming inbound bounce/delivery events via `/api/webhooks/email`. |
| `SENDGRID_API_KEY` | `SG.…` | SendGrid API key (alternative to Resend). Same import-time / re-publish semantics. |
| `SENDGRID_FROM_EMAIL` | RFC-5321 mailbox | SendGrid `From:` address. |
| `SENDGRID_WEBHOOK_VERIFICATION_KEY` | ECDSA public PEM | Optional; for inbound event webhooks. |

## First-live-send safety path — `POST /api/v1/email-route/self-test`

Owner/admin/support only (`PRIVATE_AUTOPILOT_OWNER_EMAILS` CSV gate). Destination MUST match the caller's authenticated email exactly. Sends ONE canned message tagged `kind="email_self_test"`; never touches any real application. Use this to verify the Resend path lands in your own inbox before real users hit the live route.

Curl example (after login, with your session cookie + CSRF token from `/api/v1/auth/me`):
```bash
curl -X POST "$PROD_URL/api/v1/email-route/self-test" \
     -H 'Content-Type: application/json' \
     -H "Authorization: Bearer $TOKEN" \
     -d "{\"destination\": \"$YOUR_EMAIL\"}"
```

Success response shape:
```json
{"id": "...", "state": "sent", "sent_to_smtp": true, "provider": "resend",
 "provider_message_id": "re_...", "dispatch_mode": "live",
 "kind": "email_self_test", "live_send_error": null}
```

If `state=="dry_run"` and `live_send_error!=null`, the live path failed **safely** — no email was sent, no application state changed, the row records honestly why.

## Parked-dry-run invariant

Outbox rows written under dry-run stay dry-run forever. There is NO code path (scheduler, cron, admin endpoint, sweep) that will replay them on flag flip. Pinned structurally by `tests/test_email_route_live_flip.py::test_parked_dry_run_never_replayed_by_code_grep`. If a new email_outbox writer that mutates existing rows is added, that test fails LOUDLY.

## SPF + DKIM setup (mandatory before turning the real transport on)

The operator's From-domain **must** publish valid SPF and DKIM records that authorize the chosen provider. Without these, mail lands in spam or is silently dropped by receivers.

### 1. SPF (Sender Policy Framework)

Publish a `TXT` record on the From-domain apex (or the mail sub-domain):

- **Resend:** `v=spf1 include:_spf.resend.com ~all`
- **SendGrid:** `v=spf1 include:sendgrid.net ~all`
- **Self-hosted SMTP (AWS SES example):** `v=spf1 include:amazonses.com ~all`

Only ONE SPF record per domain — merge if you already have another sender.

### 2. DKIM (DomainKeys Identified Mail)

Both Resend and SendGrid issue CNAME records that you publish on your DNS. Example (Resend):

- `resend._domainkey.YOURDOMAIN.com  CNAME  resend._domainkey.resend.com`

For SendGrid, use its "Domain Authentication" wizard — it emits 3× CNAME records (`s1._domainkey…`, `s2._domainkey…`, and a link CNAME).

For self-hosted SMTP (SES, Postmark, self-op OpenDKIM), you generate the private key server-side and publish the corresponding public-key `TXT` record.

### 3. Optional but recommended: DMARC

`_dmarc.YOURDOMAIN.com  TXT  "v=DMARC1; p=none; rua=mailto:postmaster@yourdomain.com"`

Start with `p=none` to observe alignment, then move to `p=quarantine` or `p=reject` once SPF + DKIM are landing consistently.

## Cutover checklist (founder-only)

1. In Resend dashboard: verify the sending domain (SPF + DKIM CNAMEs green).
2. Send yourself a test via mail-tester.com from Resend's playground — score ≥ 9/10.
3. In the Emergent deploy platform, set: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `EMAIL_ROUTE_DRY_RUN=false`, optionally `EMAIL_ROUTE_PROVIDER=resend`.
4. **Publish (re-deploy)** — env changes only reach the worker via re-publish.
5. Log in as an owner-emails account, hit `POST /email-route/self-test` with `destination=<your own email>`. Verify inbox delivery.
6. Only after step 5 succeeds is the live route safe for real user application dispatches.

## Preview behavior (unchanged)

In preview, dispatches with the flag unset accumulate in `email_outbox` and produce `submission_receipts` with `route="email"`, `kind="email_dry_run"`, and `sent_to_smtp=false`. Idempotency, throttling, dedup, preflight, and consent are already tested against the local sink; the live path re-uses those same paths and simply flips the transport at the end.

