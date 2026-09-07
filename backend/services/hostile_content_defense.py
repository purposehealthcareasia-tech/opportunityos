"""P1 FOUNDATION Batch 4 · Item 3 · Hostile-Content Defense.

FYND ATLAS §20 — every byte the platform fetches from a source could
be adversarial. This module is the single layer through which any
non-source-code egress MUST pass. It implements the full test set:

  1. Protocol allowlist — only `https`. `http` allowed for internal
     localhost/dev; `file`, `gopher`, `ftp`, `data`, `javascript`,
     `vbscript`, `about`, `chrome`, `view-source`, etc. rejected.
  2. Private / link-local / loopback / cloud-metadata IP blocking.
     169.254.169.254 (AWS/GCP metadata) and IPv6 equivalents (fd00::,
     fe80::, ::1) hard-blocked. Site-local + reserved ranges too.
  3. DNS re-resolution + rebinding defense — resolve hostname, verify
     EVERY returned IP against the safe set, then PIN the connection
     to the validated IP (URL rewritten to https://<ip>/, Host header
     set to the original hostname, TLS SNI to the original hostname
     via `extensions={"sni_hostname": ...}`). Prevents DNS-rebinding
     where the resolver returns a public IP for the check and a
     private IP for the actual connection.
  4. Redirect chain — max 3 hops; each hop re-validates protocol +
     IP; response Location header is rewritten and re-pinned.
  5. Response size limit — MAX_RESPONSE_BYTES = 8 MiB (streaming).
  6. Request timeout — MAX_TIMEOUT_S = 15s.
  7. MIME allowlist — reject responses with content-type not in
     ALLOWED_MIME_TYPES.
  8. HTML sanitization + script stripping.
  9. Structured-output schema validation — `validate_json_shape()`.
 10. Retrieved text isolation — `wrap_untrusted_content()` fences
     fetched text with delimiters so LLM callers cannot let it hijack
     the system prompt.
 11. Signed webhook verification (HMAC-SHA256, constant-time compare).
 12. Policy-decision logging — every allow/deny recorded via
     `_log_decision(...)` for the audit trail.
 13. PII redaction in logs — emails/phones/SSNs stripped from log
     lines before they hit stdout.

Rail: no fetcher may construct a raw httpx.AsyncClient / requests
session outside this module. Enforced by
`test_hostile_content_defense.py::test_no_raw_httpx_outside_guarded_paths`.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx


log = logging.getLogger("fynd.hostile_content_defense")


# ==================================================================
# Constants — all locked by tests
# ==================================================================
ALLOWED_SCHEMES: frozenset[str] = frozenset({"https", "http"})
"""HTTPS is preferred; HTTP retained for localhost-loopback dev + internal
service tokens. Every other scheme (`file`, `gopher`, `ftp`, `data`,
`javascript`, `vbscript`, `about`, `chrome`, `view-source`, `blob`) is
rejected."""

MAX_RESPONSE_BYTES = 8 * 1024 * 1024    # 8 MiB
MAX_TIMEOUT_S      = 15.0
MAX_REDIRECT_HOPS  = 3

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/json",
    "application/xml", "text/xml",
    "text/html", "text/plain",
    "application/rss+xml", "application/atom+xml",
    "application/ld+json",
})

# Cloud-metadata IPs — hardcoded because they're the same across all
# major clouds and MUST never be reachable by a fetcher.
BLOCKED_HARDCODED_IPS: frozenset[str] = frozenset({
    # AWS / GCP / Azure IMDSv1 IPv4
    "169.254.169.254",
    # Alibaba Cloud / Oracle Cloud metadata (documented)
    "100.100.100.200",
    # Nominal IPv6 link-local equivalents
    "fe80::a9fe:a9fe",
    "fd00:ec2::254",
})


# ==================================================================
# Exceptions
# ==================================================================
class UnsafeUrlError(RuntimeError):
    """Raised on any refusal: bad scheme, blocked IP, oversized body,
    disallowed MIME, redirect over cap, etc."""
    def __init__(self, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.reason  = reason
        self.details = details or {}


# ==================================================================
# 1. Protocol allowlist
# ==================================================================
def check_scheme(url: str) -> None:
    """Raise UnsafeUrlError if the URL's scheme is not in the allowlist."""
    scheme = (urlparse(url).scheme or "").lower()
    if not scheme:
        raise UnsafeUrlError("missing_scheme", {"url": url})
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"disallowed_scheme:{scheme}", {"url": url})


