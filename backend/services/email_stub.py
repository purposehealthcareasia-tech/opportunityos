"""INTERNAL STUB — email delivery.

Interface preserved for later swap. In Phase 1 this only logs.
"""
import logging

log = logging.getLogger("oppos.email_stub")


async def send_email(to: str, subject: str, body: str, template: str | None = None) -> dict:
    log.info("STUB email → to=%s subject=%r template=%s", to, subject, template)
    return {"delivered": False, "stub": True, "to": to, "subject": subject}
