# routers/webhook.py: Facebook webhook handler
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from backend.db import get_db
from backend.config import VERIFY_TOKEN
from backend.handlers import facebook  # new

router = APIRouter()

# ───────────────────────────────────────────
#  Meta webhook verification
# ───────────────────────────────────────────
@router.get("/meta/webhook")
async def verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)
    raise HTTPException(403, "Verification failed")

# ───────────────────────────────────────────
#  Webhook handler (feed, mentions, messages)
# ───────────────────────────────────────────
@router.post("/meta/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
):
    payload = await request.json()
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
        # if not enabled:
        #     continue  # auto-reply is turned off for this Page
        # seed page_settings row (same code) …

        for change in entry.get("changes", []):
            field = change.get("field")
            val   = change.get("value", {})
            ts    = val.get("created_time") or entry.get("time")
            try:
                created_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                created_at = None

            if field == "feed":
                await facebook.handle_feed(val, page_id, db, background_tasks, created_at)
            elif field == "mention":
                await facebook.handle_mention(val, created_at, db)
            elif field == "messages":
                await facebook.handle_message(val, created_at, db)
            # instagram handlers will slot in here later

    return {"status": "received"}
