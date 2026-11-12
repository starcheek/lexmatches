"""Book processing: stored file -> app.ingest -> reading units in `pages`.

Uploads run in the background (`process_book`, restart-safe: jobs.recover() re-queues books left pending/processing
and the units are replaced in one transaction). Pasted text and URL imports are small and call `store_document`
synchronously. The whole document is processed before any unit is written: the levels need document-wide
statistics (running headers, body font size, hyphenation vocabulary, language), and a 345-page PDF takes ~6 s.
"""
import logging
from collections import Counter

from app import db, storage
from app.ingest import Document, IngestError, build_units, ingest_file
from app.languages import to_iso

log = logging.getLogger(__name__)


def report(doc: Document, units) -> dict:
    removed = Counter(b.removed for b in doc.blocks if b.removed)
    return {"meta": doc.meta(), "audit": doc.audit.to_json(), "removed": dict(removed),
            "blocks": len(doc.blocks), "units": len(units)}


def store_document(book_id, doc: Document, conn=None) -> int:
    """Replace the book's pages with the document's reading units and mark the book completed. Returns unit count."""
    units = build_units(doc)
    rows = []
    for n, u in enumerate(units, start=1):
        start, end = u.source_pages
        rows.append((book_id, n, u.text, db.json([b.to_json() for b in u.blocks]), start, end, u.title))

    def write(c):
        c.execute("DELETE FROM pages WHERE book_id = %s", (book_id,))
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO pages (book_id, page_number, original_text, blocks, source_page_start, source_page_end,"
                " chapter_title, status) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')", rows)
        c.execute(
            "UPDATE books SET total_pages = %s, status = 'completed', error = NULL, source_format = %s,"
            " author = COALESCE(author, %s), detected_language = %s, warnings = %s, ingest = %s WHERE id = %s",
            (len(units), doc.source_format, doc.author, doc.language_detected, db.json(doc.warnings),
             db.json(report(doc, units)), book_id))

    if conn is not None:
        write(conn)
    else:
        with db.connection() as c:
            write(c)
    return len(units)


def create_uploaded_book(user_id, title: str, original_locale: str, target_locale: str, data: bytes, fmt: str) -> dict:
    """Store an uploaded (or sample) file as a `pending` book and split it into pages in the background."""
    from app import jobs
    from app.routers.common import BOOK_FIELDS

    book = db.fetch_one(
        f"INSERT INTO books (user_id, title, original_locale, target_locale, source, source_format, status)"
        f" VALUES (%s, %s, %s, %s, %s, %s, 'pending') RETURNING {BOOK_FIELDS}",
        (user_id, title.strip(), original_locale, target_locale, "pdf" if fmt == "pdf" else "text", fmt),
    )
    storage.put(storage.book_file_key(user_id, book["id"], fmt), data,
                "application/pdf" if fmt == "pdf" else "application/octet-stream")
    jobs.submit(f"book:{book['id']}", process_book, str(book["id"]))
    return book


def process_book(book_id: str) -> None:
    book = db.fetch_one("SELECT * FROM books WHERE id = %s", (book_id,))
    if book is None:
        return
    db.execute("UPDATE books SET status = 'processing', error = NULL WHERE id = %s", (book_id,))
    try:
        data = storage.get(storage.book_file_key(book["user_id"], book_id, book.get("source_format")))
        if data is None:
            raise IngestError("The uploaded file was not found in storage.")
        doc = ingest_file(data, to_iso(book["original_locale"]))
        n = store_document(book_id, doc)
        log.info("processed book %s (%s): %d units, %d blocks", book_id, doc.source_format, n, len(doc.blocks))
    except IngestError as e:
        log.info("book %s rejected: %s", book_id, e)
        db.execute("UPDATE books SET status = 'failed', error = %s WHERE id = %s", (str(e)[:1000], book_id))
    except Exception as e:
        log.exception("processing book %s failed", book_id)
        db.execute("UPDATE books SET status = 'failed', error = %s WHERE id = %s",
                   (f"Processing failed ({type(e).__name__}).", book_id))
