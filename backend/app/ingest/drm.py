"""L0 DRM detection: detect and reject with a clear message, never attempt removal.
Font obfuscation (IDPF / Adobe) in encryption.xml is NOT DRM and is accepted."""
from lxml import etree

from app.ingest.ir import DRMProtected

FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
FONT_EXT = (".otf", ".ttf", ".woff", ".woff2", ".pfb")
_XENC = "{http://www.w3.org/2001/04/xmlenc#}"


def check(kind: str, data: bytes) -> None:
    if kind == "kfx":
        raise DRMProtected("Kindle KFX/Topaz", "Amazon proprietary container")
    if kind == "mobi" and len(data) > 82:
        rec0 = int.from_bytes(data[78:82], "big")
        if rec0 + 14 <= len(data) and int.from_bytes(data[rec0 + 12:rec0 + 14], "big") in (1, 2):
            raise DRMProtected("Mobipocket/Kindle", "MOBI encryption flag set")
    if kind == "ole_doc" and "EncryptionInfo".encode("utf-16-le") in data[:200000]:
        raise DRMProtected("password-protected Office document", "EncryptionInfo stream")
    # EPUB: checked by formats.epub with its damage-tolerant zip reader (check_epub)


def check_epub(names: dict, read) -> list[str]:
    """names: {lowercase name: real name}; read(name) -> bytes. Returns notes (accepted font obfuscation)."""
    if "meta-inf/rights.xml" in names:
        raise DRMProtected("Adobe ADEPT", "META-INF/rights.xml present")
    if any(n.endswith("sinf.xml") for n in names):
        raise DRMProtected("Apple FairPlay", "sinf.xml present")
    if "meta-inf/license.lcpl" in names:
        raise DRMProtected("Readium LCP", "META-INF/license.lcpl present")
    notes = []
    if "meta-inf/encryption.xml" in names:
        raw = read(names["meta-inf/encryption.xml"]) or b""
        root = etree.fromstring(raw, etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
        encrypted = []
        for ed in (root.iter(f"{_XENC}EncryptedData") if root is not None else ()):
            m = ed.find(f"{_XENC}EncryptionMethod")
            ref = ed.find(f".//{_XENC}CipherReference")
            alg, uri = (m.get("Algorithm") if m is not None else ""), (ref.get("URI") if ref is not None else "")
            if alg in FONT_OBFUSCATION or uri.lower().endswith(FONT_EXT):
                notes.append(f"font obfuscation on {uri} (not DRM)")
            else:
                encrypted.append(uri)
        if encrypted:
            scheme = "Adobe ADEPT" if b"ns.adobe.com/adept" in raw else (
                "Readium LCP" if b"readium.org/lcp" in raw else "unknown encryption")
            raise DRMProtected(scheme, f"{len(encrypted)} encrypted resources, e.g. {encrypted[0]}")
    return notes
