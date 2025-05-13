import os
import asyncpg
import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Environment
DATABASE_URL      = os.getenv("DATABASE_URL")
#PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
llm = OpenAI(api_key=OPENAI_API_KEY)



async def generate_reply(comment_text: str) -> str:
    """
    Use GPT-4o to craft a friendly, on-brand reply in the same language.
    """
    prompt = (
        f"Brand-tone: Neutral.\n"
        f"Reply to this customer comment in the same language (Either English or Egyptian Arabic):\n\n\"{comment_text}\""
    )
    resp = llm.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[
            {"role": "system", "content": "You are a customer support assistant."},
            {"role": "user",   "content": prompt},
        ],
    )
    return resp.choices[0].message.content.strip()

async def post_reply(comment_id: str, reply_text: str, page_access_token:str ) -> str:
    """
    Post the generated reply via the Facebook Graph API.
    Returns the new Facebook reply comment ID.
    """
    url = f"https://graph.facebook.com/v22.0/{comment_id}/comments"
    params = {
        "message":      reply_text,
        "access_token": page_access_token
    }
    # e.g. 30 s connect / 60 s read
    timeout = httpx.Timeout(timeout=60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, params=params)
        response.raise_for_status()
        data = response.json()
            # Log the full response for debugging
    if response.status_code != 200:
        print("⚠️ Facebook reply failed!")
        print("URL:  ", url)
        print("Status:", response.status_code)
        print("Request payload:", params)
        print("Response body:", response.text)
        response.raise_for_status()

    return data.get("id")

async def handle_comment(comment_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # 1) Load the comment you’re replying to
        # Fetch comment text, page_id, and user_name
        row = await conn.fetchrow(
        """
        SELECT *
          FROM comments
         WHERE id = $1
           AND replied = FALSE
           AND status = 'approved'
        """,
        comment_id
        )
        if not row:
            return
        comment_text, page_id, user_id, user_name = row["text"], row["page_id"], row["user_id"], row["user_name"]
        page_name = await conn.fetchval(
        "SELECT page_name FROM page_tokens WHERE page_id=$1",
        page_id
        )

        # Get the Page’s access token
        token_row = await conn.fetchrow(
            "SELECT access_token FROM page_tokens WHERE page_id = $1",
            page_id
        )
        if not token_row:
            print(f"No token for page {page_id}, skipping reply")
            return

        page_token = token_row["access_token"]
        # Don’t ever reply to your own Page’s comments
        if user_id == page_id:
            return

        post_id   = row["post_id"]
        parent_id = row["parent_id"] or row["id"]

        # 2) Fetch the entire reply‐thread for this comment using a recursive CTE
        history = await conn.fetch(
            """
            WITH RECURSIVE thread AS (
              SELECT id, parent_id, post_id, user_id, user_name, text, created_at
                FROM comments
               WHERE id = $1
              UNION ALL
              SELECT c.id, c.parent_id, c.post_id, c.user_id, c.user_name, c.text, c.created_at
                FROM comments c
                JOIN thread t ON c.parent_id = t.id
            )
            SELECT *
              FROM thread
             WHERE post_id = $2
             ORDER BY created_at ASC
            """,
            parent_id,
            post_id
        )

        # 3) Build the OpenAI chat history including author names
        messages = [{
                "role": "system",
                "content": (
                    f"You are an AI-powered customer support assistant for the “{page_name}” Facebook Page. "
                    "Your goal is to respond in a friendly, helpful, and concise manner, using the full "
                    "conversation context to answer users’ questions accurately."
                    "Reply to this customer comment in the same language (Either English or Egyptian Arabic):"
                )
            }
        ]

        for msg in history:
            author = "Assistant" if msg["user_id"] == page_id else msg["user_name"]
            role   = "assistant" if msg["user_id"] == page_id else "user"
            # prefix with name so AI knows who said what
            messages.append({
                "role": role,
                "content": f"{author}: {msg['text']}"
            })

        # 4) Generate reply using full thread context
        raw_reply = await generate_reply(messages)
        #raw_reply = response.choices[0].message.content.strip()
        print(messages," ",raw_reply)
        # 5) Prefix the user’s name for clarity
        reply_text = f"{row['user_name']}, {raw_reply}"

        # 6) Store & send as before…
        await conn.execute(
            "INSERT INTO replies (post_id, reply_text) VALUES ($1, $2)",
            comment_id, reply_text
        )
        fb_reply_id = await post_reply(comment_id, reply_text, page_token)
        if not fb_reply_id:
            return
        await conn.execute(
            "UPDATE comments SET replied = TRUE, reply_id = $2 WHERE id = $1",
            comment_id, fb_reply_id
        )

    finally:
        await conn.close()


async def classify_sentiment(text: str) -> str:
    """
    Uses OpenAI to label text as 'positive', 'neutral', or 'negative'.
    """
    prompt = (
        "Classify the sentiment of this user comment into one of: "
        "positive, neutral, negative.\n\n"
        f"Comment: \"{text}\""
    )
    resp = llm.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[
            {"role": "system", "content": "You are an expert sentiment analyzer."},
            {"role": "user",   "content": prompt},
        ],
    )
    label = resp.choices[0].message.content.strip().lower()
    # normalize answers
    return {"positive": "positive", "neutral": "neutral", "negative": "negative"}.get(label, "neutral")


# Optional: CLI worker entrypoint
def main():
    import asyncio
    async def loop():
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            while True:
                rows = await conn.fetch(
                    "SELECT id FROM comments WHERE replied = FALSE AND parent_id IS NULL"
                )
                for r in rows:
                    await handle_comment(r["id"])
                await asyncio.sleep(5)
        finally:
            await conn.close()
    asyncio.run(loop())


if __name__ == "__main__":
    main()