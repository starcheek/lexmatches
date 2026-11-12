"""Plain text in all its forms: TXT/RTF files, pasted text, Markdown, Aozora Bunko notation.

Pasted text has no markup, so lines are classified (ported from the reflow lab, held-out kept-text token F1 0.93-0.95):
  hard-wrapped copy (PDF viewer): page numbers and running headers flagged, lines re-flowed + dehyphenated
  web page copy / prose: per-line chrome score (navigation words, datelines, bylines, credits, citations, repeated
  short lines, UI glyphs) vs prose score (length, terminal punctuation, function-word density) -> main region =
  maximum-sum segment; everything after a References / Comments / Related heading is flagged; [1] / [edit] removed.
Nothing is deleted: removed lines become blocks with `removed` = reason so the preview can show and restore them.
"""
from __future__ import annotations

import io
import re
import statistics
import zipfile
from collections import Counter

from app.ingest import langid
from app.ingest.ir import Block, Document
from app.ingest.levels import HEADING_RX, LEVEL1
from app.ingest.sniff import text_kind

FUNC = {
    "fr": "le la les de des du un une et en est que qui dans pour pas sur au aux il elle ne se ce son sa ses avec par "
          "plus mais ou nous vous ils on été être a cette leur y lui",
    "en": "the of and to in a is that for it as was with be by on not he she his her they at from this which or have "
          "an are were had but their its we you one all been has",
    "de": "der die das und in den von zu mit sich des auf für ist im dem nicht ein eine als auch es an er hat aus bei "
          "sie nach wird wie um sind noch werden über einer einem so zum zur",
    "ru": "и в не на что с по как он она это к а из то за от его но для так же у бы о ее её они был была было только "
          "все мы вы ты я когда уже",
    "pt": "o a os as de do da dos das e em um uma que para com não por se na no mais como mas foi ao ele ela seu sua "
          "são ou quando muito nos já está também",
    "lv": "un ir ar par uz no kas bet ka tas to kā lai arī vai jau ne tā viņš viņa bija pie pēc līdz tad šo šis savu "
          "tik var gan nav tiek",
}
FUNC = {k: set(v.split()) for k, v in FUNC.items()}
ALL_FUNC = set().union(*FUNC.values())
JA_PARTICLES = set("のはがをにでともへやかたしてだする")
NAV_VOCAB = set("""home|menu|search|log in|login|sign in|sign up|register|subscribe|newsletter|share|tweet|email|print|
cookie|cookies|accept|accept all|reject|privacy|terms|contact|about|advertise|advertisement|sponsored|related|read more|
read next|comments|comment|reply|leave a reply|previous|next|skip to content|skip to main content|toggle navigation|
donate|jump to|navigation|main menu|tools|edit|view history|talk|article|contents|hide|show|print/export|
download as pdf|printable version|languages|appearance|text|small|standard|large|width|wide|color|automatic|light|dark|
accueil|rechercher|se connecter|créer un compte|faire un don|partager|imprimer|modifier|modifier le code|
voir l’historique|voir l'historique|discussion|lire|sommaire|masquer|afficher|outils|apparence|commentaires|répondre|
lire aussi|à lire aussi|s'abonner|abonnez-vous|publicité|suivant|précédent|главная|поиск|войти|создать учётную запись|
пожертвовать|поделиться|печать|править|править код|история|обсуждение|читать|содержание|скрыть|показать|инструменты|
оформление|комментарии|ответить|подписаться|реклама|далее|назад|статья|startseite|suche|anmelden|
benutzerkonto erstellen|spenden|teilen|drucken|bearbeiten|quelltext bearbeiten|versionsgeschichte|diskussion|lesen|
inhalt|verbergen|anzeigen|werkzeuge|darstellung|kommentare|antworten|abonnieren|werbung|weiter|zurück|artikel|
página principal|pesquisar|entrar|criar uma conta|donativos|partilhar|compartilhar|imprimir|editar|
editar código-fonte|ver histórico|discussão|ler|conteúdo|esconder|ocultar|mostrar|ferramentas|aparência|comentários|
responder|assinar|publicidade|seguinte|anterior|sākumlapa|meklēt|pieteikties|izveidot kontu|ziedot|kopīgot|drukāt|
labot|labot pirmkodu|skatīt hronoloģiju|vēsture|diskusija|lasīt|saturs|paslēpt|rādīt|rīki|izskats|komentāri|atbildēt|
メインページ|検索|ログイン|アカウント作成|寄付|共有|印刷|編集|ソースを編集|履歴表示|ノート|閲覧|目次|非表示|表示|ツール|
言語|langues|языки|sprachen|línguas|valodas""".replace("\n", "").split("|"))
END_HEADINGS = re.compile(
    r"^\s*(notes?( et références)?|références|referências|references|notes and references|see also|voir aussi|"
    r"articles connexes|liens externes|external links|further reading|bibliograph\w*|sources?|примечания|литература|"
    r"ссылки|см\. также|источники|einzelnachweise|anmerkungen|literatur|weblinks|siehe auch|ver também|"
    r"ligações externas|notas|bibliografia|atsauces|skatīt arī|ārējās saites|literatūra|脚注|関連項目|外部リンク|"
    r"参考文献|注釈|出典|comments?|\d+ comments?|commentaires|комментарии|kommentare|comentários|komentāri|"
    r"leave a (reply|comment)|related( articles| posts)?|read more|lire aussi|à lire aussi|читайте также|"
    r"das könnte sie auch interessieren|leia também|vous aimerez aussi|you might also like|more from|most read|"
    r"articles les plus lus|les plus lus|самое читаемое|meistgelesen|mais lidas|lasītākie|a propos de nous|about us|"
    r"über uns|sobre nós|о нас|par mums|recevoir par e-mail.*|рекомендуем|empfehlungen|recomendados)\s*(\[.*\])?\s*:?\s*$",
    re.I)
