SEALED_MASK = "•••• (sealed)"


def serialize_claim(claim: dict, viewer_id: str | None) -> dict:
    """Return a copy of `claim` with sealed values masked if viewer is not the owner.

    Note: sealed masking applies to admin and support too. The ONLY viewer who sees the
    real value is the owning user themselves.
    """
    out = dict(claim)
    out.pop("_id", None)
    if out.get("sensitivity") == "sealed" and out.get("user_id") != viewer_id:
        out["value"] = SEALED_MASK
        out["_sealed"] = True
    return out


def serialize_claims(claims: list[dict], viewer_id: str | None) -> list[dict]:
    return [serialize_claim(c, viewer_id) for c in claims]
