import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.deps import get_current_user, require_consent
from core.db import get_db
from services.gate_engine import build_context, evaluate
from services.scoring import score as score_job, WEIGHTS_VERSION
from domains.jobs.models import ImportRequest, ResolveOriginRequest, HideRequest
from domains.jobs import service as jobs_svc, repository as jobs_repo
from domains.applications import service as apps_svc
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


# --------------------------------------------------------------------- #
# Feed response cache (Phase-0 addendum, founder-authorized 2026-08-04)
# In-process TTL cache; deterministic scoring means same inputs → same
# outputs within the 60s window. Cache is invalidated by process
# restart (accepted trade-off — bounded staleness).
# --------------------------------------------------------------------- #
_feed_cache: dict[tuple, tuple[float, dict]] = {}
_FEED_CACHE_TTL_S = 60.0




def _shape_job_card(job: dict, score_row: dict | None) -> dict:
    from services.gate_engine import _is_stale
    from services import velocity as vel_svc
    stale = _is_stale(job)
    effective_status = "stale" if stale and job.get("status") == "live" else job.get("status")
    disc = job.get("discovery") or {}
    velocity = vel_svc.estimate(job)
    return {
        "id": job["id"],
        "canonical_key": job.get("canonical_key"),
        "title": job.get("title"),
        "company_name": job.get("company_name"),
        "company_domain": job.get("company_domain"),
        "geo": job.get("geo"),
        "comp": job.get("comp"),
        "taxonomy_family": job.get("taxonomy_family"),
        "apply_method": job.get("apply_method"),
        "status": effective_status,
        "is_sample": bool(job.get("is_sample")),
        "last_verified": job.get("last_verified"),
        "needs_origin": bool(job.get("needs_origin")),
        "score": (score_row or {}).get("score"),
        "confidence": (score_row or {}).get("confidence"),
        "weights_version": (score_row or {}).get("weights_version"),
        # Discovery/enrichment surfaces exposed to the client so the
        # feed UI can filter and label rows. Never invented — these are
        # populated by the discovery adapters from the ATS payload.
        "source": job.get("source"),
        "apply_url": job.get("origin_url"),
        "is_newgrad": bool(job.get("is_newgrad")),
        "tags": job.get("tags") or [],
        "remote": bool(disc.get("remote")),
        "posted_at": disc.get("posted_at"),
        "employment_type": disc.get("employment_type"),
        "department": disc.get("department"),
        "source_ats": disc.get("source_ats"),
        # Phase 2 — two-lane feed + Phoenix distance
        "lane": job.get("lane"),
        "distance_from_phoenix_mi": job.get("distance_from_phoenix_mi"),
        # Phase 3 — income velocity estimate (Lane B "soonest money")
        "velocity": velocity,
    }


