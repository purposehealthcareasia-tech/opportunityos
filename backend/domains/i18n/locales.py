"""FYND ATLAS i18n foundation.

Backend-side scaffolding for internationalization. Encodes the ATLAS
constraints:

  * Locale is SUGGESTED, not imposed. The frontend obtains permission
    before reading precise geolocation. This module never reads
    device-side signals; it only interprets what the caller passes.
  * Manual country/region override wins over any suggestion.
  * Currency, date, timezone, and salary-period localization are
    driven by a stable registry (this module).
  * RTL layout primitives are exposed via the `LocaleInfo` payload
    (`direction: "ltr"|"rtl"`).
  * Country claims: NO country is "supported" from a language
    selector alone. Country readiness lives in `country_packs.py`
    with an explicit readiness stage. The public API surfaces the
    stage honestly; a language-only selector cannot flip a country
    to `general_availability`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class LocaleInfo:
    """Everything the frontend needs to render for one locale.

    Fields:
      * `bcp47`           canonical tag: `<lang>-<REGION>`, e.g.
                          `en-US`, `es-MX`, `ar-AE`.
      * `language`        ISO-639-1 code.
      * `region`          ISO-3166-1 alpha-2 code (or None for
                          language-only fallbacks like `en`).
      * `direction`       `"ltr"` or `"rtl"`.
      * `currency`        ISO-4217 code for the region's primary
                          currency, when applicable. None otherwise.
      * `date_format`     Unicode LDML pattern.
      * `time_format`     LDML pattern (12h or 24h).
      * `timezone`        IANA name, best-guess for the region. The
                          frontend may override.
      * `salary_period`   one of `"annual"`, `"monthly"`, `"hourly"`.
                          Convention differs per region.
    """
    bcp47: str
    language: str
    region: str | None
    direction: str
    currency: str | None
    date_format: str
    time_format: str
    timezone: str
    salary_period: str


# --------------------------------------------------------------------
# Locale registry. Deliberately conservative — one canonical locale
# per region we render. Country packs (see `country_packs.py`) gate
# whether a candidate can actually TRANSACT in that region; this
# registry only governs rendering.
# --------------------------------------------------------------------
LOCALES: Final[dict[str, LocaleInfo]] = {
    "en-US": LocaleInfo(
        bcp47="en-US", language="en", region="US", direction="ltr",
        currency="USD",
        date_format="MM/dd/yyyy", time_format="h:mm a",
        timezone="America/New_York", salary_period="annual",
    ),
    "en-GB": LocaleInfo(
        bcp47="en-GB", language="en", region="GB", direction="ltr",
        currency="GBP",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="Europe/London", salary_period="annual",
    ),
    "en-IN": LocaleInfo(
        bcp47="en-IN", language="en", region="IN", direction="ltr",
        currency="INR",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="Asia/Kolkata", salary_period="annual",
    ),
    "es-MX": LocaleInfo(
        bcp47="es-MX", language="es", region="MX", direction="ltr",
        currency="MXN",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="America/Mexico_City", salary_period="monthly",
    ),
    "es-ES": LocaleInfo(
        bcp47="es-ES", language="es", region="ES", direction="ltr",
        currency="EUR",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="Europe/Madrid", salary_period="annual",
    ),
    "fr-FR": LocaleInfo(
        bcp47="fr-FR", language="fr", region="FR", direction="ltr",
        currency="EUR",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="Europe/Paris", salary_period="annual",
    ),
    "de-DE": LocaleInfo(
        bcp47="de-DE", language="de", region="DE", direction="ltr",
        currency="EUR",
        date_format="dd.MM.yyyy", time_format="HH:mm",
        timezone="Europe/Berlin", salary_period="annual",
    ),
    "ja-JP": LocaleInfo(
        bcp47="ja-JP", language="ja", region="JP", direction="ltr",
        currency="JPY",
        date_format="yyyy/MM/dd", time_format="HH:mm",
        timezone="Asia/Tokyo", salary_period="annual",
    ),
    "ar-AE": LocaleInfo(
        bcp47="ar-AE", language="ar", region="AE", direction="rtl",
        currency="AED",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="Asia/Dubai", salary_period="monthly",
    ),
    "he-IL": LocaleInfo(
        bcp47="he-IL", language="he", region="IL", direction="rtl",
        currency="ILS",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="Asia/Jerusalem", salary_period="monthly",
    ),
    "pt-BR": LocaleInfo(
        bcp47="pt-BR", language="pt", region="BR", direction="ltr",
        currency="BRL",
        date_format="dd/MM/yyyy", time_format="HH:mm",
        timezone="America/Sao_Paulo", salary_period="monthly",
    ),
    "en": LocaleInfo(
        bcp47="en", language="en", region=None, direction="ltr",
        currency=None,
        date_format="yyyy-MM-dd", time_format="HH:mm",
        timezone="UTC", salary_period="annual",
    ),
}


def suggest_locale(
    *,
    accept_language_header: str | None = None,
    manual_override: str | None = None,
) -> LocaleInfo:
    """Suggest a locale. Rules:

      1. If `manual_override` is a known key, return it VERBATIM
         (candidate's choice wins over inference).
      2. If `Accept-Language` header exists, parse the first tag
         (BCP-47), then:
           a. exact match in `LOCALES` → return it.
           b. language-only fallback (e.g. `fr-CA` → `fr` if we don't
              carry `fr-CA` but the frontend knows how to render `fr`).
              We only fall back to a MATCHING registered locale; never
              fabricate one.
      3. Otherwise → `en` (language-only, region=None, currency=None).
    """
    if manual_override and manual_override in LOCALES:
        return LOCALES[manual_override]
    if accept_language_header:
        first_tag = accept_language_header.split(",")[0].strip()
        # Normalize case: `en-us` → `en-US`.
        if "-" in first_tag:
            lang, region = first_tag.split("-", 1)
            first_tag = f"{lang.lower()}-{region.upper()}"
        else:
            first_tag = first_tag.lower()
        if first_tag in LOCALES:
            return LOCALES[first_tag]
        lang = first_tag.split("-", 1)[0]
        if lang in LOCALES:
            return LOCALES[lang]
    return LOCALES["en"]


def is_rtl(locale_key: str) -> bool:
    info = LOCALES.get(locale_key)
    return bool(info and info.direction == "rtl")
