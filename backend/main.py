"""
FastAPI + Clerk (manual JWT verify) – Windows‑native reference
(New: background auto‑reply hook)
"""
import os, time, httpx, asyncpg
from functools import lru_cache
from datetime import datetime, timezone
from dotenv import load_dotenv
from jose import jwt
from fastapi import (
    FastAPI,
    Depends,
    Request,
    HTTPException,
    Query,
    BackgroundTasks,
)

# ───────────────────────────────────────────
#  Local modules
# ───────────────────────────────────────────
# Handle_comment will generate + post a reply and mark the DB row
try:
    from services.reply_engine import handle_comment  # type: ignore
except ModuleNotFoundError:
    # Dev stub so the import doesn’t crash if not yet created
    async def handle_comment(comment_id: str):
        print("[stub] would handle", comment_id)

# ───────────────────────────────────────────
#  Environment
# ───────────────────────────────────────────
load_dotenv()
DATABASE_URL      = os.getenv("DATABASE_URL")
FRONTEND_API      = os.getenv("CLERK_FRONTEND_API") or ""
JWKS_URL          = f"https://{FRONTEND_API}/.well-known/jwks.json"
ALLOWED_ORIGIN    = os.getenv("ALLOWED_ORIGIN", "http://localhost:3000")
PAGE_ID           = os.getenv("PAGE_ID")            # your own Page ID
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")   # long‑lived page token
VERIFY_TOKEN      = os.getenv("META_VERIFY_TOKEN")   # webhook verify

app = FastAPI()

# ───────────────────────────────────────────
#  Clerk helpers
# ───────────────────────────────────────────
@lru_cache
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
#  DB dependency
# ───────────────────────────────────────────
async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

# ───────────────────────────────────────────
#  Health & auth endpoints
# ───────────────────────────────────────────
@app.get("/healthz")
async def health():
    return {"ok": True, "ts": time.time()}

@app.post("/auth/callback")
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
# ───────────────────────────────────────────
#  Health & auth endpoints
# ───────────────────────────────────────────
@app.post("/page/install")
async def install_page(
    token: str = Query(..., description="Clerk session JWT"),
    page_id: str = Query(...),
    access_token: str = Query(...),
    db=Depends(get_db)
):
    # 1) verify Clerk token → tenant.user_id → tenants.id
    claims = verify_session_jwt(token)
    tenant_user_id = claims["sub"]
    tenant_row = await db.fetchrow("SELECT id FROM tenants WHERE user_id = $1", tenant_user_id)
    if not tenant_row:
        raise HTTPException(404, "Tenant not found")
    tenant_id = tenant_row["id"]

    # 2) upsert into page_tokens
    await db.execute(
        """
        INSERT INTO page_tokens (tenant_id,page_id,access_token)
        VALUES ($1,$2,$3)
        ON CONFLICT (page_id) DO UPDATE SET access_token = EXCLUDED.access_token
        """,
        tenant_id, page_id, access_token
    )
    return {"page_id": page_id}

# ───────────────────────────────────────────
#  Meta webhook verification
# ───────────────────────────────────────────
@app.get("/meta/webhook")
async def fb_verify(request: Request):
    mode      = request.query_params.get("hub.mode")
    token     = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)
    raise HTTPException(403, "Verification failed")

# ───────────────────────────────────────────
#  Webhook handler (feed, mentions, messages)
# ───────────────────────────────────────────
@app.post("/meta/webhook")
async def fb_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
):
    payload = await request.json()
    print("📝 RAW WEBHOOK PAYLOAD:", payload) 
    for entry in payload.get("entry", []):
        page_id = entry["id"]
        print(page_id)
        # ─── Seed per-Page settings if it doesn’t exist ───
        await db.execute(
            """
            INSERT INTO page_settings (page_id)
            VALUES ($1)
            ON CONFLICT (page_id) DO NOTHING
            """,
            page_id
        )

        # ─── Read that flag ───
        enabled = await db.fetchval(
            "SELECT auto_reply_enabled FROM page_settings WHERE page_id = $1",
            page_id
        )
        if not enabled:
            # auto-reply is turned off for this Page—skip
            continue

        for change in entry.get("changes", []):
            field = change.get("field")
            val   = change.get("value", {})
            ts    = val.get("created_time") or entry.get("time")
            try:
                created_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                created_at = None

            # ───────── feed events (posts & comments) ─────────
            if field == "feed":
                item = val.get("item")
                verb = val.get("verb")

                # --- New post
                if item == "status":
                    post_id   = val.get("post_id")
                    message   = val.get("message")
                    from_info = val.get("from", {})
                    await db.execute(
                        """
                        INSERT INTO posts (id, page_id, message, from_id, from_name, verb, published, created_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                        ON CONFLICT DO NOTHING
                        """,
                        post_id,
                        page_id,
                        message,
                        from_info.get("id"),
                        from_info.get("name"),
                        verb,
                        bool(val.get("published")),
                        created_at,
                    )

                # --- New comment
                elif item == "comment":
                    comment_id   = val.get("comment_id")
                    parent_post  = val.get("post_id")
                    from_info    = val.get("from", {})
                    parent_id    = val.get("parent_id")  # None for top‑level
                    text         = val.get("message")

                    await db.execute(
                        """
                        INSERT INTO comments (
                        id, page_id, post_id, text, platform, parent_id, user_id, user_name, verb, created_at
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                        ON CONFLICT DO NOTHING
                        """,
                        comment_id,
                        page_id,         # << new
                        parent_post,
                        text,
                        "facebook",
                        parent_id,
                        from_info["id"],
                        from_info["name"],
                        val.get("verb"),
                        created_at,
                    )


                    # Schedule auto‑reply only if top‑level & not by our own Page
                    if parent_id is None and from_info.get("id") != PAGE_ID:
                        background_tasks.add_task(handle_comment, comment_id)

            # ───────── Mentions ─────────
            elif field == "mention":
                mention_id = f"mention-{val.get('post_id')}-{val.get('sender_id')}-{ts}"
                await db.execute(
                    """
                    INSERT INTO mentions (id, post_id, sender_id, sender_name, verb, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    ON CONFLICT DO NOTHING
                    """,
                    mention_id,
                    val.get("post_id"),
                    val.get("sender_id"),
                    val.get("sender_name"),
                    val.get("verb"),
                    created_at,
                )

            # ───────── Messages ─────────
            elif field == "messages":
                msg_id = val.get("message_id") or val.get("mid")
                await db.execute(
                    """
                    INSERT INTO messages (id, thread_id, sender_id, recipient_id, message, platform, verb, created_at)
                    VALUES ($1,$2,$3,$4,$5,'facebook',$6,$7)
                    ON CONFLICT DO NOTHING
                    """,
                    msg_id,
                    val.get("thread_id"),
                    val.get("sender_id"),
                    val.get("recipient_id"),
                    val.get("message") or val.get("text"),
                    val.get("verb"),
                    created_at,
                )
    return {"status": "received"}