@router.get("/feed")
async def feed(user: dict = Depends(require_consent("discover_jobs")),
                lane: str | None = None,
                within_mi: int | None = None,
                sort: str = "best_fit"):
    """Feed for the signed-in candidate.

    Query params (Phase 2):
      * lane        - 'career' | 'income_now' | None (all)
      * within_mi   - if set, only jobs whose distance_from_phoenix_mi <= N
      * sort        - 'best_fit' (default, by match score) | 'nearest'
                       (Phoenix distance ascending, remote/unknown last)

    Perf caching (Phase-0 addendum, founder-authorized 2026-08-04):
      * In-process response cache keyed by (user_id, weights_version,
        lane, within_mi, sort) with 60s TTL. Returns byte-identical
        payload — no change to scoring outputs, guarded by a strict
        equality test in `tests/test_feed_perf_cache_byte_identical.py`.
      * Cache is process-local; a rolling deploy or restart invalidates
        it. Because the underlying `jobs_repo.list_live()`,
        `build_context()`, `evaluate()`, `score_job()` and the
        `match_scores.upsert()` writer are all deterministic within
        the 60s window (`weights_version` is bumped whenever scoring
        semantics change), same inputs → same outputs.
    """
    # Phase 6 — feed_enabled feature flag (§C.4). Flag OFF returns an honest 503 the UI
    # renders as "temporarily disabled by operations".
    from services import feature_flags as ff
    if not await ff.is_enabled("feed_enabled", default=True):
        raise HTTPException(status_code=503, detail={
            "error": "feature_disabled", "flag": "feed_enabled",
            "message": "Feed temporarily disabled by operations. Please try again in a few minutes.",
        })
    # Also require the passport to be activated. We surface an honest error the UI can render as a
    # passport-activation gate (distinct from consent gate).
    fresh = await get_db().users.find_one({"id": user["id"]}, {"passport_activated": 1, "_id": 0})
    if not (fresh and fresh.get("passport_activated")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "passport_not_activated", "hint": "Activate your Passport in /passport before browsing the feed."})

    # ------ perf cache lookup (additive) ------
    import time as _time
    cache_key = (user["id"], lane, within_mi, sort)
    cached = _feed_cache.get(cache_key)
    if cached is not None and (_time.monotonic() - cached[0]) < _FEED_CACHE_TTL_S:
        return cached[1]

    ctx = await build_context(user["id"])
    hidden = ctx.get("hidden_job_ids") or set()
    all_live = await jobs_repo.list_live()
    # Founder Fix Round-2 · P0 #2 — gate-engine parity: apply hidden filter identically on
    # BOTH feed and coverage-preview. Hidden count is reported as its own totals entry so
    # the two surfaces are directly comparable.
    jobs = [j for j in all_live if j["id"] not in hidden]
    hidden_count = sum(1 for j in all_live if j["id"] in hidden)

    # Phase 2 — lane + distance filters (never remove; only narrow the view).
    if lane in ("career", "income_now"):
        jobs = [j for j in jobs if j.get("lane") == lane]
    if within_mi is not None and within_mi > 0:
        jobs = [j for j in jobs
                if isinstance(j.get("distance_from_phoenix_mi"), (int, float))
                and j["distance_from_phoenix_mi"] <= within_mi]

    passing: list[dict] = []
    excluded: list[dict] = []
    excluded_by_reason: dict[str, int] = {}
    unknown_by_reason: dict[str, int] = {}
    scored_new_count = 0
    from domains.match_scores import service as ms
    from domains.usage_meters import service as um

    for job in jobs:
        gate = evaluate(ctx, job)
        if gate["pass_all"]:
            s = score_job(ctx, job, gate)
            was_new = await ms.upsert(user_id=user["id"], job_id=job["id"], score=s, gates=gate)
            if was_new:
                scored_new_count += 1
            passing.append({
                **_shape_job_card(job, s),
                "gates": gate["gates"],
                "notes": gate.get("notes") or [],
                "top_reasons": [rc for rc in s["reason_codes"] if rc["weight_applied"] > 0][:2],
                "route": apps_svc.route_decision(job),
            })
        else:
            excluded.append({
                "id": job["id"],
                "title": job.get("title"),
                "company_name": job.get("company_name"),
                "is_sample": bool(job.get("is_sample")),
                "canonical_key": job.get("canonical_key"),
                "fail_reasons": gate["fail_reasons"],
                "unknown_reasons": gate["unknown_reasons"],
                "notes": gate.get("notes") or [],
            })
            for reason in gate["fail_reasons"]:
                excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1
            for reason in gate["unknown_reasons"]:
                unknown_by_reason[reason] = unknown_by_reason.get(reason, 0) + 1
    if scored_new_count:
        await um.increment_jobs_processed(user["id"], scored_new_count)

    # Sort choice — Phase 2 introduced 'nearest' for Lane B users; Phase 3 adds
    # 'velocity' (soonest expected weekly income). Default remains best-fit score.
    if sort == "nearest":
        def _sort_key(x):
            d = x.get("distance_from_phoenix_mi")
            if not isinstance(d, (int, float)):
                d = 1e6  # remote/unknown sink to the end
            posted = x.get("posted_at") or ""
            return (d, -len(posted))  # nearer first, more recent second
        passing.sort(key=_sort_key)
    elif sort in ("velocity", "soonest_money"):
        def _vel_key(x):
            v = (x.get("velocity") or {}).get("velocity_score")
            if not isinstance(v, (int, float)):
                v = -1  # unknown velocity sinks to the end
            posted = x.get("posted_at") or ""
            return (-v, -len(posted))  # higher velocity first, more recent second
        passing.sort(key=_vel_key)
    else:
        passing.sort(key=lambda x: (x.get("score") or 0), reverse=True)
    # Phase 5.1 — surface the last successful lifecycle-sweep timestamp so
    # the UI can honestly render "last polled X mins ago". `live` on the
    # feed now means "present on the source board as of the last successful
    # poll" — a stale/closed row is filtered by list_live()'s status='live'
    # query, but the founder rule also requires the poll timestamp be
    # explicit in the response.
    last_sweep = await get_db().lifecycle_sweep_runs.find_one(
        {}, {"_id": 0, "id": 1, "finished_at": 1, "closed_total": 1,
              "boards_swept": 1},
        sort=[("finished_at", -1)],
    )

    response = {
        "weights_version": WEIGHTS_VERSION,
        "lane": lane or "all",
        "sort": sort,
        "within_mi": within_mi,
        "passing": passing,
        "excluded": excluded,
        "totals": {
            "live_jobs": len(all_live),
            "passing": len(passing),
            "excluded": len(excluded),
            "hidden": hidden_count,
            "excluded_by_reason": excluded_by_reason,
            "unknown_by_reason": unknown_by_reason,
        },
        "discovery": {
            "polled_at": (last_sweep or {}).get("finished_at"),
            "sweep_id": (last_sweep or {}).get("id"),
            "boards_swept_last_pass": (last_sweep or {}).get("boards_swept"),
            "closed_last_pass": (last_sweep or {}).get("closed_total"),
        },
    }
    # ------ perf cache write (additive) ------
    _feed_cache[cache_key] = (_time.monotonic(), response)
    return response


