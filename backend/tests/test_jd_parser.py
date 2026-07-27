"""JD parser — conservative degree + years_min extraction.

Rails:
  * Only content inside a REQUIRED-labeled section counts.
  * "Preferred" / "Nice-to-have" / "Bonus" content NEVER lifts a requirement.
  * Curly quotes, en/em dashes, and HTML tags must all be normalized.
  * When the JD is silent or ambiguous, return None.
"""
from services import jd_parser as jp


def test_bachelor_required_in_min_qualifications():
    jd = ("<p><strong>Minimum Qualifications:</strong></p>"
          "<ul><li>Bachelor's degree in Supply Chain Management</li>"
          "<li>0-2 years of experience in procurement</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] == "BS"


def test_years_min_from_required_section():
    jd = ("<strong>Required Qualifications</strong>"
          "<ul><li>Bachelor's degree</li>"
          "<li>3-5 years of experience in influencer marketing</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] == "BS"
    assert out["years_min"] == 3


def test_phd_master_or_higher_picks_lower_bound():
    jd = ("<strong>Requirements:</strong>"
          "<ul><li>MS or PhD in Robotics, EE, or a related field</li>"
          "<li>Minimum 8 years of experience</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] == "MS"
    assert out["years_min"] == 8


def test_preferred_section_does_not_count():
    jd = ("<strong>Minimum Qualifications:</strong>"
          "<ul><li>High school diploma</li></ul>"
          "<strong>Preferred Qualifications:</strong>"
          "<ul><li>Master's degree in CS</li><li>PhD in AI a plus</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] == "HS"


def test_silent_jd_returns_none():
    jd = "We're a great team building amazing things."
    out = jp.parse_requirements(jd)
    assert out["degree_level"] is None
    assert out["years_min"] is None


def test_preferred_only_jd_returns_none():
    """If a degree is mentioned but ONLY in a preferred/nice-to-have section,
    the parser must NOT emit a required degree."""
    jd = ("<strong>Nice to have:</strong>"
          "<ul><li>Bachelor's degree in CS</li>"
          "<li>3+ years of relevant experience preferred</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] is None
    assert out["years_min"] is None


def test_curly_apostrophe_and_em_dash():
    """Real ATS payloads use \u2019 and \u2013 — parser must normalize."""
    jd = ("<strong>Minimum Qualifications:</strong>"
          "<ul><li>Bachelor\u2019s degree in Automotive Technology</li>"
          "<li>0\u20132 years of experience</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] == "BS"
    assert out["years_min"] == 0 or out["years_min"] is None  # 0 fails our floor, may become None


def test_associate_degree_recognized():
    jd = ("<strong>Requirements:</strong>"
          "<ul><li>Associate's degree in Business or equivalent</li>"
          "<li>2+ years of experience</li></ul>")
    out = jp.parse_requirements(jd)
    assert out["degree_level"] == "AS"
    assert out["years_min"] == 2


def test_years_min_caps_at_20():
    jd = "<strong>Requirements:</strong><ul><li>500 years of experience</li></ul>"
    out = jp.parse_requirements(jd)
    assert out["years_min"] is None
