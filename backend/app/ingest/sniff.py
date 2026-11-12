"""L0 format detection from content (never from the file name)."""
import io
import re
import zipfile

_HTML = re.compile(rb"<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]|<meta\s|<div[\s>]|<p[\s>]", re.I)


def zip_names(data: bytes) -> list[str]:
    try:
        return zipfile.ZipFile(io.BytesIO(data)).namelist()
    except Exception:  # damaged archive: names from the local file headers
        names = []
        for m in re.finditer(rb"PK\x03\x04", data):
            i = m.start()
            if i + 30 > len(data):
                break
            n = int.from_bytes(data[i + 26:i + 28], "little")
            names.append(data[i + 30:i + 30 + n].decode("utf-8", "replace"))
        return names


def sniff(data: bytes) -> str:
    """pdf | epub | odt | docx | fb2 | fb2zip | txtzip | mobi | kfx | ole_doc | rtf | html | text | unknown_zip"""
    head = data[:4096]
    if head[:1024].lstrip().startswith(b"%PDF") or b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        if b"mimetypeapplication/epub+zip" in head[:200]:
            return "epub"
        if b"application/vnd.oasis.opendocument.text" in head[:200]:
            return "odt"
        low = [n.lower() for n in zip_names(data)]
        if "meta-inf/container.xml" in low or any(n.endswith(".opf") for n in low):
            return "epub"
        if "word/document.xml" in low:
            return "docx"
        if "content.xml" in low and "mimetype" in low:
            return "odt"
        if any(n.endswith(".fb2") for n in low):
            return "fb2zip"
        if low and all(n.endswith((".txt", ".png", ".jpg", "/")) for n in low) and any(n.endswith(".txt") for n in low):
            return "txtzip"  # e.g. Aozora Bunko text + ruby zip
        return "unknown_zip"
    if len(data) > 68 and data[60:68] in (b"BOOKMOBI", b"TEXtREAd"):
        return "mobi"
    if head.startswith(b"TPZ") or b"\xeaDRMION\xee" in head[:16]:
        return "kfx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole_doc"  # legacy .doc or a password-protected Office file
    if head.lstrip().startswith(b"{\\rtf"):
        return "rtf"
    if b"<FictionBook" in head:
        return "fb2"
    stripped = head.lstrip(b"\xef\xbb\xbf \r\n\t")
    if _HTML.search(head) and stripped.startswith(b"<"):
        return "html"
    return "text"  # plain text / Markdown / Aozora / HTML fragment: refined after decoding


def looks_like_html(text: str) -> bool:
    s = text.lstrip()[:20000]
    return s.startswith("<") and len(re.findall(r"</(p|div|h[1-6]|li|span|a|td|section|article|body)>", s, re.I)) >= 3


def text_kind(text: str) -> str:
    """markdown | aozora | plain"""
    sample = text[:20000]
    if sample.count("《") >= 3 and "》" in sample and ("［＃" in sample or "｜" in sample or "底本" in text[-3000:]):
        return "aozora"
    md = 0
    if re.match(r"---\s*\n(\w[\w-]*:.*\n)+---\s*\n", sample):
        md += 2
    md += min(3, len(re.findall(r"(?m)^#{1,6} \S", sample)))
    md += min(2, len(re.findall(r"\[[^\]]+\]\([^)\s]+\)", sample)))
    md += min(2, len(re.findall(r"(?m)^```", sample)))
    md += min(1, len(re.findall(r"\*\*[^*\n]+\*\*", sample)))
    md += min(1, len(re.findall(r"(?m)^\[\^?\w+\]:", sample)))
    return "markdown" if md >= 3 else "plain"
