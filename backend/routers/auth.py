# routers/auth.py: authentication routes
from fastapi import APIRouter, Depends, HTTPException, Query
from jose import jwt
import httpx
from functools import lru_cache
from backend.config   import JWKS_URL, FRONTEND_API, ALLOWED_ORIGIN
from backend.db import get_db
import time
router = APIRouter()

# ───────────────────────────────────────────
#  Clerk helpers
# ───────────────────────────────────────────
@lru_cache()
def load_jwks():
    """Fetch Clerk JWKS, cached in memory."""
    resp = httpx.get(JWKS_URL, timeout=5)
    resp.raise_for_status()
    return resp.json()["keys"]

def verify_session_jwt(token: str) -> dict:
    """Validate Clerk token & return claims."""
    try:
        claims = jwt.decode(
            token,
            load_jwks(),
            algorithms=["RS256"],
            audience=None,
            issuer=f"https://{FRONTEND_API}",
        )
    except Exception as exc:
        raise HTTPException(401, f"Invalid Clerk token – {exc}")
    if claims.get("azp") != ALLOWED_ORIGIN:
        raise HTTPException(401, "Wrong authorized party")
    return claims

# ───────────────────────────────────────────
#  Health & auth endpoints
# ───────────────────────────────────────────
@router.get("/healthz")
async def health():
    return {"ok": True, "ts": time.time()}

@router.post("/auth/callback")
async def auth_callback(
    token: str = Query(..., description="Clerk session JWT"),
    db=Depends(get_db),
):
    claims = verify_session_jwt(token)
    user_id = claims["sub"]
    await db.execute(
        "INSERT INTO tenants(user_id) VALUES($1) ON CONFLICT DO NOTHING",
        user_id,
    )
    return {"user_id": user_id}