"""Grounded generation VALIDATOR — deterministic, server-side, no LLM in the reject path.

GROUNDING LAW (R4): no AI-generated factual statement exists unless it references an
approved Career Passport claim ID. This module is the firewall — it does NOT suggest,
it REJECTS. Callers that want to soften the firewall have the wrong idea; there is no
softening.

R5: sealed / sensitive claim VALUES may never surface in generated lines unless the
application carries an explicit per-application approval for that scope.

Refusal is separately handled at prompt-construction time: if the user instruction asks
for facts not in approved claims, `refuse_instruction` returns a refusal reason naming
the missing claim. The validator itself does not use an LLM — that's the point.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Iterable


SENSITIVE_SEALED_TYPES = {"work_auth", "salary", "clearance"}


@dataclass
class LineRejection:
    text: str
    claim_ids: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "claim_ids": self.claim_ids, "reasons": self.reasons}


# ------------------------------------------------------------------ #
# Fact-extraction helpers — used to enforce "numbers/dates must appear
# in the referenced claims"
# ------------------------------------------------------------------ #

_NUMBER_RE = re.compile(
    r"""
    (?<![A-Za-z_\d])         # not preceded by a letter, underscore, OR digit
                              # (so '2018-2020' yields 2018 and 2020, not 2018 and -2020)
    -?\d+(?:[.,]\d+)*        # 120, 1,200, 3.14
    (?:\s?%|k|K|M)?          # optional unit suffix
    """,
    re.VERBOSE,
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_YEAR_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(19|20)\d{2}\b",
    re.IGNORECASE,
)


def _normalize_number(s: str) -> str:
    """Strip commas, %, k/K/M for match-in-source comparison."""
    s = s.strip().replace(",", "").replace(" ", "").rstrip("%")
    if s.endswith(("k", "K")):
        try:
            return str(int(float(s[:-1]) * 1000))
        except ValueError:
            return s
    if s.endswith("M"):
        try:
            return str(int(float(s[:-1]) * 1_000_000))
        except ValueError:
            return s
    return s


def _extract_numbers(text: str) -> set[str]:
    return {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(text)}


def _extract_years(text: str) -> set[str]:
    """Extract 4-digit years AND month-year phrases, normalized to just the year."""
    years: set[str] = set()
    years.update(m.group(0) for m in _YEAR_RE.finditer(text))
    for m in _MONTH_YEAR_RE.finditer(text):
        year = m.group(0).split()[-1]
        years.add(year)
    return years


def _flatten_claim_values_to_text(claim: dict) -> str:
    val = claim.get("value")
    if val is None:
        return ""
    if isinstance(val, (str, int, float)):
        return str(val)
    if isinstance(val, list):
        return " ".join(_flatten_claim_values_to_text({"value": x}) for x in val)
    if isinstance(val, dict):
        return " ".join(_flatten_claim_values_to_text({"value": v}) for v in val.values())
    return str(val)


def _sensitive_leak_tokens(claim: dict) -> set[str]:
    """Return the individual value tokens (>=3 chars) of a sealed claim that a generated
    line must NOT surface verbatim without a per-application approval. Splits nested
    dict/list values into leaves so `{"status": "ead_opt", "opt_end": "2027-12-31"}`
    yields `{"ead_opt", "2027-12-31"}` — the substring check on the whole flattened
    string would miss "ead_opt" appearing alone in a sentence.
    """
    val = claim.get("value")
    if val is None:
        return set()
    leaves: list[str] = []

    def _walk(v):
        if v is None:
            return
        if isinstance(v, (str, int, float)):
            leaves.append(str(v))
        elif isinstance(v, list):
            for x in v:
                _walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
    _walk(val)
    # Only tokens 3+ characters are considered leak candidates. This avoids flagging
    # trivial values like a single digit or a two-letter state code.
    return {t.strip() for t in leaves if isinstance(t, str) and len(t.strip()) >= 3}


def _numbers_in_claim(claim: dict) -> set[str]:
    return _extract_numbers(_flatten_claim_values_to_text(claim))


def _years_in_claim(claim: dict) -> set[str]:
    return _extract_years(_flatten_claim_values_to_text(claim))


# ------------------------------------------------------------------ #
# Main validator
# ------------------------------------------------------------------ #

@dataclass
class ValidatorResult:
    status: str                          # "passed" | "failed"
    passed_lines: list[dict]             # {text, claim_ids}
    rejected_lines: list[dict]           # rejection dicts
    stats: dict[str, int]                # counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed_lines": self.passed_lines,
            "rejected_lines": self.rejected_lines,
            "stats": self.stats,
        }


def validate_lines(
    *,
    lines: list[dict],
    approved_claims: list[dict],
    per_application_sealed_approvals: Iterable[str] = (),
) -> ValidatorResult:
    """
    lines: [{text: str, claim_ids: [str,...]}]
    approved_claims: list of the user's APPROVED claims (each has .id, .type, .value, .sensitivity)
    per_application_sealed_approvals: set of claim_type strings the user has explicitly
                                      approved for THIS application (out of scope for
                                      Phase 4 resume lines — always empty for now).

    Rejection reasons emitted (stable IDs, testable):
      - "empty_claim_ids"
      - "unapproved_claim:<id>"           (claim_id doesn't map to an APPROVED claim of this user)
      - "number_not_in_claims:<n>"        (line contains a number missing from every referenced claim)
      - "date_not_in_claims:<year>"
      - "sensitive_leak:<claim_type>"     (sealed value surfaced without per-app approval)
      - "malformed_line"                  (missing 'text' or non-list 'claim_ids')

    A line is accepted iff it has zero rejection reasons.
    """
    approved_by_id: dict[str, dict] = {c["id"]: c for c in (approved_claims or [])}
    sealed_approvals = set(per_application_sealed_approvals or [])

    passed: list[dict] = []
    rejected: list[dict] = []

    for line in lines or []:
        text = (line or {}).get("text")
        ids = (line or {}).get("claim_ids")
        reasons: list[str] = []

        if not isinstance(text, str) or not isinstance(ids, list):
            reasons.append("malformed_line")
            rejected.append(LineRejection(text=str(text or ""), claim_ids=list(ids or []), reasons=reasons).to_dict())
            continue

        text = text.strip()
        if not text:
            reasons.append("malformed_line")

        # Rule (a): empty claim_ids → reject
        if not ids:
            reasons.append("empty_claim_ids")

        # Rule (b): every claim_id must be an APPROVED claim of this user
        referenced_claims: list[dict] = []
        for cid in ids:
            if not isinstance(cid, str) or cid not in approved_by_id:
                reasons.append(f"unapproved_claim:{cid}")
            else:
                referenced_claims.append(approved_by_id[cid])

        # Rule (c1): numbers in text must appear in at least one referenced claim
        if referenced_claims:  # only meaningful when we have valid references
            numbers_in_text = _extract_numbers(text)
            allowed_numbers: set[str] = set()
            for c in referenced_claims:
                allowed_numbers |= _numbers_in_claim(c)
            for n in numbers_in_text:
                # Freestanding "1", "2" etc. in resume bullets are fine when they're
                # NOT numeric claims (they act as sentence position markers). We only
                # flag numbers of length >= 2 digits OR numbers >= 10 (heuristic).
                normalized = n.rstrip("kKM%")
                try:
                    if len(normalized) < 2 and float(normalized) < 10:
                        continue
                except ValueError:
                    continue
                if n not in allowed_numbers:
                    reasons.append(f"number_not_in_claims:{n}")

        # Rule (c2): years/dates in text must appear in at least one referenced claim
        if referenced_claims:
            years_in_text = _extract_years(text)
            allowed_years: set[str] = set()
            for c in referenced_claims:
                allowed_years |= _years_in_claim(c)
            for y in years_in_text:
                if y not in allowed_years:
                    reasons.append(f"date_not_in_claims:{y}")

        # Rule (d): sensitive-leak scan — sealed values must not surface unless approved.
        # Individual leaf value tokens are the leak surface, not the whole flattened
        # string (which would miss single-value leaks in a longer sentence).
        text_lower = text.lower()
        for c in approved_claims or []:
            if (c.get("sensitivity") or "").lower() != "sealed":
                continue
            ctype = c.get("type") or ""
            if ctype in sealed_approvals:
                continue
            for token in _sensitive_leak_tokens(c):
                if token.lower() in text_lower:
                    reasons.append(f"sensitive_leak:{ctype}")
                    break

        if reasons:
            rejected.append(LineRejection(text=text, claim_ids=list(ids or []), reasons=reasons).to_dict())
        else:
            passed.append({"text": text, "claim_ids": list(ids)})

    status = "failed" if rejected else "passed"
    return ValidatorResult(
        status=status,
        passed_lines=passed,
        rejected_lines=rejected,
        stats={
            "total": len(lines or []),
            "passed": len(passed),
            "rejected": len(rejected),
        },
    )


# ------------------------------------------------------------------ #
# Instruction refusal — bait-test path (check C)
# ------------------------------------------------------------------ #

def refuse_instruction(instruction: str, approved_claims: list[dict]) -> dict | None:
    """Return a refusal dict if the instruction asks for facts not in approved claims.

    Detected patterns (deliberately narrow — false positives here BLOCK real work):
      - "add my PMP certification" / "add my <cert>"
      - "include my patent" / "include my <thing>"
      - "mention my <language / degree / school / role>"
    …when the named entity is not found in any approved claim's flattened text.

    Returns:
      { "refused": true, "reason": "missing_claim:<entity>", "message": "..." } | None
    """
    if not instruction:
        return None
    text = instruction.strip().lower()

    # Extract likely factual entities behind "add my", "include my", "mention my", "list my"
    # The entity captured must be a token OR short phrase — followed by a suffix keyword
    # (cert/certification/degree/patent/…). The "my/i have" prefix is REQUIRED so we don't
    # capture stopwords like "my" itself as the entity.
    patterns = [
        # Case A: verb + "my" + ENTITY + SUFFIX ("add my PMP certification")
        r"(?:add|include|mention|list|say)\s+(?:i\s+have\s+|my\s+|that\s+i\s+have\s+|that\s+i\s+got\s+)"
        r"([a-z0-9][a-z0-9\-]{1,30}(?:\s+[a-z0-9][a-z0-9\-]{1,30}){0,3})"
        r"(?:\s+(?:cert(?:ification|ificate)?|degree|phd|patent|publication|award|license|role|experience))",
        # Case B: verb + "my" + SUFFIX-as-entity ("mention my patent on X" — the noun IS the fact)
        r"(?:add|include|mention|list|say)\s+(?:i\s+have\s+|my\s+|that\s+i\s+have\s+|that\s+i\s+got\s+)"
        r"(cert(?:ification|ificate)?|degree|phd|patent|publication|award|license)(?:\s+(?:on|in|about|for|of)\s+([a-z0-9][a-z0-9 \-]{1,40}))?",
    ]
    stopwords = {"the", "a", "an", "some", "any", "and", "or", "my", "own", "personal", "own"}
    haystack = " ".join(_flatten_claim_values_to_text(c).lower() for c in approved_claims or [])
    for pat in patterns:
        for m in re.finditer(pat, text):
            entity = m.group(1).strip()
            # Case B pattern may also expose group(2) with the "on X" object; append it if present.
            try:
                obj = m.group(2)
                if obj:
                    entity = f"{entity} {obj.strip()}"
            except IndexError:
                pass
            if not entity or len(entity) < 2:
                continue
            # Common noise words to skip
            if entity in stopwords:
                continue
            if entity not in haystack:
                return {
                    "refused": True,
                    "reason": f"missing_claim:{entity}",
                    "message": (
                        f"Instruction asks to include \"{entity}\" but no approved claim on your "
                        f"Passport supports it. Fynd never fabricates. Add the claim on "
                        f"your Passport with evidence, get it approved, and try again."
                    ),
                }
    return None
