import uuid
from fastapi import APIRouter, Depends
from core.deps import require_consent, get_current_user
from core.time_utils import utc_now
from core.db import get_db
from domains.preferences.models import PreferencesPayload
from domains.preferences import repository as repo
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1", tags=["preferences"])


@router.get("/preferences/me")
async def get_my_preferences(user: dict = Depends(get_current_user)):
    latest = await repo.latest_for_user(user["id"])
    if not latest:
        return {"version": 0, "payload": None, "updated_at": None}
    return {
        "version": latest["version"],
        "payload": latest["payload"],
        "updated_at": latest["updated_at"],
    }


@router.post("/preferences", status_code=201)
async def save_preferences(
    payload: PreferencesPayload,
    user: dict = Depends(require_consent("process_career_data")),
):
    version = await repo.next_version(user["id"])
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "version": version,
        "payload": payload.model_dump(),
        "updated_at": utc_now(),
    }
    await repo.insert(doc)
    await audit.write(user["id"], "preferences.save", f"user:{user['id']}", {"version": version})
    return {"version": version, "payload": doc["payload"], "updated_at": doc["updated_at"]}


# Taxonomy + Companies typeahead — supports the S5 UI
@router.get("/taxonomy", tags=["taxonomy"])
async def list_taxonomy(_user: dict = Depends(get_current_user)):
    cur = get_db().taxonomy.find({}, {"_id": 0}).sort("family", 1)
    return {"families": [r async for r in cur]}


@router.get("/companies", tags=["companies"])
async def search_companies(q: str = "", limit: int = 20, _user: dict = Depends(get_current_user)):
    q = (q or "").strip().lower()
    query: dict = {}
    if q:
        query = {"$or": [
            {"name": {"$regex": q, "$options": "i"}},
            {"domain": {"$regex": q, "$options": "i"}},
        ]}
    cur = get_db().companies.find(query, {"_id": 0}).limit(min(50, max(1, limit)))
    rows = [r async for r in cur]
    # Put SampleCo last so it doesn't crowd typeaheads
    rows.sort(key=lambda r: (r.get("domain") == "sampleco.demo", r.get("name", "")))
    return {"companies": rows}
