# Email-Route Executor — Configuration & Production Cutover

**Status in preview: DRY-RUN ONLY. Local sink writes to `email_outbox`, never to SMTP.**

## Environment (never set in preview; founder-only to enable in production)

| Variable | Values | Purpose |
| --- | --- | --- |
| `EMAIL_ROUTE_PROVIDER` | `resend` \| `sendgrid` \| `smtp` | Selects the transport. Preview leaves this unset so the router falls through to `local_sink`. |
| `EMAIL_ROUTE_FROM` | RFC 5321 mailbox | The `From:` address. **Must** be on a domain the operator controls end-to-end (see SPF + DKIM below). |
| `EMAIL_ROUTE_API_KEY` | provider API key | Resend → `re_…`; SendGrid → `SG.…`. For SMTP: `EMAIL_ROUTE_SMTP_HOST`, `EMAIL_ROUTE_SMTP_PORT`, `EMAIL_ROUTE_SMTP_USER`, `EMAIL_ROUTE_SMTP_PASS`. |
| `EMAIL_ROUTE_DRY_RUN` | `true` \| `false` | Defaults to `true`. Flipping to `false` is an explicit founder action. Never toggled at runtime. |

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

## Verifying before production cutover

```bash
# 1. Confirm SPF resolves and passes
dig +short TXT yourdomain.com | grep spf1

# 2. Confirm DKIM CNAME points to provider
dig +short CNAME resend._domainkey.yourdomain.com

# 3. Send a message to mail-tester.com and verify score >= 9/10
#    (they highlight SPF/DKIM/DMARC failures and header issues explicitly)
```

Only after all three pass may the operator flip `EMAIL_ROUTE_DRY_RUN=false` and set the provider credentials. **Under no circumstances** should preview or dev environments be pointed at a live provider.

## Preview behavior (unchanged)

In preview, dispatches accumulate in `email_outbox` and produce `submission_receipts` with `route="email"` and `sent_to_smtp=false`. Idempotency, throttling, and dedup are already tested against the local sink; wiring the real provider becomes purely a transport-layer swap once SPF + DKIM are green.