@router.get("/{job_id}")
async def job_detail(job_id: str, user: dict = Depends(require_consent("discover_jobs"))):
    job = await jobs_repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    ctx = await build_context(user["id"])
    gate = evaluate(ctx, job)
    s = None
    if gate["pass_all"]:
        s = score_job(ctx, job, gate)
        from domains.match_scores import service as ms
        await ms.upsert(user_id=user["id"], job_id=job_id, score=s, gates=gate)

    # Have/gap for skills using approved skill claims (never unapproved)
    req_skills = [str(x).lower() for x in ((job.get("requirements") or {}).get("skills_required") or [])]
    approved = ctx.get("approved_skills") or set()
    have = [s for s in req_skills if s in approved]
    gap = [s for s in req_skills if s not in approved]
    return {
        **_shape_job_card(job, s),
        "origin_url": job.get("origin_url"),
        "jd_text": job.get("jd_text"),
        "eligibility_requirements": job.get("eligibility_requirements") or {},
        "requirements": job.get("requirements") or {},
        "gates": gate["gates"],
        "pass_all": gate["pass_all"],
        "notes": gate.get("notes") or [],
        "reason_codes": (s or {}).get("reason_codes") or [],
        "have_gap": {"have": have, "gap": gap, "required": req_skills},
        "route": apps_svc.route_decision(job),
    }


@router.post("/import", status_code=201)
async def import_link(req: ImportRequest, user: dict = Depends(require_consent("discover_jobs"))):
    return await jobs_svc.user_import(user["id"], req.url, req.title, req.company_name)


@router.get("/imports/me")
async def my_imports(user: dict = Depends(require_consent("discover_jobs"))):
    rows = await jobs_repo.list_derived_for_user(user["id"])
    return {"imports": rows}


@router.post("/{job_id}/resolve")
async def resolve(job_id: str, req: ResolveOriginRequest, user: dict = Depends(require_consent("discover_jobs"))):
    return await jobs_svc.resolve_derived(user["id"], job_id, req.origin_url, req.notes)


