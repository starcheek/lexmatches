import hashlib
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app import auth, db, storage, tts
from app.config import settings
from app.ingest import MAX_TEXT_CHARS, Document, IngestError, apply_overrides, build_units, ingest_file, ingest_text
from app.ingest.fetch import fetch
from app.ingest.pipeline import precheck
from app.languages import to_iso
from app.routers.common import BOOK_FIELDS, PAGE_FIELDS, book_out, owned_book, page_out
from app.services.export import render_export
from app.services.processing import create_uploaded_book, store_document

router = APIRouter(prefix="/api/books", tags=["books"])
_IMPORTED = ("paste", "paste_html", "url")  # source formats without a stored original file


def _rejected(e: IngestError) -> JSONResponse:
    """Ingestion errors: {"detail": user-facing message, "code": stable machine code}."""
    return JSONResponse({"detail": str(e), "code": e.code}, status_code=e.status)


@router.get("")
def list_books(user: dict = Depends(auth.current_user)):
    # preview: the beginning of the first page, shown on the library card
    rows = db.fetch_all(
        f"SELECT {BOOK_FIELDS}, (SELECT left(p.original_text, 600) FROM pages p"
        f" WHERE p.book_id = books.id AND p.page_number = 1) AS preview"
        f" FROM books WHERE user_id = %s ORDER BY created_at DESC", (user["id"],)
    )
    return [book_out(r) for r in rows]


@router.post("", status_code=201)
def upload_book(
    title: str = Form(..., min_length=1, max_length=200),
    original_locale: str = Form(...),
    target_locale: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(auth.current_user),
):
    """Any supported file (PDF, EPUB, FB2, DOCX, ODT, RTF, Markdown, HTML, TXT; sniffed from the content).
    DRM, MOBI and unknown formats are rejected here; parsing runs in the background (book `pending`)."""
    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File size must be less than {settings.max_upload_mb}MB")
    try:
        fmt = precheck(data)
    except IngestError as e:
        return _rejected(e)
    return book_out(create_uploaded_book(user["id"], title, original_locale, target_locale, data, fmt))


def _create_imported(user: dict, title: str, original_locale: str, target_locale: str, doc: Document) -> dict:
    with db.connection() as conn:
        book = conn.execute(
            f"INSERT INTO books (user_id, title, original_locale, target_locale, source, source_format, status)"
            f" VALUES (%s, %s, %s, %s, 'text', %s, 'processing') RETURNING id",
            (user["id"], title.strip()[:200], original_locale, target_locale, doc.source_format),
        ).fetchone()
        store_document(book["id"], doc, conn)
        book = conn.execute(f"SELECT {BOOK_FIELDS} FROM books WHERE id = %s", (book["id"],)).fetchone()
    return book_out(book)


class TextBook(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    original_locale: str
    target_locale: str
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


@router.post("/text", status_code=201)
def create_text_book(body: TextBook, user: dict = Depends(auth.current_user)):
    """Pasted plain text, cleaned and structured like /import without a preview (kept for existing clients)."""
    try:
        doc = ingest_text(body.text, to_iso(body.original_locale))
    except IngestError as e:
        return _rejected(e)
    return _create_imported(user, body.title, body.original_locale, body.target_locale, doc)


class ImportSource(BaseModel):
    """Exactly one of text (plain paste), html (rich clipboard; `text` may accompany it) or url."""
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    html: str | None = Field(default=None, max_length=5 * MAX_TEXT_CHARS)
    url: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=40)  # ISO code or UI name; default: detected


class ImportCommit(ImportSource):
    title: str | None = Field(default=None, max_length=200)
    original_locale: str
    target_locale: str
    restore: list[str] = Field(default_factory=list, max_length=100000)  # block ids removed by default to keep
    remove: list[str] = Field(default_factory=list, max_length=100000)   # block ids kept by default to drop
    content_hash: str | None = None  # from the preview: refuses the commit if a URL changed meanwhile


def _ingest_source(body: ImportSource, language: str | None) -> tuple[Document, str]:
    if body.url:
        data, final_url = fetch(body.url.strip())
        return ingest_file(data, language, url=final_url), hashlib.sha256(data).hexdigest()
    if not (body.text or "").strip() and not (body.html or "").strip():
        raise IngestError("Nothing to import: paste some text or a link.")
    raw = (body.html or "") + "\x00" + (body.text or "")
    return ingest_text(body.text or "", language, html_text=body.html), hashlib.sha256(raw.encode()).hexdigest()


@router.post("/preview")
def preview_import(body: ImportSource, user: dict = Depends(auth.current_user)):
    """Clean and structure pasted text / HTML / a URL without saving anything. Every block is returned with
    `removed` = null (kept) or the reason it was dropped, so the client can let the user restore or remove it."""
    try:
        doc, digest = _ingest_source(body, to_iso(body.language) if body.language else None)
    except IngestError as e:
        return _rejected(e)
    units = build_units(doc)
    kept = [b for b in doc.blocks if b.readable]
    return {"title": doc.title, "author": doc.author, "language": doc.language,
            "language_detected": doc.language_detected, "language_confidence": round(doc.language_score, 3),
            "source_format": doc.source_format, "warnings": doc.warnings, "content_hash": digest,
            "size": {"chars": sum(len(b.text) for b in kept), "blocks": len(doc.blocks), "kept_blocks": len(kept),
                     "units": len(units)},
            "blocks": [b.to_json() for b in doc.blocks]}


