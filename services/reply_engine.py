import os
import asyncpg
import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Environment
DATABASE_URL      = os.getenv("DATABASE_URL")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
llm = OpenAI(api_key=OPENAI_API_KEY)

async def generate_reply(comment_text: str) -> str:
    """
    Use GPT-4o to craft a friendly, on-brand reply in the same language.
    """
    prompt = (
        f"Brand-tone: friendly and helpful.\n"
        f"Reply to this customer comment in the same language:\n\n\"{comment_text}\""
    )
    resp = llm.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[
            {"role": "system", "content": "You are a customer support assistant."},
            {"role": "user",   "content": prompt},
        ],
    )
    return resp.choices[0].message.content.strip()

async def post_reply(comment_id: str, reply_text: str) -> str:
    """
    Post the generated reply via the Facebook Graph API.
    Returns the new Facebook reply comment ID.
    """
    url = f"https://graph.facebook.com/v19.0/{comment_id}/comments"
    params = {
        "message":      reply_text,
        "access_token": PAGE_ACCESS_TOKEN
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, params=params)
        response.raise_for_status()
        data = response.json()
    return data.get("id")

async def handle_comment(comment_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # 1) Get comment text & page_id
        row = await conn.fetchrow(
            "SELECT text, page_id FROM comments WHERE id = $1 AND replied = FALSE",
            comment_id
        )
        if not row:
            return
        comment_text, page_id = row["text"], row["page_id"]

        # 2) Get that Page’s token
        token_row = await conn.fetchrow(
            "SELECT access_token FROM page_tokens WHERE page_id = $1",
            page_id
        )
        if not token_row:
            print(f"No token for page {page_id}, skipping reply")
            return
        page_token = token_row["access_token"]

        # 3) Generate reply (same as before)
        reply_text = await generate_reply(comment_text)

        # 4) Post using THAT token
        fb_reply_id = await post_reply(comment_id, reply_text, page_token)

        # 5) Mark replied
        await conn.execute(
            "UPDATE comments SET replied = TRUE, reply_id = $2 WHERE id = $1",
            comment_id, fb_reply_id
        )
    finally:
        await conn.close()


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