DATELINE = re.compile(r"^\s*((publié|mis à jour|published|updated|posted|veröffentlicht|aktualisiert|publicado|"
                      r"atualizado|опубликовано|обновлено|publicēts)\b.{0,40}|il y a \d+ \w+|\d+ (minutes?|hours?|days?|"
                      r"weeks?|months?) ago|vor \d+ \w+|há \d+ \w+|\d+ (минут\w*|час\w*|дн\w*|недел\w*) назад|"
                      r"pirms \d+ \w+|\d+\s*(min|minutes?) (read|de lecture|lesezeit|de leitura)|"
                      r"lecture\s*:\s*\d+ min)\s*$", re.I)
BYLINE = re.compile(r"^\s*(par|by|von|por|автор|écrit par|traduit par|written by|translated by|übersetzt von|"
                    r"traduzido por|перевод|autors|tulkojis)\s*:?\s+[^.!?]{2,80}$", re.I)
LICENCE_FOOTER = re.compile(r"(creative[- ]commons|cc by(-sa|-nd|-nc)?|licence 3\.0|last edited on|"
                            r"dernière modification de cette page|zuletzt am .* bearbeitet|editada pela última vez|"
                            r"последнее изменение этой страницы|pēdējo reizi labota|最終更新|all rights reserved|"
                            r"tous droits réservés|alle rechte vorbehalten|todos os direitos reservados|"
                            r"все права защищены)", re.I)
BUTTON = re.compile(r"^.{1,40}\s[»›→]\s*$|^[«‹←]\s.{1,40}$")
CREDIT = re.compile(r"(^|\s)(photo|foto|фото|image|illustration|crédit|credit|©|source ?:|getty|reuters|afp|"
                    r"associated press|wikimedia commons|used with permission|cc[ -]by|licen[cs]e|скриншот|"
                    r"screenshot|screen ?shot|capture d’écran|caption|légende)", re.I)
CITATION = re.compile(r"(abgerufen am|retrieved|consulté le|archived from|archiviert|memento|isbn|issn|doi:|"
                      r"\(pdf[;,)]|проверено|дата обращения|acesso em|consultado em|skatīts|アクセス日|\bpp?\. \d|"
                      r"\bS\. \d+)", re.I)
