#!/usr/bin/env python
import os
from pathlib import Path
import asyncio
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.table import Table
import asyncpg

# Load .env variables (including DATABASE_URL)
# Point to the backend/.env file explicitly
env_path = Path(__file__).parent / "backend" / ".env"
load_dotenv(dotenv_path=env_path)

app = typer.Typer()
DATABASE_URL = os.getenv("DATABASE_URL")
async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()
async def get_conn():
    return await asyncpg.connect(DATABASE_URL)

@app.command()
def toggle_auto_reply(page_id: str):
    """
    Toggle the auto_reply_enabled setting for a specific Page.
    """
    print(DATABASE_URL)
    async def _toggle():
        #print(DATABASE_URL)
        conn = await get_conn()
        current = await conn.fetchval(
            "SELECT auto_reply_enabled FROM page_settings WHERE page_id = $1",
            page_id
        )
        new = not current
        await conn.execute(
            "UPDATE page_settings SET auto_reply_enabled = $1 WHERE page_id = $2;",
            new, page_id
        )
        await conn.close()
        state = 'enabled' if new else 'disabled'
        Console().print(f"Auto-reply for Page {page_id} is now [bold]{state}[/bold]")
    asyncio.run(_toggle())


@app.command()
def list_pending():
    """List all pending top-level comments."""
    async def _list():
        conn = await get_conn()
        rows = await conn.fetch(
            """
            SELECT id, user_name, text, created_at
              FROM comments
             WHERE replied = FALSE AND parent_id IS NULL;
            """
        )
        await conn.close()
        table = Table()
        table.add_column("Comment ID")
        table.add_column("User")
        table.add_column("Text")
        table.add_column("Created At")
        for r in rows:
            table.add_row(r["id"], r["user_name"], r["text"], str(r["created_at"]))
        Console().print(table)
    asyncio.run(_list())

@app.command()
def reply(comment_id: str):
    """Manually trigger auto-reply for a specific comment."""
    from services.reply_engine import handle_comment

    async def _reply():
        await handle_comment(comment_id)
        Console().print(f"Triggered auto-reply for {comment_id}")
    asyncio.run(_reply())

if __name__ == "__main__":
    app()
