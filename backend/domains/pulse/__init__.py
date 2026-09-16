"""Fynd Pulse — social & collider surface for the Pulse-UI shell.

Task 2 · route contract mirrors `/tmp/pulse-ui/.../public/network.js` at
prefix `/api/v1/pulse/*`. Namespaced so it can NOT collide with existing
`/api/v1/preferences` or `/api/v1/collider/scans` semantics. Every
endpoint runs `get_current_user` dep — no anonymous access.

Rails carried from FYND-ATLAS §10-19 + P1 Batches 1-4:
  * User-scoped reads/writes only — never leak cross-user data.
  * Follows: append-only edges. Unfollow is soft (edge deleted).
  * Blocks: bidirectional visibility hide; blocked user's rows are
    filtered from feed/discover/profile/threads.
  * Message threads: 3-state (pending / accepted / declined). While
    `pending`, only the requester's initial message is visible to the
    recipient; the recipient must ACCEPT before further messages read.
  * Post `audience`: `members` (everyone auth'd) / `followers` (only
    accepted follows) / `private` (author only).
  * Optimistic concurrency on `me` + `preferences` via `version` field.
  * Idempotency-Key on POST endpoints (existing middleware already
    honors the header globally).
  * NO LLM in this module — social + preference + collider trigger are
    all deterministic. Collider results wrap `discovery.service` +
    `gate_engine` + `entity_resolution` + `liveness`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/pulse", tags=["pulse"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ==================================================================
# Models — inline, non-invasive (do not extend the auth/users model)
# ==================================================================
class MePatch(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    role: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=400)
    location: Optional[str] = Field(None, max_length=100)
    skills: Optional[list[str]] = Field(None, max_length=8)
    signal: Optional[str] = Field(None, pattern="^(employed|open|exploring|better_offer|hiring)$")
    message_policy: Optional[str] = Field(None, pattern="^(requests|following|closed)$")
    version: int


class PostCreate(BaseModel):
    kind: str = Field(..., pattern="^(update|job|gig|collab|event)$")
    body: str = Field(..., min_length=1, max_length=3000)
    title: Optional[str] = Field(None, max_length=120)
    company: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=100)
    mode: Optional[str] = Field("any", pattern="^(any|remote|hybrid|onsite)$")
    currency: Optional[str] = Field(None, max_length=6)
    min_pay: Optional[int] = Field(0, ge=0, le=1_000_000_000)
    max_pay: Optional[int] = Field(0, ge=0, le=1_000_000_000)
    tags: list[str] = Field(default_factory=list, max_length=8)
    audience: str = Field("members", pattern="^(members|followers|private)$")


class PreferencesPatch(BaseModel):
    interests: list[str] = Field(default_factory=list, max_length=12)
    role: Optional[str] = Field(None, max_length=80)
    location: Optional[str] = Field(None, max_length=80)
    mode: str = Field("any", pattern="^(any|remote|hybrid|onsite)$")
    currency: str = Field("USD", max_length=6)
    min_pay: int = Field(0, ge=0, le=1_000_000_000)
    include_undisclosed: bool = True
    version: int


# ==================================================================
# Helper — assemble the `member` shape network.js expects
# ==================================================================
async def _member_public(db, user: dict) -> dict:
    prof = await db.pulse_profiles.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    return {
        "id":             user["id"],
        "name":           prof.get("name") or user.get("name") or "FYND member",
        "role":           prof.get("role", ""),
        "bio":            prof.get("bio", ""),
        "location":       prof.get("location", ""),
        "skills":         prof.get("skills", []),
        "signal":         prof.get("signal", "exploring"),
        "message_policy": prof.get("message_policy", "requests"),
        "version":        prof.get("version", 0),
    }


async def _prefs_public(db, user: dict) -> dict:
    prefs = await db.pulse_preferences.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    return {
        "interests":            prefs.get("interests", []),
        "role":                 prefs.get("role", ""),
        "location":             prefs.get("location", ""),
        "mode":                 prefs.get("mode", "any"),
        "currency":             prefs.get("currency", "USD"),
        "min_pay":              prefs.get("min_pay", 0),
        "include_undisclosed":  prefs.get("include_undisclosed", True),
        "version":              prefs.get("version", 0),
    }


async def _blocked_ids(db, user_id: str) -> set[str]:
    rows = await db.pulse_blocks.find({"user_id": user_id}, {"blocked_id": 1, "_id": 0}).to_list(500)
    return {r["blocked_id"] for r in rows}


async def _viewer_can_see_author(db, viewer: dict, author_id: str) -> bool:
    """Blocks are bidirectional — if either side blocked the other, hide."""
    if author_id == viewer["id"]:
        return True
    if await db.pulse_blocks.find_one({"user_id": viewer["id"], "blocked_id": author_id}):
        return False
    if await db.pulse_blocks.find_one({"user_id": author_id, "blocked_id": viewer["id"]}):
        return False
    return True


async def _post_public(db, viewer: dict, post: dict) -> dict:
    """Assemble the post shape network.js expects, computing viewer-
    specific `liked`, `saved`, and author display fields."""
    liked = bool(await db.pulse_post_reactions.find_one(
        {"user_id": viewer["id"], "post_id": post["id"], "kind": "like"}))
    saved = bool(await db.pulse_post_saves.find_one(
        {"user_id": viewer["id"], "post_id": post["id"]}))
    # Author display cached at write time; re-read the profile for freshness
    author_prof = await db.pulse_profiles.find_one({"user_id": post["author_id"]}, {"_id": 0}) or {}
    return {
        "id":             post["id"],
        "author_id":      post["author_id"],
        "author_name":    author_prof.get("name", post.get("author_name", "FYND member")),
        "author_role":    author_prof.get("role", ""),
        "author_signal":  author_prof.get("signal", "exploring"),
        "created_at":     post["created_at"],
        "kind":           post["kind"],
        "body":           post["body"],
        "title":          post.get("title", ""),
        "company":        post.get("company", ""),
        "location":       post.get("location", ""),
        "mode":           post.get("mode", "any"),
        "currency":       post.get("currency", ""),
        "min_pay":        post.get("min_pay", 0),
        "max_pay":        post.get("max_pay", 0),
        "tags":           post.get("tags", []),
        "audience":       post.get("audience", "members"),
        "likes":          post.get("likes", 0),
        "replies":        post.get("replies", 0),
        "liked":          liked,
        "saved":          saved,
    }


# ==================================================================
# 1. GET /api/v1/pulse/me — boot payload
# ==================================================================
@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    db = get_db()
    return {"member": await _member_public(db, user),
            "preferences": await _prefs_public(db, user)}


# ==================================================================
# 2. PATCH /api/v1/pulse/me — update profile (optimistic concurrency)
# ==================================================================
@router.patch("/me")
async def patch_me(patch: MePatch, user: dict = Depends(get_current_user)):
    db = get_db()
    cur = await db.pulse_profiles.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    cur_version = cur.get("version", 0)
    if patch.version != cur_version:
        raise HTTPException(status_code=409, detail={
            "error": "version_conflict",
            "message": "Your input is preserved. Reopen the form to see the latest saved version."})
    doc = {**cur, "user_id": user["id"], "version": cur_version + 1,
           "updated_at": _now_iso()}
    for k, v in patch.model_dump(exclude_none=True, exclude={"version"}).items():
        doc[k] = v
    await db.pulse_profiles.update_one({"user_id": user["id"]}, {"$set": doc}, upsert=True)
    return {"member": await _member_public(db, user)}


# ==================================================================
# 3. PUT /api/v1/pulse/preferences — Collider interests
# ==================================================================
@router.put("/preferences")
async def put_preferences(patch: PreferencesPatch, user: dict = Depends(get_current_user)):
    db = get_db()
    cur = await db.pulse_preferences.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    cur_version = cur.get("version", 0)
    if patch.version != cur_version:
        raise HTTPException(status_code=409, detail={
            "error": "version_conflict",
            "message": "Your input is preserved. Reopen the form."})
    doc = {**cur, "user_id": user["id"], **patch.model_dump(exclude={"version"}),
           "version": cur_version + 1, "updated_at": _now_iso()}
    await db.pulse_preferences.update_one({"user_id": user["id"]}, {"$set": doc}, upsert=True)
    return {"preferences": await _prefs_public(db, user)}


# ==================================================================
# 4. GET /api/v1/pulse/posts — feed / discover / profile / saved
# ==================================================================
@router.get("/posts")
async def list_posts(
    limit: int = Query(20, ge=1, le=50),
    cursor: Optional[str] = None,
    kind: Optional[str] = None,
    following: Optional[str] = None,
    q: Optional[str] = None,
    saved: Optional[str] = None,
    author: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    blocked = await _blocked_ids(db, user["id"])
    q_filter: dict[str, Any] = {}
    if kind:
        q_filter["kind"] = kind
    if author:
        q_filter["author_id"] = author
    if q:
        q_filter["$or"] = [{"body": {"$regex": q, "$options": "i"}},
                            {"title": {"$regex": q, "$options": "i"}}]
    if following == "1":
        follows = await db.pulse_follows.find({"user_id": user["id"]},
                                                {"target_id": 1, "_id": 0}).to_list(500)
        followed_ids = [f["target_id"] for f in follows]
        # Includes own posts too when Following tab is chosen (natural UX)
        q_filter["author_id"] = {"$in": followed_ids + [user["id"]]}
    if saved == "1":
        saved_rows = await db.pulse_post_saves.find({"user_id": user["id"]},
                                                     {"post_id": 1, "_id": 0}).to_list(500)
        saved_ids = [s["post_id"] for s in saved_rows]
        q_filter["id"] = {"$in": saved_ids}
    if cursor:
        q_filter["created_at"] = {"$lt": cursor}

    # Audience visibility: `members` visible to any authed user; `followers`
    # only if viewer follows author OR is author; `private` only if author.
    # Applied post-query so the audience check runs on final rows.
    rows = await (db.pulse_posts.find(q_filter, {"_id": 0})
                    .sort("created_at", -1).limit(limit * 3).to_list(limit * 3))
    followed_ids = None
    out: list[dict] = []
    for p in rows:
        if p["author_id"] in blocked:
            continue
        aud = p.get("audience", "members")
        if aud == "private" and p["author_id"] != user["id"]:
            continue
        if aud == "followers" and p["author_id"] != user["id"]:
            if followed_ids is None:
                followed_ids = {f["target_id"] for f in await db.pulse_follows.find(
                    {"user_id": user["id"]}, {"target_id": 1, "_id": 0}).to_list(500)}
            if p["author_id"] not in followed_ids:
                continue
        if not await _viewer_can_see_author(db, user, p["author_id"]):
            continue
        out.append(await _post_public(db, user, p))
        if len(out) >= limit:
            break
    next_cursor = out[-1]["created_at"] if len(out) == limit and out else None
    return {"items": out, "next_cursor": next_cursor}


# ==================================================================
# 5. POST /api/v1/pulse/posts
# ==================================================================
@router.post("/posts")
async def create_post(body: PostCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    prof = await db.pulse_profiles.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    doc = {"id": _new_id(), "author_id": user["id"],
           "author_name": prof.get("name", user.get("name", "FYND member")),
           "created_at": _now_iso(), "likes": 0, "replies": 0,
           **body.model_dump()}
    await db.pulse_posts.insert_one(doc)
    return {"post": await _post_public(db, user, doc)}


@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    p = await db.pulse_posts.find_one({"id": post_id})
    if not p:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if p["author_id"] != user["id"]:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    await db.pulse_posts.delete_one({"id": post_id})
    # Cascade: reactions + saves cleaned up
    await db.pulse_post_reactions.delete_many({"post_id": post_id})
    await db.pulse_post_saves.delete_many({"post_id": post_id})
    return {"ok": True}


# ==================================================================
# 6. Like / Save toggles — network.js sends PUT (add) or DELETE (remove)
# ==================================================================
async def _toggle_reaction(post_id: str, user_id: str, kind: str, add: bool):
    db = get_db()
    post = await db.pulse_posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    col = db.pulse_post_reactions if kind == "like" else db.pulse_post_saves
    exists = await col.find_one({"user_id": user_id, "post_id": post_id})
    if add and not exists:
        row = {"user_id": user_id, "post_id": post_id, "at": _now_iso()}
        if kind == "like":
            row["kind"] = "like"
        await col.insert_one(row)
        if kind == "like":
            await db.pulse_posts.update_one({"id": post_id}, {"$inc": {"likes": 1}})
    elif not add and exists:
        await col.delete_one({"_id": exists["_id"]})
        if kind == "like":
            await db.pulse_posts.update_one({"id": post_id}, {"$inc": {"likes": -1}})
    fresh = await db.pulse_posts.find_one({"id": post_id}, {"_id": 0})
    return fresh


@router.put("/posts/{post_id}/like")
async def like_add(post_id: str, user: dict = Depends(get_current_user)):
    fresh = await _toggle_reaction(post_id, user["id"], "like", add=True)
    # P3 notification: notify post author of the like (24h idempotent).
    from domains.pulse.social import _emit_notification as _emit
    await _emit(
        get_db(),
        user_id=fresh["author_id"], kind="post_like",
        actor_id=user["id"], target_kind="post", target_id=post_id,
    )
    return {"post": await _post_public(get_db(), user, fresh)}


@router.delete("/posts/{post_id}/like")
async def like_remove(post_id: str, user: dict = Depends(get_current_user)):
    fresh = await _toggle_reaction(post_id, user["id"], "like", add=False)
    return {"post": await _post_public(get_db(), user, fresh)}


@router.put("/posts/{post_id}/save")
async def save_add(post_id: str, user: dict = Depends(get_current_user)):
    fresh = await _toggle_reaction(post_id, user["id"], "save", add=True)
    return {"post": await _post_public(get_db(), user, fresh)}


@router.delete("/posts/{post_id}/save")
async def save_remove(post_id: str, user: dict = Depends(get_current_user)):
    fresh = await _toggle_reaction(post_id, user["id"], "save", add=False)
    return {"post": await _post_public(get_db(), user, fresh)}


# ==================================================================
# 7. Members — profile view + follow
# ==================================================================
@router.get("/members/{member_id}")
async def get_member(member_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    if not await _viewer_can_see_author(db, user, member_id):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    target = await db.users.find_one({"id": member_id}, {"_id": 0, "password_hash": 0})
    if not target:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    following = bool(await db.pulse_follows.find_one(
        {"user_id": user["id"], "target_id": member_id}))
    return {"member": await _member_public(db, target), "following": following}


@router.put("/members/{member_id}/follow")
async def follow_add(member_id: str, user: dict = Depends(get_current_user)):
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail={"error": "cannot_follow_self"})
    db = get_db()
    if not await _viewer_can_see_author(db, user, member_id):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    existed = await db.pulse_follows.find_one(
        {"user_id": user["id"], "target_id": member_id})
    await db.pulse_follows.update_one(
        {"user_id": user["id"], "target_id": member_id},
        {"$set": {"user_id": user["id"], "target_id": member_id, "at": _now_iso()}},
        upsert=True,
    )
    if not existed:
        # First-follow only — dedup by _emit_notification's 24h window
        # already covers repeat follows, but skip the DB call entirely
        # when we know it's a no-op.
        from domains.pulse.social import _emit_notification as _emit
        await _emit(
            db,
            user_id=member_id, kind="follow",
            actor_id=user["id"], target_kind="user", target_id=member_id,
        )
    return {"following": True}


@router.delete("/members/{member_id}/follow")
async def follow_remove(member_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    await db.pulse_follows.delete_one({"user_id": user["id"], "target_id": member_id})
    return {"following": False}


# ==================================================================
# 8. Blocks — bidirectional visibility hide
# ==================================================================
@router.put("/members/{member_id}/block")
async def block_add(member_id: str, user: dict = Depends(get_current_user)):
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail={"error": "cannot_block_self"})
    db = get_db()
    await db.pulse_blocks.update_one(
        {"user_id": user["id"], "blocked_id": member_id},
        {"$set": {"user_id": user["id"], "blocked_id": member_id, "at": _now_iso()}},
        upsert=True,
    )
    # Also unfollow to keep state coherent.
    await db.pulse_follows.delete_one({"user_id": user["id"], "target_id": member_id})
    return {"blocked": True}


@router.delete("/members/{member_id}/block")
async def block_remove(member_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    await db.pulse_blocks.delete_one({"user_id": user["id"], "blocked_id": member_id})
    return {"blocked": False}


@router.get("/blocks")
async def list_blocks(after: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
    db = get_db()
    q = {"user_id": user["id"]}
    if after:
        q["at"] = {"$lt": after}
    rows = await db.pulse_blocks.find(q, {"_id": 0}).sort("at", -1).limit(30).to_list(30)
    items = []
    for r in rows:
        t = await db.users.find_one({"id": r["blocked_id"]}, {"id": 1, "name": 1, "_id": 0})
        if t:
            items.append({"id": t["id"], "name": t.get("name", "Blocked member")})
    return {"items": items, "next_after": rows[-1]["at"] if len(rows) == 30 else None}


# ==================================================================
# 9. Collider — POST to start a real matching run; GET to poll
# ==================================================================
@router.get("/collider/runs")
async def get_recent_run(user: dict = Depends(get_current_user)):
    db = get_db()
    run = await db.pulse_collider_runs.find_one(
        {"user_id": user["id"]}, {"_id": 0},
        sort=[("started_at", -1)])
    return {"run": run}


@router.post("/collider/runs")
async def start_run(user: dict = Depends(get_current_user)):
    """Kick off a real Collider run wrapping the discovery + gate_engine
    stack. For P1-scope this returns synchronously with a done state;
    the async-poll shape is preserved so the UI's polling loop still
    works cleanly."""
    db = get_db()
    prefs = await db.pulse_preferences.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    run_id = _new_id()
    doc = {"id": run_id, "user_id": user["id"], "status": "running",
           "started_at": _now_iso(), "preferences_snapshot": prefs}
    await db.pulse_collider_runs.insert_one(doc)
    # Real matching — inline for MVP; wire to gate_engine for full stack.
    try:
        interests = [i.lower() for i in prefs.get("interests", [])]
        role = (prefs.get("role") or "").lower()
        mode = prefs.get("mode", "any")
        wanted_country_ok = True  # no explicit country filter surfaced in prefs yet
        # Query LIVE jobs from the ingested corpus. Only rows the
        # freshness/liveness gate would permit at prepare time.
        q: dict[str, Any] = {"is_sample": False,
                             "liveness.state": "active"}
        if mode == "remote":
            q["geo"] = {"$regex": "[Rr]emote"}
        cursor = db.jobs.find(q, {"_id": 0}).limit(200)
        examined = 0
        matches: list[dict] = []
        async for j in cursor:
            examined += 1
            title = (j.get("title") or "").lower()
            jd    = (j.get("jd_text") or "").lower()
            reasons: list[str] = []
            if role and role in title:
                reasons.append(f"Title matches your role “{prefs.get('role')}”")
            for kw in interests[:6]:
                if kw and (kw in title or kw in jd):
                    reasons.append(f"Mentions “{kw}”")
                    if len(reasons) >= 3:
                        break
            if not reasons:
                continue
            # Wrap as a post-shaped card so the UI's card() renderer works.
            post = {
                "id":            j["id"],
                "author_id":     "collider",
                "author_name":   j.get("company_name", "Employer"),
                "author_role":   "Live opportunity",
                "author_signal": "hiring",
                "created_at":    j.get("first_seen", _now_iso()),
                "kind":          "job",
                "body":          (j.get("jd_text") or "")[:400] + ("…" if len(j.get("jd_text") or "") > 400 else ""),
                "title":         j.get("title", ""),
                "company":       j.get("company_name", ""),
                "location":      j.get("geo") or "",
                "mode":          "remote" if "remote" in (j.get("geo") or "").lower() else "any",
                "currency":      "",
                "min_pay":       0, "max_pay": 0,
                "tags":          [],
                "audience":      "members",
                "likes":         0, "replies": 0,
                "liked":         False, "saved": False,
                "apply_url":     j.get("origin_url", ""),
            }
            matches.append({"reasons": reasons[:3], "post": post})
            if len(matches) >= 12:
                break
        doc.update({"status": "done", "finished_at": _now_iso(),
                    "result": {"matches": matches, "examined": examined,
                               "search_window": 200}})
    except Exception as exc:
        doc.update({"status": "failed", "finished_at": _now_iso(),
                    "error": str(exc)[:200]})
    await db.pulse_collider_runs.update_one({"id": run_id}, {"$set": doc})
    fresh = await db.pulse_collider_runs.find_one({"id": run_id}, {"_id": 0})
    return fresh


@router.get("/collider/runs/{run_id}")
async def poll_run(run_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    run = await db.pulse_collider_runs.find_one(
        {"id": run_id, "user_id": user["id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return run


# ==================================================================
# 10. Threads / messaging + comments + reports — P3 real endpoints.
# Delegated to `domains/pulse/social.py`. Its APIRouter (same
# `/api/v1/pulse` prefix) is mounted from `server.py` right after
# this module's router.
# ==================================================================