TERMINAL = re.compile(r"[.!?…»”\"')\]:;。！？」』]\s*$")
UI_GLYPH = re.compile(r"^[\W\d_]{1,6}$|^\d+:\d{2}$|[♁⊙▶►◀▲▼☰✕×⋮…]\s*$")
_REMOVE_REASONS = ("navigation", "table_row", "citation", "ui_glyph_or_number", "repeated_short_line",
                   "caption_credit", "dateline", "byline", "licence_footer", "button")


def func_density(words: list[str], lang: str | None) -> float:
    if not words or lang == "ja":
        return 0.0
    fw = FUNC.get(lang or "", ALL_FUNC)
    return sum(1 for w in words if w.lower() in fw) / len(words)


def _removed(text: str, reason: str, role: str = "boilerplate") -> Block:
    b = Block("paragraph", text.strip(), confidence=0.5)
    b.remove(reason, role)
    return b


# ------------------------------------------------------------------------------------------------ reflow
def reflow(lines: list[str], lang: str | None) -> list[str]:
    """Join hard-wrapped lines into paragraphs; dehyphenate; detect paragraph ends without blank lines."""
    nonblank = [ln for ln in lines if ln.strip()]
    if not nonblank:
        return []
    width = sorted(len(ln.rstrip()) for ln in nonblank)[int(len(nonblank) * 0.8)]
    vocab = Counter(w.lower() for ln in nonblank for w in re.findall(r"\w+", ln))
    blank_delimited = (len(lines) - len(nonblank)) / max(1, len(lines)) > 0.08
    paras: list[list[str]] = []
    cur: list[str] = []

    def flush():
        if cur:
            paras.append(cur[:])
            cur.clear()
    for k, raw in enumerate(lines):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flush()
            continue
        indent = len(raw) - len(raw.lstrip(" 　\t"))
        if cur and (indent >= 2 or (re.match(r"^\s*([—–\-«»„“\"]|―)\s*\S", line) and TERMINAL.search(cur[-1]))):
            flush()
        if HEADING_RX.match(s) or (s.isupper() and 2 < len(s) < 60 and not TERMINAL.search(s)):
            flush()
            paras.append([s])
            continue
        nxt = lines[k + 1] if k + 1 < len(lines) else ""
        if not blank_delimited and not cur and len(line) < 0.6 * width and not TERMINAL.search(line) \
                and not line.endswith(("-", "‐", ",")) and nxt[:1].isupper():
            paras.append([s])  # standalone short line (heading / label) in unbroken text
            continue
        cur.append(s)
        if not blank_delimited and len(line) < 0.72 * width and TERMINAL.search(line):
            flush()  # short line ending a sentence = paragraph end
    flush()
    out = []
    for p in paras:
        text = p[0]
        for nxt in p[1:]:
            m = re.search(r"(\w+)[\-‐­]$", text)
            if m and nxt[:1].islower():
                right = re.match(r"\w+", nxt)
                joined, hyph = (m.group(1) + (right.group(0) if right else "")).lower(), \
                    f"{m.group(1)}-{right.group(0) if right else ''}".lower()
                text = text[:-1] + nxt if text.endswith(("‐", "­")) or vocab[joined] >= vocab[hyph] else text + nxt
            elif text.endswith("-") and nxt[:1].isupper():
                text += nxt  # German compound continuation: Bäcker-\nInnung
            else:
                text += ("" if lang in ("ja", "zh") else " ") + nxt
        out.append(text)
    return out


def _para_block(p: str, verse_ok: bool) -> Block:
    if HEADING_RX.match(p) or (p.isupper() and 2 < len(p) < 70 and "\n" not in p):
        return Block("heading", p.strip(), level=1 if LEVEL1.match(p) else 2, confidence=0.8)
    if verse_ok and "\n" in p and all(len(x) < 70 for x in p.split("\n")):
        return Block("verse", p)
    return Block("paragraph", re.sub(r"\s*\n\s*", " ", p).strip())


