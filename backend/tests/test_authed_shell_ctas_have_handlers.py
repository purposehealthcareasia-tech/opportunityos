"""FYND ATLAS §44 zero-tolerance CI rail — inert primary CTAs must FAIL.

Founder's directive (2026-08-13 hotfix): every primary CTA on the authed
shell (Finish Passport banner, Continue sprint, Upload résumé, etc.) must
have a working handler or route. An inert primary CTA — meaning a button
with `variant="primary"` / `variant="accent"` or a `liquid-primary`
capsule that carries NO `onClick`, NO `<Link to>`, and NO `href` — is a
release blocker; CI must fail on it, not ship.

Scope (light, deterministic — pure static AST scan):
- Discovers .jsx files under frontend/src/pages and frontend/src/components.
- Parses primary CTAs by regex + surrounding-node lookahead so we can
  attribute an actionable-attribute to each candidate CTA.
- Skips clearly-decorative usages (e.g., `variant="ghost"`, disabled
  buttons whose parent renders an accompanying "why disabled" text —
  those are outside this rail's scope).

This is a static rail: it does NOT boot React. It catches "primary CTA
with no click handler + no route", which was the exact
`Finish Passport — 2 min` bug class before the hotfix.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"

# Scan these dirs — pages define screen CTAs, components define shared
# CTAs like SmartCTA and DailyBudgetCapsule.
SCAN_DIRS = ["pages", "components"]

# A "primary CTA" in this codebase is one of:
#   * <Button variant="accent" …>                (design system primary)
#   * <Button variant="primary" …>               (legacy primary)
#   * <Link className="liquid-capsule liquid-primary …" to=…>
#   * bare <a className="liquid-capsule liquid-primary …" href=…>
#
# We accept any of these ACTIONABLE attributes on the element as
# evidence of NOT-inert:
#   onClick=  |  to=  |  href=  |  type="submit" (inside a <form>)
PRIMARY_BUTTON_RE = re.compile(
    r'<Button\b(?P<attrs>[^>]*?)variant=(?:"|\{[\'"])(?:accent|primary)(?:"|[\'"]\})(?P<rest>[^>]*)>',
    re.DOTALL,
)
LIQUID_PRIMARY_RE = re.compile(
    r'<(?P<tag>Link|a)\b(?P<attrs>[^>]*?liquid-primary[^>]*)>',
    re.DOTALL,
)

ACTIONABLE_ATTRS = ("onClick", "to=", "href=", 'type="submit"', "type={'submit'}")


def _is_actionable(attrs_blob: str) -> bool:
    return any(marker in attrs_blob for marker in ACTIONABLE_ATTRS)


def _scan_file(path: Path):
    """Yield ('kind', line_no, snippet) tuples for every inert primary
    CTA found in the file."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    inert = []

    def _line_at(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    for m in PRIMARY_BUTTON_RE.finditer(text):
        attrs_blob = (m.group("attrs") or "") + (m.group("rest") or "")
        if not _is_actionable(attrs_blob):
            # Also allow the button to be enclosed by a <form onSubmit={…}> —
            # look 200 chars back for <form onSubmit or a wrapping onClick.
            before = text[max(0, m.start() - 400): m.start()]
            if "onSubmit" not in before and "onClick" not in before:
                inert.append(("primary-button", _line_at(m.start()), m.group(0)))

    for m in LIQUID_PRIMARY_RE.finditer(text):
        attrs_blob = m.group("attrs") or ""
        if not _is_actionable(attrs_blob):
            inert.append(("liquid-primary-link", _line_at(m.start()), m.group(0)))

    return inert


@pytest.mark.skipif(not FRONTEND_ROOT.exists(), reason="frontend workspace not present in this build")
def test_no_inert_primary_ctas_on_authed_shell():
    """A primary <Button variant='accent|primary'>...</Button> or a
    <Link className='liquid-primary'> that carries NO actionable
    attribute (onClick, to, href, type='submit') is a release blocker.
    """
    offenders: list[tuple[str, str, int, str]] = []
    for sub in SCAN_DIRS:
        base = FRONTEND_ROOT / sub
        if not base.exists():
            continue
        for path in base.rglob("*.jsx"):
            for kind, line, snippet in _scan_file(path):
                offenders.append((str(path.relative_to(FRONTEND_ROOT)), kind, line,
                                    snippet.strip().replace("\n", " ")[:180]))

    if offenders:
        details = "\n".join(
            f"  - {p}:{ln}  ({kind})  →  {sn}"
            for p, kind, ln, sn in offenders
        )
        pytest.fail(
            "\nFYND ATLAS §44 CI rail: inert primary CTA(s) detected — "
            "every primary button / capsule on the authed shell must carry "
            "onClick / to / href / type='submit'.\n" + details
        )


def test_smart_cta_finish_passport_deep_links_to_add_identity():
    """The Finish Passport CTA must NOT navigate to a same-URL no-op.
    Deep-link contract (see components/SmartCTA.jsx): when passport is
    not activated, the CTA targets `/passport?action=add-identity` so
    landing on /passport observably opens the manual-add modal."""
    smart_cta = (FRONTEND_ROOT / "components" / "SmartCTA.jsx").read_text(encoding="utf-8")
    # The literal bug was `to: '/passport'` with no query — assert that
    # bare form does NOT exist in the primary branch.
    assert "to: '/passport'," not in smart_cta, (
        "SmartCTA.jsx: the Finish-Passport CTA still targets a bare "
        "'/passport' — same-URL clicks become no-ops. Use "
        "'/passport?action=add-identity' so the destination page opens "
        "the manual-add modal."
    )
    assert "/passport?action=add-identity" in smart_cta, (
        "SmartCTA.jsx: Finish Passport CTA lost its deep-link — "
        "the `?action=add-identity` param must be present so clicking "
        "the topbar CTA observably opens the manual-add modal even "
        "when the user is already on /passport."
    )


def test_passport_consumes_action_query_param():
    """/passport reads the `?action=` param on mount and opens the
    matching manual-claim modal — closing the loop for the Finish
    Passport deep-link."""
    passport = (FRONTEND_ROOT / "pages" / "Passport.jsx").read_text(encoding="utf-8")
    assert "useSearchParams" in passport, (
        "Passport.jsx: useSearchParams import missing — the page cannot "
        "consume the ?action= deep-link."
    )
    assert "'add-identity'" in passport
    assert "'add-education'" in passport
    assert "'add-employment'" in passport
    # It must also strip the param so refresh doesn't re-open the modal.
    assert "next.delete('action')" in passport or 'delete("action")' in passport, (
        "Passport.jsx: the ?action= param is not stripped after being "
        "consumed — a page refresh would re-open the modal."
    )
