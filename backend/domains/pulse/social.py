"""Fynd Pulse · P3 social — real comments / threads / reports / notifications.

Decide-and-document privacy model (per ATLAS-STATE §11 defaults):

COMMENTS
  * Owner-only delete: only the comment's author OR the parent post's
    author may delete a comment. Deletes are HARD (row removed);
    denormalized counters on the parent post updated atomically.
  * Audience inherits the parent post's scope (`members`/`followers`/
    `private`). If the viewer cannot see the post, they cannot see or
    write its comments. Enforced by `_viewer_can_see_post`.
  * Block-aware visibility: comments by users the viewer has blocked
    (or vice versa) are hidden from list + count.
  * Honest empty state on the initial page.

THREADS / MESSAGING
  * 3-state request gating: `pending` → `accepted` | `declined`.
  * `pending` state: ONLY the initiator's FIRST message is visible to
    the recipient. Recipient must ACCEPT before any further messages
    are readable by either side (initiator's follow-on messages queue
    but do not render for the recipient until acceptance).
  * Participant-only reads: any outsider gets a strict `404`, never a
    `403` — non-participants MUST NOT be able to distinguish thread
    existence.
  * Block integration: if either party blocks the other AT ANY TIME,
    both sides get `404` on the thread. Block ends visibility, not
    just future writes.
  * No read-receipts unless mutual: `last_read_at` is only surfaced
    to the OTHER party when BOTH participants have accepted AND
    NEITHER has blocked. Otherwise the value is masked as `null`.
  * CSRF + ownership on every mutating route (CSRF middleware is
    global; ownership enforced per handler).

REPORTS
  * Persisted `pulse_reports` collection; every submission ACKs the
    reporter with the report id.
  * NO auto-punishment — every report is `state="pending"` until an
    admin reviews it. Admin surface at
    `/api/v1/admin/pulse/reports` lists pending; `PATCH` marks the
    state and records the reviewer.
  * Duplicate suppression: a reporter may not open more than one
    open report for the same target within 24 hours (409 conflict).

NOTIFICATIONS
  * Persisted `pulse_notifications` per user. Auto-emitted on:
      - like a post           → post_like
      - comment on a post     → post_comment
      - follow a user         → follow
      - open a thread request → message_request
  * User-scoped reads only. `read_at:null` counts as unread. Batch
    mark-read supported.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import get_current_user


router = APIRouter(prefix="/api/v1/pulse", tags=["pulse-social"])


# ==================================================================
# Helpers
# ==================================================================
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


async def _blocked_ids(db, user_id: str) -> set[str]:
    rows = await db.pulse_blocks.find(
        {"user_id": user_id}, {"blocked_id": 1, "_id": 0}
    ).to_list(500)
    return {r["blocked_id"] for r in rows}


async def _mutually_visible(db, viewer_id: str, other_id: str) -> bool:
    """True when neither party has blocked the other. Symmetric."""
    if viewer_id == other_id:
        return True
    if await db.pulse_blocks.find_one(
        {"user_id": viewer_id, "blocked_id": other_id}
    ):
        return False
    if await db.pulse_blocks.find_one(
        {"user_id": other_id, "blocked_id": viewer_id}
    ):
        return False
    return True


async def _viewer_can_see_post(db, viewer_id: str, post: dict) -> bool:
    """Audience gate mirrored from the pulse/posts list handler."""
    if post["author_id"] == viewer_id:
        return True
    if not await _mutually_visible(db, viewer_id, post["author_id"]):
        return False
    aud = post.get("audience", "members")
    if aud == "private":
        return False
    if aud == "followers":
        follows = await db.pulse_follows.find_one(
            {"user_id": viewer_id, "target_id": post["author_id"]}
        )
        if not follows:
            return False
    return True


async def _emit_notification(db, *, user_id: str, kind: str,
                              actor_id: str, target_kind: str,
                              target_id: str, meta: Optional[dict] = None) -> None:
    """Insert a notification row for `user_id`. Idempotent within a
    24h window per (user_id, kind, actor_id, target_id) to avoid
    spamming on repeated toggles (like/unlike/like)."""
    if user_id == actor_id:
        return  # never notify the actor about their own action
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    dup = await db.pulse_notifications.find_one({
        "user_id": user_id, "kind": kind, "actor_id": actor_id,
        "target_id": target_id, "created_at": {"$gte": cutoff},
    })
    if dup:
        return
    await db.pulse_notifications.insert_one({
        "id": _new_id(),
        "user_id": user_id,
        "kind": kind,
        "actor_id": actor_id,
        "target_kind": target_kind,
        "target_id": target_id,
        "created_at": _now_iso(),
        "read_at": None,
        "meta": meta or {},
    })


# ==================================================================
# COMMENTS
# ==================================================================
class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=1500)


@router.get("/posts/{post_id}/comments")
async def list_comments(
    post_id: str,
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """List comments on a post, respecting audience + block filters."""
    db = get_db()
    post = await db.pulse_posts.find_one({"id": post_id})
    if not post or not await _viewer_can_see_post(db, user["id"], post):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    blocked = await _blocked_ids(db, user["id"])
    q: dict[str, Any] = {"post_id": post_id}
    if cursor:
        q["created_at"] = {"$lt": cursor}
    rows = await (db.pulse_comments.find(q, {"_id": 0})
                    .sort("created_at", -1).limit(limit * 2)
                    .to_list(limit * 2))
    out: list[dict] = []
    for c in rows:
        if c["author_id"] in blocked:
            continue
        # Symmetric block: if the author blocked the viewer, hide.
        if not await _mutually_visible(db, user["id"], c["author_id"]):
            continue
        author_prof = await db.pulse_profiles.find_one(
            {"user_id": c["author_id"]}, {"_id": 0}) or {}
        out.append({
            "id":            c["id"],
            "post_id":       c["post_id"],
            "author_id":     c["author_id"],
            "author_name":   author_prof.get("name", "FYND member"),
            "author_role":   author_prof.get("role", ""),
            "body":          c["body"],
            "created_at":    c["created_at"],
            "can_delete":    (c["author_id"] == user["id"]
                              or post["author_id"] == user["id"]),
        })
        if len(out) >= limit:
            break
    next_cursor = out[-1]["created_at"] if len(out) == limit and out else None
    return {"items": out, "next_cursor": next_cursor}


@router.post("/posts/{post_id}/comments")
async def create_comment(
    post_id: str,
    payload: CommentCreate,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    post = await db.pulse_posts.find_one({"id": post_id})
    if not post or not await _viewer_can_see_post(db, user["id"], post):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    doc = {
        "id":         _new_id(),
        "post_id":    post_id,
        "author_id":  user["id"],
        "body":       payload.body,
        "created_at": _now_iso(),
    }
    await db.pulse_comments.insert_one(doc)
    # Update denormalized `replies` counter atomically.
    await db.pulse_posts.update_one(
        {"id": post_id}, {"$inc": {"replies": 1}}
    )
    # Notify the post author (unless they are commenting on their own post).
    await _emit_notification(
        db,
        user_id=post["author_id"],
        kind="post_comment",
        actor_id=user["id"],
        target_kind="post",
        target_id=post_id,
        meta={"comment_id": doc["id"]},
    )
    return {"comment": {
        "id":          doc["id"],
        "post_id":     doc["post_id"],
        "author_id":   doc["author_id"],
        "body":        doc["body"],
        "created_at":  doc["created_at"],
        "can_delete":  True,
    }}


@router.delete("/posts/{post_id}/comments/{comment_id}")
async def delete_comment(
    post_id: str,
    comment_id: str,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    c = await db.pulse_comments.find_one({"id": comment_id,
                                            "post_id": post_id})
    if not c:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    post = await db.pulse_posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    # Owner-only delete: comment author OR post author.
    if c["author_id"] != user["id"] and post["author_id"] != user["id"]:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    await db.pulse_comments.delete_one({"id": comment_id})
    await db.pulse_posts.update_one(
        {"id": post_id}, {"$inc": {"replies": -1}}
    )
    return {"ok": True}


# ==================================================================
# THREADS / MESSAGING
# ==================================================================
class ThreadStart(BaseModel):
    recipient_id: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1, max_length=3000)


class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=3000)


class ThreadDecision(BaseModel):
    decision: str = Field(..., pattern="^(accepted|declined)$")


async def _load_thread_for_participant(db, thread_id: str,
                                        viewer_id: str) -> dict:
    """Load a thread ONLY if the viewer is a participant AND no
    bidirectional block exists. Any other case surfaces 404 so
    outsiders cannot distinguish existence."""
    t = await db.pulse_threads.find_one({"id": thread_id})
    if not t or viewer_id not in t.get("participants", []):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    other = next(p for p in t["participants"] if p != viewer_id)
    if not await _mutually_visible(db, viewer_id, other):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return t


@router.get("/threads")
async def list_threads(user: dict = Depends(get_current_user)):
    """List threads the viewer participates in, filtered by block +
    the recipient-side visibility rule for `declined` state."""
    db = get_db()
    rows = await (db.pulse_threads.find(
        {"participants": user["id"]}, {"_id": 0}
    ).sort("last_message_at", -1).to_list(500))
    out: list[dict] = []
    for t in rows:
        other = next(p for p in t["participants"] if p != user["id"])
        if not await _mutually_visible(db, user["id"], other):
            continue
        # A `declined` thread is hidden from the recipient's inbox
        # but visible to the initiator (so they can see the outcome).
        if t["state"] == "declined" and t["initiator_id"] != user["id"]:
            continue
        other_prof = await db.pulse_profiles.find_one(
            {"user_id": other}, {"_id": 0}) or {}
        # Read-receipt masking: only surface the other party's
        # last_read_at when BOTH have accepted AND no block.
        can_see_receipt = (
            t["state"] == "accepted"
            and await _mutually_visible(db, user["id"], other)
        )
        last_read_by_other = (
            (t.get("last_read_at") or {}).get(other)
            if can_see_receipt else None
        )
        # Preview snippet: on a pending thread the recipient sees ONLY
        # the initiator's first message (which lives on the thread row
        # for exactly that purpose).
        preview = t.get("initial_body", "")
        if t["state"] == "accepted":
            last_msg = await (db.pulse_messages.find(
                {"thread_id": t["id"]}, {"_id": 0}
            ).sort("created_at", -1).limit(1).to_list(1))
            if last_msg:
                preview = last_msg[0]["body"][:200]
        out.append({
            "id":                t["id"],
            "other_id":          other,
            "other_name":        other_prof.get("name", "FYND member"),
            "state":             t["state"],
            "initiator_id":      t["initiator_id"],
            "created_at":        t["created_at"],
            "last_message_at":   t["last_message_at"],
            "preview":           preview,
            "other_last_read_at": last_read_by_other,
        })
    return {"items": out, "next_cursor": None}


@router.post("/threads")
async def start_thread(payload: ThreadStart,
                        user: dict = Depends(get_current_user)):
    """Open a new message-request thread. The initiator's first message
    is stored on the thread row so the recipient can see it while the
    thread is `pending`; further messages go into `pulse_messages` but
    are hidden from the recipient until acceptance."""
    db = get_db()
    if payload.recipient_id == user["id"]:
        raise HTTPException(status_code=400,
                            detail={"error": "cannot_message_self"})
    recipient = await db.users.find_one({"id": payload.recipient_id})
    if not recipient:
        # Match the 404-for-outsiders shape so probes cannot enumerate.
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if not await _mutually_visible(db, user["id"], payload.recipient_id):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    # Dedup: if an existing thread with this pair exists, return it.
    existing = await db.pulse_threads.find_one({
        "participants": {"$all": [user["id"], payload.recipient_id]},
    })
    if existing:
        return {"thread": {"id": existing["id"],
                             "state": existing["state"],
                             "initiator_id": existing["initiator_id"]}}
    doc = {
        "id":              _new_id(),
        "participants":    sorted([user["id"], payload.recipient_id]),
        "initiator_id":    user["id"],
        "state":           "pending",
        "initial_body":    payload.body,
        "created_at":      _now_iso(),
        "last_message_at": _now_iso(),
        "last_read_at":    {},
    }
    await db.pulse_threads.insert_one(doc)
    # Notify the recipient of the message request.
    await _emit_notification(
        db,
        user_id=payload.recipient_id,
        kind="message_request",
        actor_id=user["id"],
        target_kind="thread",
        target_id=doc["id"],
    )
    return {"thread": {"id": doc["id"], "state": doc["state"],
                        "initiator_id": doc["initiator_id"]}}


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str,
                         user: dict = Depends(get_current_user)):
    """List messages on a thread. On `pending` state, only the
    initiator's first message is visible to the recipient. On
    `accepted`, all messages are visible to both participants. On
    `declined`, the initiator sees their initial message; the
    recipient sees nothing."""
    db = get_db()
    t = await _load_thread_for_participant(db, thread_id, user["id"])
    is_initiator = user["id"] == t["initiator_id"]
    if t["state"] == "pending":
        if is_initiator:
            # Initiator sees everything they sent.
            msgs = await (db.pulse_messages.find(
                {"thread_id": thread_id}, {"_id": 0}
            ).sort("created_at", 1).to_list(500))
            # Prepend the initial body so it renders as message #1.
            all_msgs = [{"id": f"init:{t['id']}", "thread_id": t["id"],
                         "sender_id": t["initiator_id"],
                         "body": t["initial_body"],
                         "created_at": t["created_at"]}] + msgs
        else:
            # Recipient sees ONLY the initial body until they accept.
            all_msgs = [{"id": f"init:{t['id']}", "thread_id": t["id"],
                         "sender_id": t["initiator_id"],
                         "body": t["initial_body"],
                         "created_at": t["created_at"]}]
    elif t["state"] == "declined":
        if is_initiator:
            all_msgs = [{"id": f"init:{t['id']}", "thread_id": t["id"],
                         "sender_id": t["initiator_id"],
                         "body": t["initial_body"],
                         "created_at": t["created_at"]}]
        else:
            all_msgs = []
    else:  # accepted
        msgs = await (db.pulse_messages.find(
            {"thread_id": thread_id}, {"_id": 0}
        ).sort("created_at", 1).to_list(500))
        all_msgs = [{"id": f"init:{t['id']}", "thread_id": t["id"],
                     "sender_id": t["initiator_id"],
                     "body": t["initial_body"],
                     "created_at": t["created_at"]}] + msgs
    # Update viewer's last_read_at (but only surface it to the other
    # party when mutual + accepted — enforced in list_threads).
    if all_msgs:
        await db.pulse_threads.update_one(
            {"id": thread_id},
            {"$set": {f"last_read_at.{user['id']}": _now_iso()}},
        )
    return {"items": all_msgs, "state": t["state"],
             "initiator_id": t["initiator_id"]}


@router.post("/threads/{thread_id}/messages")
async def send_message(thread_id: str,
                        payload: MessageCreate,
                        user: dict = Depends(get_current_user)):
    """Send a new message.

    Rules:
      * Only participants may send. Outsiders get 404.
      * On `pending`, ONLY the initiator may send follow-on messages
        (they'll queue and become readable to the recipient after
        acceptance). The recipient cannot send on `pending` — they
        must accept first.
      * On `declined`, neither party may send.
    """
    db = get_db()
    t = await _load_thread_for_participant(db, thread_id, user["id"])
    if t["state"] == "declined":
        raise HTTPException(status_code=403,
                            detail={"error": "thread_declined"})
    if t["state"] == "pending" and user["id"] != t["initiator_id"]:
        raise HTTPException(status_code=403,
                            detail={"error": "accept_before_reply"})
    doc = {
        "id":         _new_id(),
        "thread_id":  thread_id,
        "sender_id":  user["id"],
        "body":       payload.body,
        "created_at": _now_iso(),
    }
    await db.pulse_messages.insert_one(dict(doc))
    await db.pulse_threads.update_one(
        {"id": thread_id},
        {"$set": {"last_message_at": doc["created_at"]}},
    )
    return {"message": {k: v for k, v in doc.items() if k != "_id"}}


@router.patch("/threads/{thread_id}")
async def decide_thread(thread_id: str,
                         payload: ThreadDecision,
                         user: dict = Depends(get_current_user)):
    """Accept or decline a pending thread. Only the recipient (the
    NON-initiator participant) may accept/decline. Initiator gets 404
    to avoid distinguishing 'wrong role' from 'not participant'."""
    db = get_db()
    t = await _load_thread_for_participant(db, thread_id, user["id"])
    if user["id"] == t["initiator_id"]:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if t["state"] != "pending":
        raise HTTPException(status_code=409,
                            detail={"error": "already_decided",
                                    "state": t["state"]})
    await db.pulse_threads.update_one(
        {"id": thread_id},
        {"$set": {"state": payload.decision,
                  "decided_at": _now_iso()}},
    )
    if payload.decision == "accepted":
        # Notify initiator that their request was accepted.
        await _emit_notification(
            db,
            user_id=t["initiator_id"],
            kind="thread_accepted",
            actor_id=user["id"],
            target_kind="thread",
            target_id=thread_id,
        )
    return {"ok": True, "state": payload.decision}


# ==================================================================
# REPORTS
# ==================================================================
class ReportSubmit(BaseModel):
    target_kind: str = Field(..., pattern="^(post|comment|user|message)$")
    target_id: str = Field(..., min_length=1)
    reason: str = Field(..., pattern="^(spam|harassment|misinformation|impersonation|nsfw|other)$")
    notes: Optional[str] = Field(None, max_length=1000)


@router.post("/reports")
async def submit_report(payload: ReportSubmit,
                         user: dict = Depends(get_current_user)):
    """Submit a moderation report. Never auto-punishes. Ack the
    reporter with the report id; admin review is human-only."""
    db = get_db()
    # Duplicate suppression within 24h.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    dup = await db.pulse_reports.find_one({
        "reporter_id": user["id"],
        "target_kind": payload.target_kind,
        "target_id":   payload.target_id,
        "state":       "pending",
        "created_at":  {"$gte": cutoff},
    })
    if dup:
        raise HTTPException(status_code=409, detail={
            "error": "duplicate_open_report",
            "report_id": dup["id"],
        })
    doc = {
        "id":          _new_id(),
        "reporter_id": user["id"],
        "target_kind": payload.target_kind,
        "target_id":   payload.target_id,
        "reason":      payload.reason,
        "notes":       payload.notes or "",
        "state":       "pending",
        "created_at":  _now_iso(),
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": "",
    }
    await db.pulse_reports.insert_one(dict(doc))
    return {"report": {"id": doc["id"], "state": doc["state"],
                        "created_at": doc["created_at"]}}


# ==================================================================
# NOTIFICATIONS
# ==================================================================
class NotificationsMarkRead(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


@router.get("/notifications")
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = None,
    unread_only: bool = False,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    q: dict[str, Any] = {"user_id": user["id"]}
    if cursor:
        q["created_at"] = {"$lt": cursor}
    if unread_only:
        q["read_at"] = None
    rows = await (db.pulse_notifications.find(q, {"_id": 0})
                    .sort("created_at", -1).limit(limit)
                    .to_list(limit))
    unread_total = await db.pulse_notifications.count_documents(
        {"user_id": user["id"], "read_at": None}
    )
    next_cursor = rows[-1]["created_at"] if len(rows) == limit else None
    return {"items": rows, "next_cursor": next_cursor,
             "unread_total": unread_total}


@router.post("/notifications/mark_read")
async def mark_notifications_read(payload: NotificationsMarkRead,
                                    user: dict = Depends(get_current_user)):
    """Batch mark-read. When `ids` is empty, marks ALL of the user's
    notifications as read (bulk sweep for the 'clear inbox' button)."""
    db = get_db()
    q: dict[str, Any] = {"user_id": user["id"], "read_at": None}
    if payload.ids:
        q["id"] = {"$in": payload.ids}
    r = await db.pulse_notifications.update_many(
        q, {"$set": {"read_at": _now_iso()}}
    )
    return {"ok": True, "updated": r.modified_count}
