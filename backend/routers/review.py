from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.background import BackgroundTasks
from backend.db import get_db
from services.reply_engine import handle_comment

router = APIRouter(prefix='/comments')

@router.get('/review')
async def list_pending(page_id: str = Query(None), db=Depends(get_db)):
    query = (
        "SELECT id, post_id, user_name, text, sentiment, created_at "
        "FROM comments WHERE status='pending_review'"
    )
    args = []
    if page_id:
        query += " AND page_id=$1"
        args.append(page_id)
    query += " ORDER BY created_at ASC"
    rows = await db.fetch(query, *args)
    return [dict(r) for r in rows]

@router.post('/review/{comment_id}/approve')
async def approve_comment(
    comment_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db)
):
    row = await db.fetchrow(
        "SELECT page_id FROM comments WHERE id=$1 AND status='pending_review'",
        comment_id
    )
    if not row:
        raise HTTPException(404, 'Comment not found or not pending review')
    await db.execute(
        "UPDATE comments SET status='approved' WHERE id=$1",
        comment_id
    )
    # queue the approved comment for AI reply
    background_tasks.add_task(handle_comment, comment_id)
    return {'id': comment_id, 'status': 'approved'}

@router.post('/review/{comment_id}/reject')
async def reject_comment(comment_id: str, db=Depends(get_db)):
    row = await db.fetchrow(
        "SELECT id FROM comments WHERE id=$1 AND status='pending_review'",
        comment_id
    )
    if not row:
        raise HTTPException(404, 'Comment not found or not pending review')
    await db.execute(
        "UPDATE comments SET status='rejected' WHERE id=$1",
        comment_id
    )
    return {'id': comment_id, 'status': 'rejected'}