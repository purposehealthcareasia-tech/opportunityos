"""Conservative JD parser (Phase 3 follow-up · 2026-07-27).

Given a job description text, extract `degree_level` and `years_min` requirements
CONSERVATIVELY. When the phrasing is ambiguous, "preferred", "a plus", "bonus",
"nice-to-have", or the JD text is silent — return None so the gate engine emits
NO note (per founder's rule: "when unparseable, emit no note; never guess").

Strategy — real-world ATS JDs use section headers, not full sentences. We:
  1. Strip HTML tags.
  2. Locate REQUIREMENT SECTION headers ("Minimum Qualifications", "Required
     Qualifications", "Requirements", "Basic Qualifications", "Must Have").
  3. Extract the ~1500 chars following each header up to the next section
     header or ~end of block.
  4. Detect degree / years inside those blocks only.
  5. If the block also contains preference markers ("preferred", "a plus",
     "bonus"), keep parsing but only trust items in the REQUIRED block
     itself, not the preferred block.

Public API:
    parse_requirements(jd_text: str) -> {"degree_level": str|None, "years_min": int|None}
"""
from __future__ import annotations

import re
from typing import Optional


_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Strip tags AND normalize whitespace & unicode punctuation for regex-safety."""
    if not text:
        return ""
    plain = _HTML_TAG.sub(" ", text)
    plain = plain.replace("&nbsp;", " ").replace("&amp;", "&")
    # Curly quotes → straight; en/em dash → hyphen
    plain = (plain.replace("\u2018", "'").replace("\u2019", "'")
                    .replace("\u201c", '"').replace("\u201d", '"')
                    .replace("\u2013", "-").replace("\u2014", "-"))
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain


# Requirement section header phrases. Matches at the START of a section
# (case-insensitive). Any header containing "Preferred" / "Nice-to-have" /
# "Bonus" is intentionally EXCLUDED from this list so we don't lift a "nice"
# credential into our required set.
_REQUIRED_HEADER = re.compile(
    r"(?:^|\.\s+|:\s+|-\s+|\|\s+|\*\s+)"
    r"(minimum\s+(?:qualifications?|requirements?)"
    r"|required\s+qualifications?"
    r"|basic\s+qualifications?"
    r"|core\s+qualifications?"
    r"|what\s+you(?:'ll)?\s+need"
    r"|what\s+we(?:'re)?\s+looking\s+for"
    r"|must[-\s]have(?:s)?"
    r"|requirements?\s*[:\-]"
    r"|qualifications?\s*[:\-])",
    re.IGNORECASE,
)

# Preferred-section headers — content in these blocks NEVER counts as required.
_PREFERRED_HEADER = re.compile(
    r"(preferred\s+qualifications?|nice[-\s]to[-\s]haves?|bonus\s+(?:points|qualifications?)"
    r"|plus(?:es)?\s*:|extras?\s*:|desirables?\s*:)",
    re.IGNORECASE,
)


def _required_blocks(text: str, block_len: int = 1500) -> list[str]:
    """Return the substrings of `text` immediately following required-section
    headers, truncated at the next header (required OR preferred) or block_len.
    """
    text = _strip_html(text)
    if not text:
        return []
    # Locate all header positions with a kind marker (required or preferred).
    events: list[tuple[int, str]] = []
    for m in _REQUIRED_HEADER.finditer(text):
        events.append((m.end(), "required"))
    for m in _PREFERRED_HEADER.finditer(text):
        events.append((m.start(), "preferred"))
    events.sort()
    blocks: list[str] = []
    for i, (pos, kind) in enumerate(events):
        if kind != "required":
            continue
        # end = next event position (whatever kind) OR pos + block_len
        end = pos + block_len
        for pos2, kind2 in events[i + 1:]:
            if pos2 > pos:
                end = min(end, pos2)
                break
        blocks.append(text[pos:end])
    return blocks


# Ordered ascending so a JD asking "MS or PhD" reports the LOWER bound (MS).
_DEGREE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhigh\s+school\s+diploma\b|\bGED\b", re.IGNORECASE), "HS"),
    (re.compile(r"\b(?:associate'?s?|A\.A\.|A\.S\.|associate\s+degree)\b", re.IGNORECASE), "AS"),
    (re.compile(
        r"\bbachelor'?s?\b|\bbachelor'?s?\s+degree\b|\bBS\b(?:/|\s+or\s+)?|\bBA\b(?:/|\s+or\s+)?|"
        r"\bB\.S\.\b|\bB\.A\.\b|\b4[-\s]?year\s+degree\b|\bundergraduate\s+degree\b",
        re.IGNORECASE), "BS"),
    (re.compile(
        r"\bmaster'?s?\b|\bmaster'?s?\s+degree\b|\bMS\b(?:/|\s+or\s+)?|\bMA\b(?:/|\s+or\s+)?|"
        r"\bM\.S\.\b|\bM\.A\.\b|\bM\.Eng\b|\bMBA\b",
        re.IGNORECASE), "MS"),
    (re.compile(r"\bPh\.?D\b|\bdoctorate\b|\bdoctoral\s+degree\b|\bD\.Phil\b",
                 re.IGNORECASE), "PHD"),
]

_DEGREE_ORDER = ["HS", "AS", "BS", "MS", "PHD"]


# Years-of-experience — capture the LOWER bound only.
# Handles: "5+ years", "at least 3 years", "minimum 5 years", "5-7 years",
# "0-2 years of experience", "3+ years of relevant experience".
_YEARS_MIN = re.compile(
    r"(?:at\s+least\s+|minimum\s+(?:of\s+)?|min\.?\s+(?:of\s+)?|)?"
    r"(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*(?:years|yrs?\.?)"
    r"\s*(?:\+)?\s*(?:of|in)?\s*(?:relevant|professional|hands[-\s]on)?\s*"
    r"(?:experience|exp\.?|work)",
    re.IGNORECASE,
)


def parse_degree(jd_text: str) -> Optional[str]:
    """Return the LOWEST degree level the JD explicitly REQUIRES, or None.

    Only content inside a REQUIRED-header section counts. "Preferred" / "Nice-
    to-have" blocks are excluded.
    """
    blocks = _required_blocks(jd_text)
    if not blocks:
        return None
    best_idx: Optional[int] = None
    for block in blocks:
        for pat, level in _DEGREE_PATTERNS:
            if pat.search(block):
                idx = _DEGREE_ORDER.index(level)
                if best_idx is None or idx < best_idx:
                    best_idx = idx
                break
    return _DEGREE_ORDER[best_idx] if best_idx is not None else None


def parse_years_min(jd_text: str) -> Optional[int]:
    """Return an integer years-of-experience floor from a REQUIRED section.

    Values > 20 are dropped as noise. Multiple matches → the SMALLEST floor
    is used (least restrictive).
    """
    blocks = _required_blocks(jd_text)
    if not blocks:
        return None
    best: Optional[int] = None
    for block in blocks:
        for m in _YEARS_MIN.finditer(block):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 20:
                if best is None or n < best:
                    best = n
    return best


def parse_requirements(jd_text: str) -> dict:
    """Parse degree + years_min from JD text (conservative). Returns
    ``{"degree_level": str|None, "years_min": int|None}``.

    Never fabricates a value — returns None when the JD doesn't clearly
    state the requirement in a REQUIRED-labeled section.
    """
    return {
        "degree_level": parse_degree(jd_text or ""),
        "years_min": parse_years_min(jd_text or ""),
    }