@router.post("/import", status_code=201)
def commit_import(body: ImportCommit, user: dict = Depends(auth.current_user)):
    """Create a book from pasted text / HTML / a URL with the user's preview decisions applied."""
    language = to_iso(body.language) if body.language else to_iso(body.original_locale)
    try:
        doc, digest = _ingest_source(body, language)
        if body.url and body.content_hash and body.content_hash != digest:
            return JSONResponse({"detail": "The page changed since the preview; please preview it again.",
                                 "code": "content_changed"}, status_code=409)
        apply_overrides(doc, body.restore, body.remove, language)
    except IngestError as e:
        return _rejected(e)
    title = (body.title or doc.title or "Untitled").strip() or "Untitled"
    return _create_imported(user, title, body.original_locale, body.target_locale, doc)


@router.get("/{book_id}/ingest")
def ingest_report(book_id: UUID, user: dict = Depends(auth.current_user)):
    """Extraction report: detected language, warnings, what every level changed, removed-block counts."""
    owned_book(book_id, user)
    row = db.fetch_one("SELECT ingest, warnings FROM books WHERE id = %s", (book_id,))
    return {"warnings": row["warnings"], **(row["ingest"] or {})}


@router.get("/{book_id}")
def get_book(book_id: UUID, user: dict = Depends(auth.current_user)):
    return book_out(owned_book(book_id, user))


class BookPatch(BaseModel):
    last_read_page: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)


@router.patch("/{book_id}")
def update_book(book_id: UUID, body: BookPatch, user: dict = Depends(auth.current_user)):
    owned_book(book_id, user)
    changes = body.model_dump(exclude_none=True)
    if changes:
        sets = ", ".join(f"{k} = %s" for k in changes)
        db.execute(f"UPDATE books SET {sets} WHERE id = %s", (*changes.values(), book_id))
    return book_out(owned_book(book_id, user))


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: UUID, user: dict = Depends(auth.current_user)):
    book = owned_book(book_id, user)
    db.execute("DELETE FROM books WHERE id = %s", (book_id,))
    if book["source_format"] not in _IMPORTED:
        try:
            storage.delete(storage.book_file_key(user["id"], book_id, book["source_format"]))
        except Exception:
            pass
    try:  # the book's cached read-aloud audio (per-user artifacts must not outlive the book)
        tts.delete_audio(user["id"], str(book_id))
    except Exception:
        pass  # the tts/ lifecycle rule expires it anyway
    return Response(status_code=204)


@router.get("/{book_id}/pdf")
def get_pdf(book_id: UUID, user: dict = Depends(auth.current_user)):
    owned_book(book_id, user)
    data = storage.get(storage.book_pdf_key(user["id"], book_id))
    if data is None:
        raise HTTPException(404, "No PDF for this book")
    return Response(data, media_type="application/pdf", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{book_id}/pages")
def list_pages(
    book_id: UUID,
    numbers: str | None = Query(None, description="Comma-separated page numbers"),
    status: str | None = Query(None),
    user: dict = Depends(auth.current_user),
):
    owned_book(book_id, user)
    sql = f"SELECT {PAGE_FIELDS} FROM pages WHERE book_id = %s"
    params: list = [book_id]
    if numbers:
        try:
            nums = [int(n) for n in numbers.split(",") if n.strip()]
        except ValueError:
            raise HTTPException(400, "numbers must be comma-separated integers")
        sql += " AND page_number = ANY(%s)"
        params.append(nums)
    if status:
        sql += " AND status = %s"
        params.append(status)
    rows = db.fetch_all(sql + " ORDER BY page_number", params)
    return [page_out(r) for r in rows]


@router.get("/{book_id}/stats")
def book_stats(book_id: UUID, user: dict = Depends(auth.current_user)):
    book = owned_book(book_id, user)
    row = db.fetch_one(
        "SELECT count(*) FILTER (WHERE status = 'completed') AS translated FROM pages WHERE book_id = %s",
        (book_id,),
    )
    return {"translated": row["translated"], "total": book["total_pages"]}


@router.post("/{book_id}/reset-failed")
def reset_failed(book_id: UUID, user: dict = Depends(auth.current_user)):
    owned_book(book_id, user)
    n = db.execute("UPDATE pages SET status = 'pending' WHERE book_id = %s AND status = 'failed'", (book_id,))
    return {"reset": n}


@router.get("/{book_id}/search")
def search(book_id: UUID, q: str = Query(..., min_length=1), user: dict = Depends(auth.current_user)):
    owned_book(book_id, user)
    rows = db.fetch_all(
        "SELECT page_number, original_text FROM pages WHERE book_id = %s AND original_text ILIKE %s"
        " ORDER BY page_number",
        (book_id, "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"),
    )
    results = []
    needle = q.lower()
    for r in rows:
        text = r["original_text"]
        lower = text.lower()
        idx = lower.find(needle)
        if idx < 0:
            continue
        start, end = max(0, idx - 50), min(len(text), idx + len(q) + 50)
        snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
        results.append({"pageNumber": r["page_number"], "snippet": snippet, "matchCount": lower.count(needle)})
    return results


class ExportRequest(BaseModel):
    pageNumbers: list[int] = Field(min_length=1)
    format: str = "html"


@router.post("/{book_id}/export")
def export_book(book_id: UUID, body: ExportRequest, user: dict = Depends(auth.current_user)):
    book = owned_book(book_id, user)
    pages = db.fetch_all(
        "SELECT page_number, translated_data FROM pages WHERE book_id = %s AND page_number = ANY(%s)"
        " AND status = 'completed' ORDER BY page_number",
        (book_id, body.pageNumbers),
    )
    if not pages:
        raise HTTPException(404, "No translated pages found for export")
    nums = body.pageNumbers
    html = render_export(book, pages, nums)
    filename = f"{book['title']}-pages-{nums[0]}-{nums[-1]}.html".replace('"', "")
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
