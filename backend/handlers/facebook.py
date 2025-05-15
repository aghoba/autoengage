# backend/handlers/facebook.py
from datetime import datetime, timezone
from services.reply_engine import handle_comment, classify_sentiment
from backend.config import VERIFY_TOKEN
# leave get_db out—router passes db connection in


async def handle_feed(val, page_id, db, background_tasks, created_at):
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
        comment_id  = val["comment_id"]
        parent_post = val["post_id"]
        from_info   = val.get("from", {})
        author_id   = from_info.get("id")
        author_name = from_info.get("name")
        parent_id   = val.get("parent_id")
        text        = val.get("message")
        # print(comment_id," ",parent_post," ",from_info," ",author_id," ",author_name," ",parent_id," ",text)
        # 1) Skip empty text
        if not text:
            print(f"Skipping comment {comment_id} — no text found. ({verb} action)")
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

        # 1) classify sentiment
        sentiment = await classify_sentiment(text)
        # 3) auto-approve any comments authored by the Page itself
        if author_id == page_id:
            status = 'approved'
        else:
            # 2) fetch page’s auto-reply settings
            enabled = await db.fetchrow(
                "SELECT auto_reply_enabled, auto_reply_negative FROM page_settings WHERE page_id=$1",
                page_id
            )
            if enabled:
                auto_reply_enabled, auto_reply_negative  = enabled
                #= enabled["auto_reply_negative"]
            else:
                # default fallback if page_settings missing
                auto_reply_enabled, auto_reply_negative = True, False
            
            # 3) determine status: use auto_reply_negative if sentiment is 'negative'
            if not auto_reply_enabled:
                status = 'pending_review'
            elif sentiment == 'negative' and not auto_reply_negative:
                status = 'pending_review'
            else:
                status = 'approved'
        print(f"Comment {comment_id} sentiment: {sentiment} Status: {status}")
        
        # 4) Insert the comment
        await db.execute(
            """
            INSERT INTO comments (
              id, page_id, post_id, text, platform,
              parent_id, user_id, user_name, verb, created_at,
            sentiment, status
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT DO NOTHING
            """,
            comment_id,
            page_id,
            parent_post,
            text,
            "facebook",
            parent_id,
            author_id,
            author_name,
            val.get("verb"),
            created_at, 
            sentiment, 
            status
        )
        # after you’ve inserted the comment into DB
        
        # 5) Queue auto-reply if needed
        # new: schedule for any comment not authored by the Page itself
        print(author_id," ",page_id)
        if author_id != page_id and status == 'approved':
            background_tasks.add_task(handle_comment, comment_id)

async def handle_mention(val, created_at, db):
    # 1) pull the actor from the payload
    from_info  = val.get("from", {})
    sender_id   = from_info.get("id")
    sender_name = from_info.get("name")

    # 2) skip if we lack sender info
    if not sender_id or not sender_name:
        print(f"Skipping mention—no sender info: {val}")
        return

    # 3) build your mention_id however you like
    mention_id = f"mention-{val.get('post_id')}-{sender_id}-{created_at.timestamp()}"

    # 4) now insert safely
    await db.execute(
        """
        INSERT INTO mentions (
          id, post_id, sender_id, sender_name, verb, created_at
        ) VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT DO NOTHING
        """,
        mention_id,
        val.get("post_id"),
        sender_id,
        sender_name,
        val.get("verb"),
        created_at,
    )

async def handle_message(val, created_at, db):
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
