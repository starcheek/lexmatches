"""Zip-bomb guard for zip-based uploads (EPUB, DOCX, ODT, zipped FB2/TXT).

zipfile never returns more than an entry's declared size (ZipExtFile stops at ZipInfo.file_size), so checking
the declared sizes before any parser runs bounds what mammoth / lxml / zipfile can inflate. The damaged-archive
fallback in formats/epub.py inflates with raw zlib and uses MAX_ENTRY / MAX_TOTAL itself.
"""
import io
import zipfile

from app.ingest.ir import IngestError

MAX_ENTRIES = 10_000
MAX_ENTRY = 100 * 1024 * 1024   # one file inside the archive (FB2 with embedded images can be large)
MAX_TOTAL = 300 * 1024 * 1024   # everything inside the archive
MAX_RATIO = 200                 # inflated / compressed, for entries over 1 MB (text compresses ~3-10x)


class ArchiveTooLarge(IngestError):
    code = "archive_too_large"
    status = 413


def check(data: bytes) -> None:
    try:
        infos = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except Exception:
        return  # not a readable central directory: the format parsers' own error handling applies
    if len(infos) > MAX_ENTRIES:
        raise ArchiveTooLarge("This archive contains too many files.")
    total = 0
    for i in infos:
        total += i.file_size
        if i.file_size > MAX_ENTRY or total > MAX_TOTAL:
            raise ArchiveTooLarge("This file unpacks to more data than is allowed.")
        if i.file_size > 1024 * 1024 and i.file_size > MAX_RATIO * max(i.compress_size, 1):
            raise ArchiveTooLarge("This file is compressed suspiciously well and was rejected.")
