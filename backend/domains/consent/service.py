from fastapi import HTTPException, status
from core.policy import CONSENT_SCOPES, SCOPE_KEYS, policy_version
from domains.consent import repository as repo
from domains.audit import service as audit


async def record(
    *,
    user_id: str,
    scope: str,
    granted: bool,
    policy_text_version: str,
    actor: str,
    source: str,
) -> str:
    if scope not in SCOPE_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unknown_scope")
    row_id = await repo.append({
        "user_id": user_id,
        "scope": scope,
        "granted": bool(granted),
        "policy_text_version": policy_text_version,
        "actor": actor,
        "source": source,
    })
    await audit.write(
        actor,
        "consent.grant" if granted else "consent.revoke",
        f"consent:{row_id}",
        {"user_id": user_id, "scope": scope, "policy_text_version": policy_text_version},
    )
    return row_id


async def state(user_id: str) -> dict:
    latest = await repo.latest_all(user_id)
    items = []
    for scope_def in CONSENT_SCOPES:
        scope = scope_def["scope"]
        row = latest.get(scope)
        items.append({
            "scope": scope,
            "granted": bool(row and row.get("granted")),
            "policy_text_version": row.get("policy_text_version") if row else None,
            "ts": row.get("ts") if row else None,
        })
    return {"scopes": items, "policy_text_version": policy_version()}
