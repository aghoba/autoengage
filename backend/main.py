"""
FastAPI + Clerk (manual JWT verify) – Windows‑native reference
"""
import os, time, json, httpx, asyncio, asyncpg
from functools import lru_cache
from dotenv import load_dotenv
from jose import jwt
from fastapi import FastAPI, Depends, HTTPException, Query

load_dotenv()                                        # .env in backend/

DATABASE_URL      = os.getenv("DATABASE_URL")
FRONTEND_API      = os.getenv("CLERK_FRONTEND_API")  # e.g. set-bat-44.clerk.accounts.dev
JWKS_URL          = f"https://{FRONTEND_API}/.well-known/jwks.json"
ALLOWED_ORIGIN    = "http://localhost:3000"

app = FastAPI()

# ────────────────────────────────────────────────────────────────────────────────
#  JWT helpers
# ────────────────────────────────────────────────────────────────────────────────
@lru_cache
def load_jwks():
    """Fetch Clerk's JWKS once and cache in memory (≈5 keys)."""
    print("🔑 Fetching Clerk JWKS …")
    resp = httpx.get(JWKS_URL, timeout=5)
    resp.raise_for_status()
    return resp.json()["keys"]

def verify_session_jwt(token: str) -> dict:
    """Return JWT claims if signature, exp/nbf and azp all check out."""
    try:
        claims = jwt.decode(
            token,
            load_jwks(),                     # key set
            algorithms=["RS256"],
            audience=None,                   # Clerk does not set aud
            issuer=f"https://{FRONTEND_API}",
        )
    except Exception as exc:
        raise HTTPException(401, f"Invalid Clerk token – {exc}")

    if claims.get("azp") != ALLOWED_ORIGIN:         # Extra defence
        raise HTTPException(401, "Wrong authorized party")

    return claims
# ────────────────────────────────────────────────────────────────────────────────

async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

@app.get("/healthz")
def health():
    return {"ok": True, "ts": time.time()}

@app.post("/auth/callback")
async def auth_callback(
    token: str = Query(..., description="Clerk session JWT"),
    db=Depends(get_db),
):
    claims = verify_session_jwt(token)              # <— one‑liner

    user_id = claims["sub"]
    await db.execute(
        "insert into tenants(user_id) values($1) on conflict do nothing",
        user_id,
    )
    return {"user_id": user_id}
