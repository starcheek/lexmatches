"""L0 bytes -> str. Order: BOM > ISO-2022-JP escapes > strict UTF-8 > declared charset (validated) >
decode with every plausible legacy codec and score each decoding with language-ID confidence minus a penalty for
unlikely characters (works at paste size, where statistical detectors alone fail) > Cyrillic tie-break."""
import codecs
import re

from charset_normalizer import from_bytes

from app.ingest import langid

_ALIASES = {"iso-8859-1": "cp1252", "latin-1": "cp1252", "latin1": "cp1252", "us-ascii": "cp1252", "ascii": "cp1252",
            "shift_jis": "cp932", "shift-jis": "cp932", "sjis": "cp932", "x-sjis": "cp932", "windows-31j": "cp932",
            "windows-1251": "cp1251", "windows-1252": "cp1252", "windows-1257": "cp1257", "euc-jp": "euc_jp",
            "x-mac-cyrillic": "mac_cyrillic", "koi8_r": "koi8-r"}
_META = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w:.-]+)""", re.I)
_XML = re.compile(rb"""<\?xml[^>]+encoding\s*=\s*["']([\w:.-]+)["']""", re.I)
_C1 = re.compile("[\x80-\x9f]")
CANDIDATES = ["cp1252", "cp1250", "cp1257", "iso8859-13", "cp1251", "koi8-r", "cp866", "iso8859-5", "cp932", "euc_jp",
              "mac_roman"]
_CYRILLIC = ("cp1251", "koi8-r", "cp866", "iso8859-5")
_BALTIC_CE = ("lv", "lt", "et", "pl", "cs", "sk", "hu", "ro", "hr", "sl", "tr")


def _norm(name: str | None) -> str | None:
    if not name:
        return None
    n = _ALIASES.get(name.lower().strip(), name.lower().strip())
    if n == "cp932":
        return n
    try:
        return codecs.lookup(n).name
    except LookupError:
        return None


def declared_charset(data: bytes, http_header: str | None = None) -> str | None:
    if http_header:
        m = re.search(r"charset=([\w:.-]+)", http_header, re.I)
        if m:
            return m.group(1)
    for rx in (_XML, _META):
        m = rx.search(data[:4096])
        if m:
            return m.group(1).decode("ascii", "ignore")
    return None


def decode(data: bytes, http_header: str | None = None) -> tuple[str, dict]:
    rep = {"method": None, "encoding": None}
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"), (codecs.BOM_UTF8, "utf-8-sig"),
                     (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            rep.update(method="bom", encoding=enc)
            return data.decode(enc, "replace"), rep
    if b"\x1b$B" in data[:20000] or b"\x1b$@" in data[:20000]:
        rep.update(method="escape-sequence", encoding="iso2022_jp")
        return data.decode("iso2022_jp", "replace"), rep
    try:
        text = data.decode("utf-8")
        rep.update(method="utf8-strict", encoding="utf-8")
        return text, rep
    except UnicodeDecodeError:
        pass
    declared = _norm(declared_charset(data, http_header))
    if declared and declared != "utf-8":
        text = data.decode(declared, "replace")
        if (len(_C1.findall(text)) + text.count("�")) / max(1, len(text)) < 0.001:
            rep.update(method="declared", encoding=declared)
            return text, rep
    enc = detect_legacy(data[:200000])
    rep.update(method="decode+langid", encoding=enc)
    return data.decode(enc, "replace"), rep


def _cyrillic_tiebreak(data: bytes) -> str:
    """cp1251 vs koi8-r vs cp866: natural text is mostly lower case with capitals after sentence ends."""
    best, best_score = "cp1251", float("-inf")
    for enc in _CYRILLIC:
        t = data.decode(enc, "replace")
        lower = sum(1 for c in t if "а" <= c <= "я" or c == "ё")
        upper = sum(1 for c in t if "А" <= c <= "Я" or c == "Ё")
        vowels = sum(t.count(v) for v in "оеаи")
        odd = sum(1 for c in t if ord(c) > 127 and not ("Ѐ" <= c <= "ӿ") and c not in "«»—–…„“”’№")
        caps = len(re.findall(r"[.!?]\s+[А-ЯЁ]", t))
        score = lower + vowels - 3 * max(0, upper - 3 * caps - len(t) // 200) - 5 * odd
        if score > best_score:
            best, best_score = enc, score
    return best


def detect_legacy(data: bytes) -> str:
    guess = from_bytes(data).best()
    cn = _norm(guess.encoding) if guess else None
    if cn in ("shift_jis", "shift_jis_2004", "shift_jisx0213"):
        cn = "cp932"
    sample = data[:6000]
    best, best_score = None, float("-inf")
    for enc in dict.fromkeys(([cn] if cn else []) + CANDIDATES):
        try:
            t = sample.decode(enc)
        except (UnicodeDecodeError, LookupError):
            try:
                t = sample[:-4].decode(enc)  # a multi-byte character cut at the sample end is fine
            except Exception:
                continue
        lang, score = langid.detect(t)
        odd = sum(1 for c in t if "\x80" <= c <= "\x9f" or "─" <= c <= "◿")
        if lang not in _BALTIC_CE:
            odd += sum(1 for c in t if "Ā" <= c <= "ſ" and c not in "œŒ")
        if lang not in ("ja", "zh", "ko"):
            odd += sum(1 for c in t if "　" <= c <= "鿿")
        score -= 20 * odd / max(1, len(t))
        if enc == cn:
            score += 0.05 if cn in CANDIDATES else -0.05
        if score > best_score:
            best, best_score = enc, score
    if best is None:
        return "cp1252"
    return _cyrillic_tiebreak(data) if best in _CYRILLIC else best
