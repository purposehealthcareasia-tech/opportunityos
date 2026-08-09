"""Phase 5a · Passport Share Link (resume-free apply).

Consent-scoped, HMAC-signed, revocable public link that lets an employer
open a filtered read-only Passport view — WITHOUT a résumé attachment.

Rails:
  * Requires `share_passport` consent (see core/policy.py).
  * TTL-bounded (min 1h, max 30 days).
  * Immediately revocable — a revoked link 410s on the next view.
  * Every view logged to `share_view_receipts` (view_id, share_id,
    ip_prefix (/24 for IPv4, redacted-network for IPv6), ua_hash,
    ts) — auditable.
  * Filtered payload per scope. Sealed claims, ITAR flags, private
    preferences, salary/income never appear in ANY scope.
  * Public GET path has NO CSRF (public read); other paths use the
    site's normal auth+CSRF pipeline.
"""
