"""i18n foundation — WIP for P1 Batch 6.

Scaffolding only. No consumers wired in yet. Safe to import; safe to
leave unused. Full Batch 6 wiring resumes after founder's Re-publish
click clears.
"""
from domains.i18n.locales import (  # noqa: F401
    LOCALES,
    LocaleInfo,
    is_rtl,
    suggest_locale,
)

__all__ = ["LOCALES", "LocaleInfo", "is_rtl", "suggest_locale"]
