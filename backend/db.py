# db.py: database connection dependency
import asyncpg
from fastapi import Depends
from backend.config import DATABASE_URL

# ───────────────────────────────────────────
#  DB dependency
# ───────────────────────────────────────────
async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()
