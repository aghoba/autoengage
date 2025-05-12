# routers/page.py: page install route
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.routers.auth import verify_session_jwt
from backend.db import get_db

router = APIRouter()

@router.post("/page/install")
async def install_page(
    token: str = Query(...),
    page_id: str = Query(...),
    access_token: str = Query(...),
    db=Depends(get_db)
):
    claims = verify_session_jwt(token)
    tenant_user_id = claims["sub"]
    tenant_row = await db.fetchrow(
        "SELECT id FROM tenants WHERE user_id = $1", tenant_user_id
    )
    if not tenant_row:
        raise HTTPException(404, "Tenant not found")
    tenant_id = tenant_row["id"]

    await db.execute(
        """
        INSERT INTO page_tokens (tenant_id,page_id,access_token)
        VALUES ($1,$2,$3)
        ON CONFLICT (page_id) DO UPDATE SET access_token = EXCLUDED.access_token
        """,
        tenant_id, page_id, access_token
    )
    await db.execute(
        """
        INSERT INTO page_settings (page_id, auto_reply_enabled)
        VALUES ($1, TRUE)
        ON CONFLICT (page_id) DO NOTHING
        """,
        page_id,
    )
    return {"page_id": page_id}