@router.post("/{job_id}/hide", status_code=201)
async def hide_job(job_id: str, req: HideRequest, user: dict = Depends(require_consent("discover_jobs"))):
    job = await jobs_repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    await jobs_repo.add_hidden(user["id"], job_id, req.reason)
    await audit.write(user["id"], "job.hide", f"job:{job_id}", {"reason": req.reason})
    return {"hidden": True, "job_id": job_id, "reason": req.reason}


@router.post("/{job_id}/shortlist", status_code=201)
async def shortlist_job(job_id: str, user: dict = Depends(require_consent("discover_jobs"))):
    job = await jobs_repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    try:
        app_row = await apps_svc.shortlist(user["id"], job)
    except apps_svc.DuplicateApplication:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "already_shortlisted"})
    except apps_svc.EmployerCapReached as e:
        # Phase 3 — rolling 30-day per-employer safety cap.
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={
            "error": "employer_cap_reached",
            "message": (f"You've reached the {e.cap_info['cap']}-per-{e.cap_info['window_days']}-day cap "
                        f"for {e.cap_info.get('employer') or 'this employer'}. "
                        "Focus on other employers first, or wait for the window to roll."),
            **e.cap_info,
        })
    return app_row



# --------------------------------------------------------------------- #
# SURPRISE ME — Fynd Liquid directive (2026-07-28)
#
# Draws ONE eligible job deliberately OUTSIDE the user's usual title
# / industry lanes (measured by the median score-derived family of the
# user's shortlisted applications). The candidate MUST still pass:
#   * the three hard gates (evaluate.pass_all is True)
#   * the rolling 30-day per-employer cap logic (informational — draw
#     itself does not consume the cap; the cap kicks in at shortlist)
#   * dedup — no job the user has already drawn today may be redrawn
# Rate-limit: 5 draws per user per calendar day (UTC).
# Consent-gate: `discover_jobs`.
# Draws are logged in `surprise_me_draws` for audit + no-repeat.
# --------------------------------------------------------------------- #

from datetime import datetime, timezone, timedelta
import random as _random

_SURPRISE_DAILY_LIMIT = 5


async def _user_usual_families(user_id: str) -> set[str]:
    """Infer the user's usual title families from their shortlisted /
    submitted applications. If they have fewer than 2 apps, the set is
    empty and Surprise Me draws from the full eligible pool."""
    db = get_db()
    fams: dict[str, int] = {}
    async for a in db.applications.find(
        {"user_id": user_id,
         "state": {"$in": ["shortlisted", "preparing", "awaiting_approval",
                            "approved", "submitting", "submitted", "response",
                            "interview", "offer"]}},
        {"job_snapshot": 1, "_id": 0},
    ):
        snap = a.get("job_snapshot") or {}
        fam = (snap.get("taxonomy_family") or "").strip().lower()
        if fam:
            fams[fam] = fams.get(fam, 0) + 1
    if sum(fams.values()) < 2:
        return set()
    return set(fams.keys())