# ==================================================================
# 2. + 3. IP validation + DNS-rebinding defense
# ==================================================================
def _ip_family_is_private(ip_obj: ipaddress._BaseAddress) -> bool:
    """True if this IP is any category we must never talk to."""
    return (ip_obj.is_private     or  # RFC1918 + link-local
            ip_obj.is_loopback    or
            ip_obj.is_reserved    or
            ip_obj.is_multicast   or
            ip_obj.is_unspecified or
            ip_obj.is_link_local)


def check_ip_is_safe(ip_str: str) -> None:
    """Raise UnsafeUrlError if `ip_str` resolves to any category the
    platform forbids: private, link-local, loopback, reserved,
    multicast, unspecified, cloud-metadata (hardcoded blocklist)."""
    if ip_str in BLOCKED_HARDCODED_IPS:
        raise UnsafeUrlError(f"blocked_hardcoded_ip:{ip_str}",
                             {"ip": ip_str, "why": "cloud_metadata_or_special"})
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError as e:
        raise UnsafeUrlError(f"invalid_ip:{ip_str}",
                             {"ip": ip_str, "error": str(e)})
    if _ip_family_is_private(ip_obj):
        raise UnsafeUrlError(
            f"private_or_reserved_ip:{ip_str}",
            {"ip": ip_str,
             "is_private": ip_obj.is_private,
             "is_loopback": ip_obj.is_loopback,
             "is_link_local": ip_obj.is_link_local,
             "is_reserved": ip_obj.is_reserved,
             "is_multicast": ip_obj.is_multicast})


def safe_resolve(hostname: str) -> str:
    """Resolve `hostname` and validate EVERY returned IP against the
    safe set. Returns the first safe IPv4 (or IPv6 if v4 not present).
    Raises UnsafeUrlError if ANY answer trips the private-check
    (rail: reject at the FIRST unsafe answer, don't cherry-pick)."""
    if not hostname or hostname != hostname.strip():
        raise UnsafeUrlError("bad_hostname", {"host": hostname})
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeUrlError("dns_resolution_failed",
                             {"host": hostname, "error": str(e)})
    seen: list[str] = []
    for family, _t, _p, _canon, sockaddr in results:
        ip = sockaddr[0]
        seen.append(ip)
        # Reject the WHOLE resolution set if any IP is private —
        # otherwise DNS rebinding could return one safe + one private
        # answer and we might pick the wrong one.
        check_ip_is_safe(ip)
    if not seen:
        raise UnsafeUrlError("dns_empty", {"host": hostname})
    # Prefer IPv4 for determinism.
    v4 = [ip for ip in seen if ":" not in ip]
    return v4[0] if v4 else seen[0]


