from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import auth, db, jobs
from app.routers.common import owned_page, page_out
from app.translation.pipeline import page_progress, translate_page

router = APIRouter(prefix="/api/pages", tags=["pages"])


@router.get("/{page_id}")
def get_page(page_id: UUID, user: dict = Depends(auth.current_user)):
    return page_out(owned_page(page_id, user))


@router.post("/{page_id}/translate")
def start_translation(page_id: UUID, user: dict = Depends(auth.current_user)):
    """Start (or resume) translating a page in the background. Idempotent; poll GET /api/pages/{id}."""
    page = owned_page(page_id, user)
    if page["status"] == "completed":
        return {"status": "completed", "started": False, **page_progress(page)}
    key = f"page:{page_id}"
    started = False
    if not jobs.is_running(key):
        # Mark immediately so pollers never see a stale 'pending'/'failed' after this call returns.
        db.execute("UPDATE pages SET status = 'processing', error = NULL WHERE id = %s", (page_id,))
        started = jobs.submit(key, translate_page, str(page_id))
    progress = page_progress(page)
    return JSONResponse({"status": "processing", "started": started, **progress}, status_code=202)
