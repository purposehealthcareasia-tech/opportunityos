"""P0 Truth Audit (g) — robots.txt + sitemap.xml + /privacy.html served."""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"


def test_robots_txt_exists_and_mentions_fynd_and_sitemap():
    p = PUBLIC / "robots.txt"
    assert p.exists(), "frontend/public/robots.txt must exist"
    text = p.read_text(encoding="utf-8")
    assert "fynd" in text.lower(), "robots.txt must identify the site as Fynd"
    assert "Sitemap:" in text, "robots.txt must advertise a Sitemap URL"
    assert "Disallow: /api/" in text, "robots.txt must Disallow the API surface"
    assert "Disallow: /admin" in text, "robots.txt must Disallow admin routes"
    assert "Allow: /standards" in text, "robots.txt must allow the /standards public page"


def test_sitemap_xml_is_valid_xml_and_includes_public_routes():
    p = PUBLIC / "sitemap.xml"
    assert p.exists(), "frontend/public/sitemap.xml must exist"
    text = p.read_text(encoding="utf-8")
    # Parse — must be valid XML. ElementTree raises on malformed input.
    root = ET.fromstring(text)
    assert root.tag.endswith("urlset"), "sitemap root must be <urlset>"
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [u.text for u in root.findall("s:url/s:loc", ns)]
    assert locs, "sitemap must contain at least one <url><loc>"
    # Required public routes:
    required = {
        "https://fynd.llc/",
        "https://fynd.llc/standards",
        "https://fynd.llc/privacy.html",
        "https://fynd.llc/about",
        "https://fynd.llc/employers",
    }
    missing = required - set(locs)
    assert not missing, f"sitemap missing required public URLs: {sorted(missing)}"


def test_privacy_html_still_exists_and_is_versioned():
    p = PUBLIC / "privacy.html"
    assert p.exists(), "frontend/public/privacy.html must exist"
    text = p.read_text(encoding="utf-8")
    assert "Version <code>1.0</code>" in text or "Version 1.0" in text, (
        "privacy.html must carry the explicit policy version string"
    )
    assert "Fynd" in text
    assert "opportunityos" not in text.lower(), (
        "privacy.html must not carry legacy OpportunityOS branding"
    )