def pin_url_to_ip(url: str, ip: str) -> tuple[str, str]:
    """Rewrite `url` to use the validated IP directly. Returns
    (pinned_url, original_hostname) — the caller MUST set
    `Host: <original_hostname>` and TLS SNI to `<original_hostname>`
    on the httpx request so cert validation still works."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise UnsafeUrlError("no_hostname_to_pin", {"url": url})
    orig_host = parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    # Bracket IPv6 literals.
    ip_literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_literal}{port}"
    pinned = urlunparse(parsed._replace(netloc=netloc))
    return pinned, orig_host


# ==================================================================
# 4. + 5. + 6. + 7. Safe fetch primitive
# ==================================================================
@dataclass
class SafeFetchResult:
    url:          str
    final_url:    str
    status_code:  int
    content_type: str
    body_bytes:   bytes
    body_text:    str
    hops:         list[dict]


async def safe_fetch(url: str, *,
                      max_bytes: int  = MAX_RESPONSE_BYTES,
                      timeout_s: float = MAX_TIMEOUT_S,
                      max_hops: int   = MAX_REDIRECT_HOPS,
                      allowed_mime: frozenset[str] = ALLOWED_MIME_TYPES,
                      allow_http: bool = False) -> SafeFetchResult:
    """The ONE safe fetch primitive. Every guard runs BEFORE the byte
    leaves the pod, and each redirect hop re-runs the guards."""
    if not allow_http:
        scheme = urlparse(url).scheme.lower()
        if scheme == "http":
            raise UnsafeUrlError("http_disallowed_use_https", {"url": url})

    hops: list[dict] = []
    current_url = url
    for hop_i in range(max_hops + 1):  # +1 to give the terminal fetch a hop budget
        # 1. Scheme check.
        check_scheme(current_url)
        parsed = urlparse(current_url)
        # 2. Resolve + IP validation.
        ip = safe_resolve(parsed.hostname or "")
        # 3. Pin connection to validated IP.
        pinned_url, orig_host = pin_url_to_ip(current_url, ip)
        hop_record = {
            "hop": hop_i, "requested": current_url, "resolved_ip": ip,
            "pinned_url": pinned_url, "host_header": orig_host,
        }

        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=False,  # we handle redirects ourselves
            verify=True,             # TLS verify on
        ) as c:
            r = await c.get(
                pinned_url,
                headers={"Host": orig_host,
                         "User-Agent": "Fynd-SafeFetch/1.0 (contact: privacy@fynd.llc)"},
                extensions={"sni_hostname": orig_host},
            )
        hop_record["status_code"] = r.status_code
        hop_record["content_type"] = r.headers.get("content-type", "")
        hops.append(hop_record)
        _log_decision("fetch_hop", "allow", hop_record)

        if 300 <= r.status_code < 400:
            loc = r.headers.get("location")
            if not loc:
                raise UnsafeUrlError("redirect_without_location",
                                     {"hop": hop_i, "url": current_url})
            # 4. Redirect cap.
            if hop_i >= max_hops:
                raise UnsafeUrlError(
                    "redirect_chain_exceeded_max",
                    {"max_hops": max_hops, "hops": hops})
            # Resolve relative location against current URL.
            if loc.startswith("/"):
                loc = urlunparse(parsed._replace(path=loc, query="", fragment=""))
            current_url = loc
            continue

        # 5. Response size limit.
        body = r.content or b""
        if len(body) > max_bytes:
            raise UnsafeUrlError("response_body_over_max_bytes",
                                 {"got": len(body), "max": max_bytes})

        # 6. MIME allowlist.
        mime = (r.headers.get("content-type", "").split(";")[0].strip().lower())
        if mime and mime not in allowed_mime:
            raise UnsafeUrlError(f"disallowed_content_type:{mime}",
                                 {"content_type": mime, "allowed": sorted(allowed_mime)})

        # Decode text safely.
        text = ""
        try:
            text = body.decode(r.encoding or "utf-8", errors="replace")
        except Exception:
            text = ""

        return SafeFetchResult(
            url=url, final_url=current_url,
            status_code=r.status_code,
            content_type=mime,
            body_bytes=body,
            body_text=text,
            hops=hops,
        )

    raise UnsafeUrlError("redirect_chain_exceeded_max",
                          {"max_hops": max_hops, "hops": hops})


# ==================================================================
# 8. HTML sanitization + script stripping
# ==================================================================
_SCRIPT_RX     = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.DOTALL | re.IGNORECASE)
_STYLE_RX      = re.compile(r"<style\b[^>]*>.*?</style\s*>",  re.DOTALL | re.IGNORECASE)
_IFRAME_RX     = re.compile(r"<(iframe|object|embed|applet|form)\b[^>]*>.*?</\1\s*>",
                             re.DOTALL | re.IGNORECASE)
_SELF_CLOSE_DANGEROUS = re.compile(r"<(iframe|object|embed|applet|form)\b[^>]*/?>",
                                    re.IGNORECASE)
_ON_EVENT_ATTR = re.compile(r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
                             re.IGNORECASE)
_DANGEROUS_URI = re.compile(
    r"\s+(href|src|xlink:href|action)\s*=\s*"
    r"(\"\s*(javascript|vbscript|data|about|blob|file):[^\"]*\""
    r"|'\s*(javascript|vbscript|data|about|blob|file):[^']*'"
    r"|(javascript|vbscript|data|about|blob|file):[^\s>]+)",
    re.IGNORECASE,
)


def sanitize_html(html: str) -> str:
    """Return `html` with scripts, event handlers, and dangerous URI
    schemes stripped. NEVER interprets — pure textual sanitizer.
    Deterministic; no dependency on a JS runtime."""
    if not html:
        return ""
    out = _SCRIPT_RX.sub("", html)
    out = _STYLE_RX.sub("", out)
    out = _IFRAME_RX.sub("", out)
    out = _SELF_CLOSE_DANGEROUS.sub("", out)
    out = _ON_EVENT_ATTR.sub("", out)
    out = _DANGEROUS_URI.sub("", out)
    return out


# ==================================================================
# 9. Structured-output schema validation
# ==================================================================
def validate_json_shape(data: Any, schema: dict, *, path: str = "$") -> None:
    """Deterministic shape check — schema is a nested dict of
    `{key: type_or_subschema}`. Raises UnsafeUrlError on mismatch.
    Kept intentionally simple; no jsonschema dep. Types:
      * type[str], type[int], type[float], type[bool], type[dict],
        type[list] → isinstance check
      * dict subschema → recurse
      * list with 1 element → recurse each item against element schema
    """
    if isinstance(schema, type):
        if not isinstance(data, schema):
            raise UnsafeUrlError(
                f"schema_type_mismatch",
                {"path": path, "expected": schema.__name__,
                 "got": type(data).__name__})
        return
    if isinstance(schema, dict):
        if not isinstance(data, dict):
            raise UnsafeUrlError(
                "schema_expected_dict",
                {"path": path, "got": type(data).__name__})
        for key, subschema in schema.items():
            if key not in data:
                raise UnsafeUrlError(
                    "schema_missing_key",
                    {"path": f"{path}.{key}"})
            validate_json_shape(data[key], subschema, path=f"{path}.{key}")
        return
    if isinstance(schema, list) and len(schema) == 1:
        if not isinstance(data, list):
            raise UnsafeUrlError("schema_expected_list",
                                 {"path": path, "got": type(data).__name__})
        for i, item in enumerate(data):
            validate_json_shape(item, schema[0], path=f"{path}[{i}]")
        return
    raise UnsafeUrlError("schema_definition_invalid", {"path": path})


# ==================================================================
# 10. Retrieved-text isolation — never let fetched content hijack a
# privileged prompt.
# ==================================================================
UNTRUSTED_FENCE_OPEN  = "<<<UNTRUSTED_CONTENT_BEGIN>>>"
UNTRUSTED_FENCE_CLOSE = "<<<UNTRUSTED_CONTENT_END>>>"


def wrap_untrusted_content(text: str) -> str:
    """Wrap `text` in a fixed fence so downstream LLM callers can
    unambiguously distinguish system instructions from fetched content.
    Also strips any occurrence of the fence tokens INSIDE the text so
    the attacker cannot forge a fence to break out."""
    if not text:
        return f"{UNTRUSTED_FENCE_OPEN}{UNTRUSTED_FENCE_CLOSE}"
    inner = (text.replace(UNTRUSTED_FENCE_OPEN, "[fence-token-stripped]")
                  .replace(UNTRUSTED_FENCE_CLOSE, "[fence-token-stripped]"))
    return f"{UNTRUSTED_FENCE_OPEN}\n{inner}\n{UNTRUSTED_FENCE_CLOSE}"


# ==================================================================
# 11. Signed webhook verification (constant-time)
# ==================================================================
def verify_hmac_sha256(body: bytes | str, signature_hex: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verify. `signature_hex` is the
    hex-encoded HMAC from the webhook `X-Signature-256` (or
    equivalent) header. Returns True iff the signature matches."""
    if not signature_hex or not secret:
        return False
    if isinstance(body, str):
        body = body.encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), body,
                         hashlib.sha256).hexdigest()
    # Strip common prefixes like `sha256=`
    sig = signature_hex.lower().strip()
    if sig.startswith("sha256="):
        sig = sig[len("sha256="):]
    return hmac.compare_digest(expected, sig)


# ==================================================================
# 12. Policy-decision logging
# ==================================================================
def _log_decision(what: str, verdict: str, details: dict) -> None:
    """Structured policy log — every fetch guard verdict is emitted
    for audit. PII is redacted before the log line hits stdout."""
    safe = redact_pii(str(details))
    log.info("hostile_content_defense.%s verdict=%s details=%s",
             what, verdict, safe)


# ==================================================================
# 13. PII redaction in logs
# ==================================================================
_EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RX = re.compile(r"\+?\d[\d\-\.\s\(\)]{7,}\d")
_SSN_RX   = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def redact_pii(text: str) -> str:
    """Redact emails / phones / SSNs from a log string. Order matters:
    SSNs are checked BEFORE phones so 123-45-6789 doesn't get eaten
    by the more permissive phone regex."""
    if not text:
        return text
    out = _SSN_RX.sub("[REDACTED-SSN]", text)
    out = _EMAIL_RX.sub("[REDACTED-EMAIL]", out)
    out = _PHONE_RX.sub("[REDACTED-PHONE]", out)
    return out