@router.post("/surprise-me")
async def surprise_me(user: dict = Depends(require_consent("discover_jobs"))):
    """Return ONE outside-lane eligible job with a validator-grounded
    "why you qualify" trace. Rate-limited to 5/day, logged, no-repeat.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    todays_draws = [d async for d in db.surprise_me_draws.find(
        {"user_id": user["id"], "drawn_at": {"$gte": day_start}},
        {"_id": 0, "job_id": 1},
    )]
    if len(todays_draws) >= _SURPRISE_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail={
            "error": "surprise_daily_limit_reached",
            "limit": _SURPRISE_DAILY_LIMIT,
            "remaining_today": 0,
            "message": (f"You've drawn {_SURPRISE_DAILY_LIMIT} surprises today. "
                          "The dice reset at midnight UTC."),
        })
    already_drawn_ids = {d["job_id"] for d in todays_draws}

    # Also exclude any job the user has ever drawn (across all time) so
    # the same row never comes up twice.
    async for d in db.surprise_me_draws.find(
        {"user_id": user["id"]}, {"_id": 0, "job_id": 1},
    ):
        already_drawn_ids.add(d["job_id"])

    usual = await _user_usual_families(user["id"])
    ctx = await build_context(user["id"])
    hidden = ctx.get("hidden_job_ids") or set()
    all_live = await jobs_repo.list_live()

    # Candidate pool = live · not hidden · not already-drawn · passes 3 gates
    # · OUTSIDE the user's usual families (unless they have <2 apps).
    candidates: list[tuple[dict, dict, dict]] = []
    for job in all_live:
        if job["id"] in hidden or job["id"] in already_drawn_ids:
            continue
        if job.get("is_sample"):
            # Founder rule: Surprise Me never draws SAMPLE rows — the whole
            # point is real, verifiable, out-of-lane opportunities.
            continue
        fam = (job.get("taxonomy_family") or "").strip().lower()
        if usual and fam and fam in usual:
            continue  # inside usual lane — skip
        gate = evaluate(ctx, job)
        if not gate["pass_all"]:
            continue
        s = score_job(ctx, job, gate)
        candidates.append((job, gate, s))
        if len(candidates) >= 200:
            break  # bounded scan — this endpoint must return quickly

    if not candidates:
        return {
            "job": None,
            "why_you_qualify": [],
            "remaining_today": _SURPRISE_DAILY_LIMIT - len(todays_draws),
            "message": ("No outside-lane opportunities are eligible right now. "
                          "As Fynd sees more Passport claims and the discovery "
                          "catalog grows, this will populate."),
        }

    # Deterministic-but-varied pick: weight lightly by score so a stronger
    # match is preferred but we still surprise the user.
    weights = [max(1, int((s.get("score") or 0) * 100)) for _, _, s in candidates]
    picked = _random.choices(candidates, weights=weights, k=1)[0]
    job, gate, s = picked

    # "why you qualify" trace — pulled ONLY from the scoring `reason_codes`
    # that were POSITIVELY applied and the gate `notes`. Never invents.
    why: list[str] = []
    for rc in (s or {}).get("reason_codes") or []:
        if (rc.get("weight_applied") or 0) > 0 and rc.get("explanation"):
            why.append(rc["explanation"])
        if len(why) >= 3:
            break
    for note in (gate.get("notes") or [])[:2]:
        if note not in why:
            why.append(note)

    # Log the draw. Append-only; never overwritten.
    from domains.audit import service as audit_svc
    draw_id = str(uuid.uuid4())
    await db.surprise_me_draws.insert_one({
        "id": draw_id,
        "user_id": user["id"],
        "job_id": job["id"],
        "employer": job.get("company_name"),
        "taxonomy_family": job.get("taxonomy_family"),
        "score": (s or {}).get("score"),
        "drawn_at": now,
        "usual_families_snapshot": sorted(usual),
    })
    await audit_svc.write(user["id"], "feed.surprise_me.draw",
                             f"job:{job['id']}",
                             {"draw_id": draw_id,
                              "employer": job.get("company_name"),
                              "taxonomy_family": job.get("taxonomy_family")})

    return {
        "draw_id": draw_id,
        "job": _shape_job_card(job, s),
        "why_you_qualify": why,
        "remaining_today": _SURPRISE_DAILY_LIMIT - (len(todays_draws) + 1),
        "message": ("This role sits outside the lanes you usually apply to, "
                     "but your Passport meets every hard gate. Have a look."),
    }


@router.get("/surprise-me/status")
async def surprise_me_status(user: dict = Depends(require_consent("discover_jobs"))):
    """How many draws remain today; used by the UI to enable/disable the CTA."""
    db = get_db()
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    used = await db.surprise_me_draws.count_documents(
        {"user_id": user["id"], "drawn_at": {"$gte": day_start}})
    return {
        "limit": _SURPRISE_DAILY_LIMIT,
        "used_today": used,
        "remaining_today": max(0, _SURPRISE_DAILY_LIMIT - used),
    }
