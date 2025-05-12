# routers/webhook.py: Facebook webhook handler
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from datetime import datetime, timezone
from backend.db import get_db
from backend.config import VERIFY_TOKEN, PAGE_ID
from services.reply_engine import handle_comment

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
            continue  # auto-reply is turned off for this Page

        for change in entry.get("changes", []):
            field = change.get("field")
            val   = change.get("value", {})
            ts    = val.get("created_time") or entry.get("time")
            try:
                created_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                created_at = None

            if field == "feed":
                await _handle_feed(val, page_id, db, background_tasks, created_at)

            elif field == "mention":
                await _handle_mention(val, created_at, db)

            elif field == "messages":
                await _handle_message(val, created_at, db)

    return {"status": "received"}


async def _handle_feed(val, page_id, db, background_tasks, created_at):
    item = val.get("item")
    verb = val.get("verb")

    # Helper: parse Facebook ISO timestamp or default
    def parse_fb_time(iso_str):
        try:
            # Facebook returns e.g. "2025-05-12T09:41:23+0000"
            # Python needs “+00:00” instead of “+0000”
            tz_fixed = iso_str[:-2] + ":" + iso_str[-2:]
            return datetime.fromisoformat(tz_fixed)
        except Exception:
            return datetime.now(timezone.utc)
        
    # --- New post
    if item == "status":
        post_id   = val.get("post_id")
        message   = val.get("message")
        from_info = val.get("from", {})
        await db.execute(
            """
            INSERT INTO posts (
              id, page_id, message, from_id, from_name, verb, published, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
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
        comment_id  = val.get("comment_id")
        parent_post = val.get("post_id")   # this is the post_id FK
        from_info   = val.get("from", {})
        parent_id   = val.get("parent_id")
        text        = val.get("message")

        # 1) Skip empty text
        if not text:
            print(f"Skipping comment {comment_id} — no text found. {verb} action")
            return

        # 2) Auto-insert stub post if missing
         # Ensure the parent post exists, using the same timestamp as above
        post_exists = await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM posts WHERE id=$1)", parent_post
        )
        if not post_exists:
            # Try to pull timestamp off of val["post"], if present
            post_info = val.get("post", {})
            post_ts    = post_info.get("updated_time")
            stub_ts    = parse_fb_time(post_ts) if post_ts else datetime.now(timezone.utc)
            print(f"Auto-stubbing missing post {parent_post}")
            await db.execute(
                """
                INSERT INTO posts (id, page_id, created_at)
                VALUES ($1, $2, $3)
                """,
                parent_post,
                page_id,
                stub_ts,
            )

        # 3) Check/normalize parent_id
        if parent_id:
            parent_exists = await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM comments WHERE id=$1)",
                parent_id
            )
            if not parent_exists:
                parent_id = None

        # 4) Insert the comment
        await db.execute(
            """
            INSERT INTO comments (
              id, page_id, post_id, text, platform,
              parent_id, user_id, user_name, verb, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT DO NOTHING
            """,
            comment_id,
            page_id,
            parent_post,
            text,
            "facebook",
            parent_id,
            from_info["id"],
            from_info["name"],
            val.get("verb"),
            created_at,
        )

        # 5) Queue auto-reply if needed
        if parent_id is None and from_info.get("id") != PAGE_ID:
            background_tasks.add_task(handle_comment, comment_id)



async def _handle_mention(val, created_at, db):
    mention_id = f"mention-{val.get('post_id')}-{val.get('sender_id')}-{val.get('created_time')}"
    await db.execute(
        """
        INSERT INTO mentions (
            id, post_id, sender_id, sender_name, verb, created_at
        ) VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT DO NOTHING
        """,
        mention_id,
        val.get("post_id"),
        val.get("sender_id"),
        val.get("sender_name"),
        val.get("verb"),
        created_at,
    )


async def _handle_message(val, created_at, db):
    msg_id = val.get("message_id") or val.get("mid")
    await db.execute(
        """
        INSERT INTO messages (
            id, thread_id, sender_id, recipient_id, message, platform, verb, created_at
        ) VALUES ($1,$2,$3,$4,$5,'facebook',$6,$7)
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
