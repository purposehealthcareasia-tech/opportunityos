"""Golden-set runner.

Sends each labeled fixture through the same LLM parse path that the resume-upload flow uses
(`services.llm.parse_resume_text`), then scores field accuracy against the labeled expectations.

Honest checker: a field is credited when at least one claim of the corresponding TYPE contains
the labeled substring (case-insensitive) somewhere in its value. We deliberately grade "did
you find this fact", not "did you format it my way".

Run:
    cd /app/backend && python3 -m tests.golden_resumes.golden_run
Add --json to emit machine-readable output.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Path setup so we can be run as `python3 -m tests.golden_resumes.golden_run` from /app/backend.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.llm import parse_resume_text  # noqa: E402
from tests.golden_resumes.fixtures import FIXTURES  # noqa: E402


def _flat_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (str, int, float)):
        return str(v)
    if isinstance(v, list):
        return " ".join(_flat_value(x) for x in v)
    if isinstance(v, dict):
        return " ".join(_flat_value(x) for x in v.values())
    return str(v)


def _find_any(claims: list[dict], want_type: str, needle: str) -> bool:
    """True iff any claim.type == want_type contains needle (case-insensitive) in its value."""
    needle_lower = needle.lower().strip()
    if not needle_lower:
        return True
    for c in claims:
        if c.get("type") != want_type:
            continue
        text = _flat_value(c.get("value")).lower()
        if needle_lower in text:
            return True
    return False


def score_fixture(fixture: dict, claims: list[dict]) -> dict:
    exp = fixture["expected"]
    total = 0
    hits = 0
    misses: list[str] = []

    def check(label: str, ok: bool):
        nonlocal total, hits
        total += 1
        if ok:
            hits += 1
        else:
            misses.append(label)

    # identity.name
    if exp.get("name"):
        check(f"identity:{exp['name']}", _find_any(claims, "identity", exp["name"]))
    # contact.email / contact.phone
    for e in exp.get("emails", []):
        check(f"email:{e}", _find_any(claims, "contact", e))
    for p in exp.get("phones", []):
        check(f"phone:{p}", _find_any(claims, "contact", p))
    # location.city
    for loc in exp.get("locations", []):
        check(f"location:{loc.get('city')}", _find_any(claims, "location", loc.get("city", "")))
    # link
    for l in exp.get("links", []):
        check(f"link:{l['kind']}:{l['substring']}", _find_any(claims, "link", l["substring"]))
    # education
    for edu in exp.get("education", []):
        # Institution string is the more distinctive signal
        check(f"education:{edu['institution']}", _find_any(claims, "education", edu["institution"]))
    # employment
    for emp in exp.get("employment", []):
        check(f"employment:{emp['company']}", _find_any(claims, "employment", emp["company"]))
    # skills — each skill is its own claim by prompt design
    for sk in exp.get("skills", []):
        check(f"skill:{sk}", _find_any(claims, "skill", sk))

    return {
        "slug": fixture["slug"],
        "total": total,
        "hits": hits,
        "accuracy": round(hits / total, 4) if total else 0.0,
        "misses": misses,
        "n_claims": len(claims),
    }


async def run_one(fixture: dict) -> dict:
    result = await parse_resume_text(fixture["text"], document_id=fixture["slug"], user_id="golden_runner")
    return {"fixture": fixture, "parsed": result, "score": score_fixture(fixture, result.get("claims") or [])}


async def run_all(limit: int | None = None) -> dict:
    fixtures = FIXTURES[:limit] if limit else FIXTURES
    results = []
    for f in fixtures:
        try:
            r = await run_one(f)
        except Exception as e:
            r = {"fixture": f, "parsed": {"error": str(e)}, "score": {"slug": f["slug"], "total": 0, "hits": 0, "accuracy": 0.0, "misses": ["parse_error"], "n_claims": 0}}
        results.append(r)
    total_labeled = sum(x["score"]["total"] for x in results)
    total_hits = sum(x["score"]["hits"] for x in results)
    overall = round(total_hits / total_labeled, 4) if total_labeled else 0.0
    return {
        "n_fixtures": len(results),
        "total_labeled_fields": total_labeled,
        "total_hits": total_hits,
        "overall_accuracy": overall,
        "target": 0.95,
        "passed_target": overall >= 0.95,
        "per_fixture": [x["score"] for x in results],
    }


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    report = asyncio.run(run_all(limit=args.limit))
    out_path = Path(__file__).parent / "last_report.json"
    out_path.write_text(json.dumps(report, indent=2))

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Golden set: {report['n_fixtures']} fixtures, {report['total_labeled_fields']} labeled fields")
    print(f"Hits: {report['total_hits']} / {report['total_labeled_fields']}")
    print(f"Overall accuracy: {report['overall_accuracy']:.2%}  (target 95%)")
    print(f"Target met: {'YES' if report['passed_target'] else 'NO'}")
    print()
    print("Per-fixture:")
    for r in report["per_fixture"]:
        marker = "✓" if r["accuracy"] >= 0.95 else "!"
        print(f"  {marker} {r['slug']:12s} {r['hits']:>3}/{r['total']:<3}  {r['accuracy']:.2%}  claims={r['n_claims']}  misses={r['misses']}")


if __name__ == "__main__":
    _cli()