def _plain(text: str, doc: Document, lang: str | None) -> None:
    """TXT / RTF files: header fields, hard-wrap detection, paragraphs."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    for key, rx in (("title", r"(?im)^\s*(title|titre|titel|título|название)\s*:\s*(.+)$"),
                    ("author", r"(?im)^\s*(author|auteur|autor|автор)\s*:\s*(.+)$"),
                    ("language", r"(?im)^\s*(language|langue|sprache)\s*:\s*(.+)$")):
        m = re.search(rx, raw[:6000])
        if m and not getattr(doc, key):
            setattr(doc, key, m.group(2).strip())
    lines = raw.split("\n")
    nonblank = [ln for ln in lines if ln.strip()]
    blank_ratio = 1 - len(nonblank) / max(1, len(lines))
    lens = sorted(len(ln) for ln in nonblank) or [0]
    chunks = re.split(r"\n\s*\n", raw)
    multi = sum(1 for c in chunks if c.count("\n") >= 2) / max(1, len(chunks))
    hard_wrapped = lens[int(len(lens) * 0.8)] < 100 and (multi > 0.3 or blank_ratio < 0.05)
    if hard_wrapped:
        paras = reflow(lines, lang)
        doc.audit.add("L3", "hard_wrapped_reflowed", len(paras))
    else:
        paras = []
        for c in chunks:
            c = c.strip("\n")
            if c.strip():
                cl = c.split("\n")
                paras.extend(x.strip() for x in cl if x.strip()) if len(cl) > 1 and blank_ratio < 0.05 \
                    else paras.append(c.strip())
    doc.blocks = [_para_block(p, verse_ok=not hard_wrapped) for p in paras]


# ------------------------------------------------------------------------------------------------ paste
TIMESTAMP_CHAT = re.compile(r"^\s*\[?\d{1,2}:\d{2}(:\d{2})?\]?\s*([^:]{1,30}):\s*")
QUOTE_LINE = re.compile(r"^\s*>")
ATTRIB = re.compile(r"(wrote|a écrit|написал\(?а?\)?|schrieb|escreveu|rakstīja|のメッセージ)\s*:?\s*$", re.I)
SIGNOFF = re.compile(r"^(--\s*$|sent from my|envoyé de mon|отправлено с|gesendet von|enviado do|cordialement|bien à vous|"
                     r"best( regards)?,?$|regards,?$|cheers,?$|с уважением|mit freundlichen grüßen|atenciosamente|"
                     r"ar cieņu)", re.I)
GREETING = re.compile(r"^(bonjour|salut|hello|hi|dear|привет|здравствуйте|hallo|liebe[rs]?|olá|oi|sveiki|labdien|"
                      r"こんにちは)\b[^.!?]{0,40}[,!]?\s*$", re.I)
CLOSING = re.compile(r"^(bonne lecture|merci|thanks|спасибо|danke|obrigad[oa]|paldies)\b.{0,30}$", re.I)


def _genre(lines: list[str]) -> str:
    nonblank = [ln for ln in lines if ln.strip()]
    if not nonblank:
        return "web_or_prose"
    if sum(1 for ln in nonblank if TIMESTAMP_CHAT.match(ln)) / len(nonblank) > 0.5:
        return "chat"
    if sum(1 for ln in nonblank if QUOTE_LINE.match(ln)) / len(nonblank) > 0.05 or \
            any(ATTRIB.search(ln) for ln in nonblank[:40]) or any(SIGNOFF.match(ln.strip()) for ln in nonblank[-8:]):
        return "email"
    lens = [len(ln) for ln in nonblank if len(ln) > 20]
    if len(lens) >= 8:
        med = statistics.median(lens)
        near = sum(1 for x in lens if abs(x - med) < 0.2 * med) / len(lens)
        no_term = sum(1 for ln in nonblank if not TERMINAL.search(ln)) / len(nonblank)
        if near > 0.55 and med < 110 and no_term > 0.5:
            return "hardwrapped"
    return "web_or_prose"


def _score(t: str, lang: str | None, counts: Counter) -> tuple[float, str | None]:
    low = t.lower().rstrip(":").strip()
    words = re.findall(r"\w+", t)
    nw = len(words) if lang != "ja" else max(1, len(t) // 2)
    if low in NAV_VOCAB or (len(low) < 40 and re.sub(r"[\W\d]+", " ", low).strip() in NAV_VOCAB):
        return -3, "navigation"
    if "\t" in t:
        return -2, "table_row"
    if DATELINE.match(t):
        return -3, "dateline"
    if BYLINE.match(t) and nw <= 12:
        return -2, "byline"
    if LICENCE_FOOTER.search(t) and len(t) < 500:
        return -3, "licence_footer"
    if BUTTON.match(t) and nw <= 6:
        return -2.5, "button"
    if CITATION.search(t) and (not TERMINAL.search(t[:-1]) or (nw < 40 and t.count(".") >= 2 and re.search(r"\d{4}", t))):
        return -2, "citation"
    if UI_GLYPH.search(t) and nw <= 3:
        return -2, "ui_glyph_or_number"
    if counts[t] >= 3 and nw <= 8:
        return -2, "repeated_short_line"
    if CREDIT.search(t) and nw <= 25 and not (nw > 12 and TERMINAL.search(t) and func_density(words, lang) > 0.2):
        return -1.5, "caption_credit"
    term = bool(TERMINAL.search(t))
    if lang == "ja":
        chars = [c for c in t if not c.isspace()]
        fd = 1.5 * sum(1 for c in chars if c in JA_PARTICLES) / max(1, len(chars))
        s = min(len(t) / 40.0, 3.0) * (0.6 + fd * 2.0)
    else:
        fd = func_density(words, lang)
        s = min(nw / 12.0, 3.0) * (0.6 + fd * 2.0)
    s += 0.8 if term else -0.4
    reason = None
    if nw <= 4 and not term:
        s -= 1.0
        reason = "short_label"
    if fd < 0.05 and nw > 3 and lang != "ja":
        s -= 0.8
    if re.match(r"^[\-•*·▪◦–—]\s", t) and nw < 6:
        s -= 0.5
    return s, reason


def _max_segment(scores: list[float]) -> tuple[int, int]:
    best, cur, start, bs, be = float("-inf"), 0.0, 0, 0, -1
    for i, s in enumerate(scores):
        cur, start = (s, i) if cur <= 0 else (cur + s, start)
        if cur > best:
            best, bs, be = cur, start, i
    return bs, be


def _paste(text: str, doc: Document, lang: str | None) -> None:
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").split("\n")
    counts = Counter(ln.strip() for ln in raw_lines if ln.strip())
    out = doc.blocks
    genre = _genre(raw_lines)
    if genre == "chat":  # "[12:01] Anna: text" - keep messages with substance, drop prefixes and chatter
        for ln in raw_lines:
            m = TIMESTAMP_CHAT.match(ln)
            body = (ln[m.end():] if m else ln).strip()
            if not body:
                continue
            if QUOTE_LINE.match(body) or len(re.findall(r"\w+", body)) < 8:
                out.append(_removed(ln, "chat_chatter"))
            else:
                out.append(Block("paragraph", body, confidence=0.8))
        doc.extractor = "paste heuristics (chat)"
        return
    if genre == "email":  # greeting, quoted replies, attribution lines, sign-off and signature are flagged
        keep, signature = [], False
        for i, ln in enumerate(raw_lines):
            s = ln.strip()
            reason = None
            if signature or SIGNOFF.match(s):
                signature, reason = True, "email_signature"
            elif QUOTE_LINE.match(ln):
                reason = "email_quote"
            elif ATTRIB.search(s):
                reason = "email_attribution"
            elif (GREETING.match(s) and i < 5) or CLOSING.match(s):
                reason = "email_greeting"
            if reason and s:
                out.append(_removed(s, reason))
            elif not reason:
                keep.append(ln)
        for p in re.split(r"\n\s*\n", "\n".join(keep)):
            if p.strip():
                out.append(Block("paragraph", re.sub(r"\s*\n\s*", " ", p.strip()), confidence=0.8))
        doc.extractor = "paste heuristics (email)"
        return
    if genre == "hardwrapped":
        keep = []
        for ln in raw_lines:
            t = ln.strip()
            if re.fullmatch(r"[-–—]?\s*\d{1,4}\s*[-–—]?", t):
                out.append(_removed(t, "page_number"))
                keep.append("")
            elif t and counts[t] >= 3 and len(t) < 80:
                out.append(_removed(t, "running_header"))
                keep.append("")
            else:
                keep.append(ln)
        merged = []  # a page break inside a paragraph: drop the blank when the previous line did not end a sentence
        for t in keep:
            if not t.strip() and merged and merged[-1].strip() and not TERMINAL.search(merged[-1]):
                continue
            merged.append(t)
        for p in reflow(merged, lang):
            b = _para_block(p, verse_ok=False)
            b.confidence = 0.75
            out.append(b)
        doc.extractor = "paste heuristics (hard-wrapped)"
        doc.audit.add("L3", "hard_wrapped_reflowed")
        return
    content = [ln.strip() for ln in raw_lines if ln.strip()]
    if not content:
        return
    blank_before = {}
    prev_blank = True
    k = 0
    for ln in raw_lines:
        if ln.strip():
            blank_before[k] = prev_blank
            k += 1
        prev_blank = not ln.strip()
    scored = [_score(t, lang, counts) for t in content]
    bs, be = _max_segment([s for s, _ in scored])
    while bs > 0 and scored[bs - 1][0] > 0.8:
        bs -= 1
    while be < len(content) - 1 and scored[be + 1][0] > 0.8:
        be += 1
    end_cut = next((k for k in range(bs + 3, be + 1) if END_HEADINGS.match(content[k])), None)
    for k, t in enumerate(content):
        score, reason = scored[k]
        inside = bs <= k <= be and (end_cut is None or k < end_cut)
        if not inside:
            if not (score >= 3.0 and k < bs and reason is None):
                after = end_cut is not None and k >= end_cut
                out.append(_removed(t, reason if reason not in (None, "short_label") else
                                    ("after_article_end" if after else "outside_main_text"),
                                    "back_matter" if after else "boilerplate"))
                continue
        elif score < -1 or reason in _REMOVE_REASONS:
            out.append(_removed(t, reason or "low_score"))
            continue
        words = re.findall(r"\w+", t)
        heading = len(words) <= 10 and not TERMINAL.search(t) and (blank_before.get(k) or HEADING_RX.match(t)) \
            and not t.startswith(("-", "•", "*")) and not (len(words) >= 4 and t.endswith("."))
        if heading:
            out.append(Block("heading", t, level=2, confidence=0.6 if k + 1 < len(content) and scored[k + 1][0] > 1.5
                             else 0.45))
        elif re.match(r"^[\-•*·▪◦]\s+", t):
            out.append(Block("list_item", re.sub(r"^[\-•*·▪◦]\s+", "", t), confidence=0.7))
        else:
            out.append(Block("paragraph", t, confidence=round(min(0.95, 0.5 + score / 8), 2)))
    title = _infer_title(content[:max(1, bs + 3)], out, lang)
    if title:
        doc.title = title
        b = next((x for x in out if x.text == title), None)
        if b is not None and b.removed:  # the page title above the article: restore it as its heading
            out.remove(b)
            b.removed, b.role, b.type, b.level = None, "body", "heading", 1
            out.insert(next((i for i, x in enumerate(out) if x.readable), len(out)), b)
    doc.extractor = "paste heuristics (line classifier)"


def _infer_title(head: list[str], blocks: list[Block], lang: str | None) -> str | None:
    """Short line before/at the main region whose words are frequent in the kept text (titles repeat the topic)."""
    freq = Counter(re.findall(r"\w+", " ".join(b.text for b in blocks if b.readable).lower()))
    counts = Counter(head)
    best, best_s = None, 0.0
    for t in head:
        words = re.findall(r"\w+", t.lower())
        if not (1 <= len(words) <= 14) or (TERMINAL.search(t) and not t.endswith(")")) or t.lower() in NAV_VOCAB:
            continue
        content = [w for w in words if len(w) > 3 or lang == "ja"]
        if content:
            s = sum(min(freq[w], 30) for w in content) / len(content) * (1.5 if counts[t] >= 2 else 1.0) \
                * (1 + 0.25 * min(len(content), 6))
            if s > best_s:
                best, best_s = t, s
    return best


# ------------------------------------------------------------------------------------------------ markdown / aozora
def _markdown(text: str, doc: Document) -> None:
    from markdown_it import MarkdownIt
    from mdit_py_plugins.footnote import footnote_plugin

    from app.ingest.formats.html import html_to_blocks, noteref_targets, parse_html
    m = re.match(r"---\s*\n((?:.*\n)*?)---\s*\n", text)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip().lower(), v.strip().strip("'\"")
            if k in ("title", "author") and v:
                setattr(doc, k, v)
            elif k in ("lang", "language") and v:
                doc.language = v
        text = text[m.end():]
    html = MarkdownIt("commonmark", {"html": True}).enable("table").use(footnote_plugin).render(text)
    root = parse_html("<html><body>" + html + "</body></html>")
    for li in root.iter("li"):
        if (li.get("id") or "").startswith("fn"):
            li.set("class", "footnote")
            for a in list(li.iter("a")):
                if "footnote-backref" in (a.get("class") or ""):
                    a.drop_tree()
    doc.blocks, _, refs = html_to_blocks(root, noteref_targets(root))
    doc.audit.add("L0", "noteref_markers_dropped", refs)
    doc.extractor = "markdown-it-py -> lxml html walker"


_AOZ_RUBY = re.compile(r"｜([^《｜]+)《[^》]+》|([㐀-鿿豈-﫿々〆ヶ※]+)《[^》]+》")  # ※ = gaiji placeholder
_AOZ_NOTE = re.compile(r"［＃[^］]*］")
_AOZ_HEAD = re.compile(r"［＃「([^」]+)」は(大|中|小)見出し］")


def _aozora(text: str, doc: Document) -> None:
    """Aozora Bunko notation: ruby readings 《》 removed, annotations ［＃…］ removed, legend and colophon flagged."""
    lines = text.replace("\r\n", "\n").split("\n")
    doc.title = lines[0].strip() if lines else None
    doc.author = lines[1].strip() if len(lines) > 1 else None
    doc.language = "ja"
    section = "body"
    for line in lines[2:]:
        s = line.rstrip()
        if re.match(r"^-{20,}$", s):
            section = "legend" if section != "legend" else "body"
            continue
        if s.startswith(("底本：", "底本:")):
            section = "colophon"
        t = _AOZ_RUBY.sub(lambda m: m.group(1) or m.group(2), _AOZ_NOTE.sub("", s)).strip("　 ").strip()
        if not t:
            continue
        if section != "body":
            doc.blocks.append(_removed(t, "aozora_notation_legend" if section == "legend" else "aozora_colophon",
                                       "front_matter" if section == "legend" else "back_matter"))
        elif _AOZ_HEAD.search(s) or (len(t) <= 12 and re.fullmatch(r"[一二三四五六七八九十百〇０-９0-9]+|第.+[章話回節]", t)):
            doc.blocks.append(Block("heading", t, level=2))
        else:
            doc.blocks.append(Block("paragraph", t))
    doc.extractor = "aozora notation parser"


def unzip_text(data: bytes) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(data))
    return z.read(next(n for n in z.namelist() if n.lower().endswith(".txt")))


def parse_text(text: str, declared: str | None, source_format: str) -> Document:
    """source_format: txt | rtf | paste."""
    doc = Document([], source_format, "text reflow")
    kind = text_kind(text)
    if kind == "aozora":
        _aozora(text, doc)
        return doc
    if kind == "markdown" and source_format != "paste" or (kind == "markdown" and text.lstrip().startswith(("#", "---"))):
        doc.source_format = "markdown" if source_format != "paste" else source_format
        _markdown(text, doc)
        return doc
    lang = declared or langid.detect(text[:5000])[0]
    if source_format == "paste":
        _paste(text, doc, lang)
    else:
        _plain(text, doc, lang)
    return doc
