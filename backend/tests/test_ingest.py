"""Ingestion quality regression tests (app/ingest), metric-based. Thresholds sit a little below the measured values
(docs/ARCHITECTURE.md#ingestion has the full table; eval/ingest_eval.py reproduces it on the lab corpora).
Fixtures: tests/fixtures/ingest (sources and licences in SOURCES.txt)."""
import io
import json
import re
import zipfile
from pathlib import Path

import httpx
import pytest

from app.ingest import (DRMProtected, IngestError, NoText, UnsupportedFormat, URLBlocked, apply_overrides,
                        build_units, fetch, ingest_file, ingest_text, ocr)
from app.ingest.encoding import decode
from app.ingest.ir import Block, Document
from app.ingest.sentences import segment
from app.ingest.units import SPLIT, unit_sentences
from tests.helpers import make_pdf
from tests.ingest_metrics import boundary_f1, heading_recall, leaks, para_f1, text_scores, token_f1

FIX = Path(__file__).parent / "fixtures" / "ingest"
PDF_CASES = json.loads((FIX / "pdf" / "cases.json").read_text(encoding="utf-8"))


def body(doc):
    return [b for b in doc.blocks if b.readable and b.type != "footnote"]


def kept_text(doc):
    return "\n".join(b.text for b in doc.blocks if b.readable and b.type != "footnote")


def read(name):
    return (FIX / "reflow" / name).read_bytes()


# ------------------------------------------------------------------------------------------------ PDF
# doc: (max CER, min paragraph-start F1, min heading recall)   measured: see ARCHITECTURE.md
PDF_THRESHOLDS = {
    "fr_verne_novel": (0.005, 0.90, 0.85),
    "de_kafka_frontmatter": (0.005, 0.95, 0.95),
    "ru_chekhov_stories": (0.005, 0.95, 0.95),
    "pt_camoes_verse": (0.005, 0.95, 0.95),
    "lv_lacplesis_docx": (0.015, 0.88, 0.95),   # a 2-column cast table is read column-wise (tables are out of scope)
    "en_twocol_article": (0.005, 0.90, 0.95),
    "ja_rashomon_vertical": (0.02, 0.88, 0.95),
}


@pytest.mark.parametrize("stem", sorted(PDF_THRESHOLDS))
def test_pdf_quality(stem):
    case = PDF_CASES[stem]
    lang = case["language"]
    doc = ingest_file((FIX / "pdf" / f"{stem}.pdf").read_bytes(), lang)
    gt = [b for b in json.loads((FIX / "pdf" / f"{stem}.gt.json").read_text(encoding="utf-8"))["blocks"]
          if b["type"] not in ("footnote", "toc", "boilerplate")]
    hyp = "\n\n".join(b.text for b in body(doc))
    max_cer, min_para, min_head = PDF_THRESHOLDS[stem]
    assert text_scores(hyp, "\n\n".join(b["text"] for b in gt), lang, case["eval_anchors"])["cer"] <= max_cer
    assert para_f1([b.text for b in body(doc)], [b["text"] for b in gt], lang) >= min_para
    assert heading_recall([b.text for b in body(doc) if b.type == "heading"],
                          [b["text"] for b in gt if b["type"] == "heading"], lang) >= min_head
    assert leaks(hyp, case["artifacts"], lang) <= (2 if stem == "de_kafka_frontmatter" else 1)  # name in the text
    assert not doc.ocr_pages


def test_pdf_levels_audit_and_structure():
    doc = ingest_file((FIX / "pdf" / "fr_verne_novel.pdf").read_bytes(), "fr")
    c = doc.audit.counts
    assert c["L2"]["remove_pagenum"] >= 15 and c["L2"]["remove_header"] >= 5  # running heads / folios
    assert c["L2"]["footnote_lines"] >= 3 and sum(v for k, v in c["L3"].items() if k.startswith("dehyphen")) > 50
    assert any(b.type == "footnote" for b in doc.blocks)
    assert any(b.role == "toc" and b.removed == "toc" for b in doc.blocks)  # TOC kept, flagged, not read
    assert "extrêmement" in kept_text(doc) and "ex-trêmement" not in kept_text(doc)  # automatic hyphenation
    assert "cinquante-cinq" in kept_text(doc)  # a real compound split at a line end keeps its hyphen


def test_pdf_original_fixtures():
    hyph = ingest_file((FIX / "pdf" / "fr_hyphenated.pdf").read_bytes(), "fr")
    assert not re.search(r"\w[-‐] [a-zà-ÿ]", kept_text(hyph))  # no broken words left
    two = ingest_file((FIX / "pdf" / "fr_two_column.pdf").read_bytes(), "fr")
    assert any(w["code"] == "multi_column" for w in two.warnings)
    assert kept_text(two).startswith("En 1815, M. Charles-François-Bienvenu Myriel était évêque de Digne.")
    notes = ingest_file((FIX / "pdf" / "fr_structured_footnotes.pdf").read_bytes(), "fr")
    types = [b.type for b in notes.blocks]
    assert types.count("footnote") >= 2 and types.count("list_item") >= 8 and types[0] == "heading"
    assert "¹" not in kept_text(notes).replace("\n", "")[:200]
    prose = ingest_file((FIX / "pdf" / "fr_clean_prose.pdf").read_bytes(), "fr")
    units = build_units(prose)
    assert units[0].title == "Le Tour du monde en quatre-vingts jours" and len(units) >= 3
    assert all(len(u.text) <= 1900 for u in units)


def test_pdf_broken_text_layer_routes_to_ocr():
    with pytest.raises(NoText, match="scanned"):
        ingest_file((FIX / "pdf" / "fr_broken_tounicode.pdf").read_bytes(), "fr")


def test_partially_scanned_pdf_warns_and_drops_those_pages():
    pdf = make_pdf(["Le chat est sur la table. Il mange une pomme.", "", "Le chien dort sous la table ce soir."],
                   image_only=(1,))
    doc = ingest_file(pdf, "fr")
    assert doc.ocr_pages == [2]
    w = next(w for w in doc.warnings if w["code"] == "scanned_pages")
    assert "pages 2" in w["message"] and w["pages"] == [2]
    assert "Le chien dort" in kept_text(doc)


def test_ocr_hook_splices_blocks_by_source_page(monkeypatch):
    calls = []

    def fake_ocr(pdf_bytes, pages, language):
        calls.append((pages, language))
        return {p: [Block("paragraph", f"Texte reconnu de la page {p}.", source_page=p)] for p in pages}
    monkeypatch.setattr(ocr, "ocr_pages", fake_ocr)
    pdf = make_pdf(["Première page de texte.", "", "Troisième page de texte."], image_only=(1,))
    doc = ingest_file(pdf, "fr")
    assert calls == [([2], "fr")]
    assert [b.text for b in body(doc)] == ["Première page de texte.", "Texte reconnu de la page 2.",
                                           "Troisième page de texte."]
    assert all(b.sentences for b in body(doc))  # OCR output goes through L6 like everything else


# ------------------------------------------------------------------------------------------------ EPUB / DRM
def _rezip(data: bytes, drop=(), add=None, mimetype_first=True) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            if info.filename not in drop:
                z.writestr(info, src.read(info.filename))
        for name, content in (add or {}).items():
            z.writestr(name, content)
    return out.getvalue()


@pytest.fixture(scope="module")
def candide():
    return read("fr_candide.epub")


@pytest.fixture(scope="module")
def candide_doc(candide):
    return ingest_file(candide)


def test_epub_structure(candide_doc):
    doc = candide_doc
    assert doc.source_format == "epub" and doc.language == "fr" and "Candide" in (doc.title or "")
    text = kept_text(doc)
    assert "Project Gutenberg" not in text  # licence header/footer flagged, not read
    assert any(b.removed == "gutenberg_licence" for b in doc.blocks)
    toc = [b for b in doc.blocks if b.type == "table"]  # the book's own contents <table>: kept, flagged, not read
    assert len(toc) == 1 and toc[0].removed == "toc" and "CHAPITRE II" in toc[0].text
    units = build_units(doc)
    titles = {u.title for u in units}
    assert len(units) >= 30 and sum(1 for t in titles if t and t.startswith("CHAPITRE")) >= 25
    assert all(len(u.text) <= 3600 for u in units)


def test_toc_table_flagged_data_table_kept():
    from app.ingest.levels import flag_boilerplate
    para = "Le chat dort sur la table pendant que la pluie tombe sur la ville."
    chapters = ["Chapitre I. Le départ", "Chapitre II. La tempête", "Chapitre III. Le retour"]
    rows = Block("table", "\n".join(f"{c} | {i + 3}" for i, c in enumerate(chapters)))   # no "Contents" heading
    data = Block("table", "Souper | 3 francs\nChambre | 10 francs\nChandelle | 5 francs")
    after_heading = Block("table", "I | Du titre\nII | Du livre\nIII | La dénonciation\n" + "IV | Un devoir | 9\n" * 10)
    doc = Document([rows] + [x for c in chapters for x in (Block("heading", c, level=2), Block("paragraph", para))]
                   + [data, Block("paragraph", para), Block("heading", "Table des matières", level=2), after_heading],
                   "epub", "test")
    flag_boilerplate(doc)
    assert (rows.removed, rows.role) == ("toc", "toc") and (after_heading.removed, after_heading.role) == ("toc", "toc")
    assert data.readable and sum(b.readable for b in doc.blocks) == 8
    assert doc.audit.counts["L2"] == {"toc_table": 1, "toc_heading": 1, "toc_entry": 1}


@pytest.mark.parametrize("damage", ["truncated", "bad_eocd", "no_container"])
def test_damaged_epub_tolerated(candide, candide_doc, damage):
    if damage == "truncated":
        data = candide[: int(len(candide) * 0.6)]
    elif damage == "bad_eocd":
        i = candide.rfind(b"PK\x05\x06")
        data = candide[:i] + b"XX\x05\x06" + candide[i + 4:]
    else:
        data = _rezip(candide, drop=("META-INF/container.xml",))
    doc = ingest_file(data)
    P, R, F = token_f1(kept_text(doc), kept_text(candide_doc))
    assert P > 0.99 and R > (0.3 if damage == "truncated" else 0.97)
    if damage != "no_container":
        assert any(w["code"] == "damaged_file" for w in doc.warnings)


@pytest.mark.parametrize("extra,scheme", [
    ({"META-INF/rights.xml": "<rights/>"}, "Adobe ADEPT"),
    ({"META-INF/license.lcpl": "{}"}, "Readium LCP"),
    ({"META-INF/sinf.xml": "<sinf/>"}, "Apple FairPlay"),
    ({"META-INF/encryption.xml": '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
      'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData><enc:EncryptionMethod '
      'Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/><enc:CipherData><enc:CipherReference '
      'URI="OEBPS/chapter1.xhtml"/></enc:CipherData></enc:EncryptedData></encryption>'}, "unknown encryption"),
])
def test_drm_rejected(candide, extra, scheme):
    from app.ingest.pipeline import precheck
    data = _rezip(candide, add=extra)
    with pytest.raises(DRMProtected) as e:
        precheck(data)
    assert e.value.scheme == scheme and "DRM" in str(e.value)
    with pytest.raises(DRMProtected):
        ingest_file(data)


def test_font_obfuscation_is_not_drm(candide):
    enc = ('<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
           'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData><enc:EncryptionMethod '
           'Algorithm="http://www.idpf.org/2008/embedding"/><enc:CipherData><enc:CipherReference '
           'URI="OEBPS/fonts/a.otf"/></enc:CipherData></enc:EncryptedData></encryption>')
    assert ingest_file(_rezip(candide, add={"META-INF/encryption.xml": enc})).source_format == "epub"


def _mobi(encryption: int) -> bytes:
    data = bytearray(400)
    data[60:68] = b"BOOKMOBI"
    data[78:82] = (100).to_bytes(4, "big")  # record 0 offset
    data[112:114] = encryption.to_bytes(2, "big")
    return bytes(data)


def test_mobi_rejected_with_typed_errors():
    with pytest.raises(DRMProtected):
        ingest_file(_mobi(2))
    with pytest.raises(UnsupportedFormat, match="EPUB"):
        ingest_file(_mobi(0))
    with pytest.raises(UnsupportedFormat):
        ingest_file(b"\x89PNG\r\n\x1a\n" + bytes(100))


# ------------------------------------------------------------------------------------------------ other formats
def test_fb2_and_cp1251_txt_vs_gold():
    gold = read("ru_dama.gold.txt").decode("utf-8")
    fb2 = ingest_file(read("ru_dama_handbuilt.fb2"))
    assert fb2.source_format == "fb2" and token_f1(kept_text(fb2), gold)[2] > 0.99
    txt = ingest_file(read("ru_dama_librustyle.cp1251.txt"))
    assert txt.language == "ru" and token_f1(kept_text(txt), gold)[2] > 0.99
    assert any(w["code"] == "encoding_guessed" and "cp1251" in w["message"] for w in txt.warnings)


def test_mojibake_repaired():
    doc = ingest_file(read("fr_candide_excerpt.mojibake.txt"))
    assert token_f1(kept_text(doc), read("fr_candide_excerpt.gold.txt").decode("utf-8"))[2] > 0.99
    assert doc.audit.counts["L1"]["mojibake_repaired"] > 0


@pytest.mark.parametrize("text,enc,lang", [
    ("Lāčplēsis, Lielvārdes kuniga dēls, saplēš lāci. Viņš devās uz Burtnieku pili, kur dzīvoja Laimdota, "
     "un tur viņam bija jācīnās ar raganu Spīdolu un ar vāciešiem.", "cp1257", "lv"),
    ("Дмитрий Дмитрич Гуров, проживший в Ялте уже две недели и привыкший тут, тоже стал интересоваться "
     "новыми лицами.", "koi8-r", "ru"),
    ("Il y avait en Westphalie, dans le château de M. le baron de Thunder-ten-tronckh, un jeune garçon "
     "à qui la nature avait donné les mœurs les plus douces.", "cp1252", "fr"),
])
def test_legacy_encodings_at_paste_size(text, enc, lang):
    decoded, rep = decode(text.encode(enc))
    assert decoded == text and rep["method"] == "decode+langid"
    doc = ingest_file(text.encode(enc))
    assert doc.language == lang


def test_aozora_zip_ruby_and_colophon():
    doc = ingest_file(read("ja_rashomon_ruby.zip"))
    text = kept_text(doc)
    assert doc.language == "ja" and "羅生門" in (doc.title or "") and len(text) > 5000
    assert "《" not in text and "［＃" not in text
    assert any(b.removed == "aozora_colophon" for b in doc.blocks)


def test_markdown_docx_odt_rtf():
    md = ingest_file(read("fr_horla_frontmatter.md"))
    assert md.source_format == "markdown" and md.title and md.blocks[0].type in ("heading", "paragraph")
    docx = ingest_file(read("fr_user_notes.docx"))
    assert docx.source_format == "docx" and any(b.type == "heading" for b in docx.blocks)
    odt = io.BytesIO()
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
                   '<text:h text:outline-level="1">Chapitre premier</text:h><text:p>Le chat dort sur la table.'
                   '<text:note><text:note-body><text:p>Une note.</text:p></text:note-body></text:note> Il fait beau.'
                   '</text:p></office:text></office:body></office:document-content>')
    doc = ingest_file(odt.getvalue())
    assert [(b.type, b.text) for b in doc.blocks] == [
        ("heading", "Chapitre premier"), ("paragraph", "Le chat dort sur la table. Il fait beau."), ("footnote", "Une note.")]
    rtf = rb"{\rtf1\ansi\ansicpg1252 {\fonttbl\f0 Times;}\f0 Le ch\'e2teau \'e9tait vide.\par Il pleuvait sur la ville.\par}"
    doc = ingest_file(rtf, "fr")
    assert doc.source_format == "rtf" and "château était vide." in kept_text(doc)


# ------------------------------------------------------------------------------------------------ web / paste
def test_web_page_main_content():
    doc = ingest_file(read("news_ru_globalvoices.html"), url="https://ru.globalvoices.org/2026/11/10/131471/")
    P, R, F = token_f1(kept_text(doc), read("news_ru_globalvoices.gold.txt").decode("utf-8"))
    assert F > 0.98 and doc.source_format == "url"
    assert any(b.removed == "web_chrome" for b in doc.blocks)  # navigation kept in the IR, flagged


def test_paste_web_copy_plain_and_rich():
    gold = read("wp_fr_baguette.gold.txt").decode("utf-8")
    plain = ingest_text(read("wp_fr_baguette_ctrl_a.txt").decode("utf-8"))
    assert token_f1(kept_text(plain), gold)[2] > 0.95 and plain.title and "Baguette" in plain.title
    removed = {b.removed for b in plain.blocks if b.removed}
    assert removed & {"navigation", "outside_main_text", "after_article_end"}
    rich = ingest_text("", html_text=read("wp_fr_baguette_ctrl_a.html").decode("utf-8"))
    assert token_f1(kept_text(rich), gold)[2] > 0.97 and rich.source_format == "paste_html"


@pytest.mark.parametrize("name", ["fr_email_paste", "ru_chat_paste"])
def test_paste_email_and_chat(name):
    doc = ingest_text(read(f"{name}.txt").decode("utf-8"))
    assert token_f1(kept_text(doc), read(f"{name}.gold.txt").decode("utf-8"))[2] > 0.95


def test_paste_pdf_viewer_copy_reflowed():
    doc = ingest_text(read("ws_fr_mousquetaires_pdfviewer_copy.txt").decode("utf-8"))
    gold = [x for x in read("ws_fr_mousquetaires.gold.txt").decode("utf-8").split("\n") if x.strip()]
    paras = [b.text for b in doc.blocks if b.readable]
    assert boundary_f1(paras, gold) > 0.9 and token_f1("\n".join(paras), "\n".join(gold))[2] > 0.99
    assert any(b.removed in ("page_number", "running_header") for b in doc.blocks)


def test_paste_overrides_and_limits():
    doc = ingest_text("Accueil\nRechercher\n\nLe chat dort sur la table depuis le matin. Il fait beau et chaud.\n"
                      "Partager\n")
    removed = [b for b in doc.blocks if b.removed]
    kept = [b for b in doc.blocks if b.readable]
    assert removed and kept
    apply_overrides(doc, restore=[removed[0].id], remove=[kept[0].id], language="de")
    assert removed[0].readable and not kept[0].readable and doc.language == "de"
    with pytest.raises(NoText):
        apply_overrides(doc, remove=[b.id for b in doc.blocks])
    with pytest.raises(IngestError, match="too long"):
        ingest_text("x" * 1_000_001)


# ------------------------------------------------------------------------------------------------ sentences
def test_sentence_segmenter_on_both_lab_sets():
    sets = json.loads((FIX / "sentences.json").read_text(encoding="utf-8"))
    for name, cases in sets.items():
        ok = sum([t[a:b].strip() for a, b in segment(t, lang)] == exp for lang, t, exp in cases)
        assert ok / len(cases) >= 0.9, (name, ok, len(cases))


# ------------------------------------------------------------------------------------------------ units
def _doc(blocks) -> Document:
    from app.ingest.sentences import segment_block
    d = Document(blocks, "txt", "test", language="fr")
    for b in d.blocks:
        b.sentences = segment_block(b.text, b.type, "fr")
    d.renumber()
    return d


def test_units_rules():
    sent = "Le chat dort sur la table pendant que la pluie tombe sur la ville endormie. "
    long_para = sent * 60  # ~4500 chars
    verse = "\n".join(["Sous le pont Mirabeau coule la Seine et nos amours"] * 80)  # ~4000 chars, never split
    lic = Block("paragraph", "Licence text " * 50)
    lic.remove("gutenberg_licence", "boilerplate")
    blocks = [Block("heading", "Titre", level=1), Block("paragraph", sent * 10), Block("heading", "Section", level=3),
              Block("paragraph", sent * 20), Block("heading", "Chapitre deux", level=2), Block("paragraph", long_para),
              Block("verse", verse), lic]
    units = build_units(_doc(blocks))
    texts = [u.text for u in units]
    assert units[0].title == "Titre" and units[0].blocks[0].text == "Titre"
    assert all(not u.blocks[-1].readable or u.blocks[-1].type != "heading" for u in units)  # no orphan heading
    assert any(u.title == "Chapitre deux" and u.blocks[0].text == "Chapitre deux" for u in units)
    pieces = [b for u in units for b in u.blocks if b.id.startswith("b6")]
    assert len(pieces) >= 3 and all(len(b.text) <= 1800 for b in pieces) and len(long_para) > SPLIT
    assert all(p.text.rstrip().endswith(".") for p in pieces)  # cut at sentence boundaries
    assert sum(1 for t in texts if verse in t) == 1  # the stanza stays whole
    assert units[-1].blocks[-1] is lic  # removed blocks stay where they occur, not read
    sents = unit_sentences([b.to_json() for b in units[0].blocks])
    assert sents[0] == (0, "Titre", "b1") and {p for p, _, _ in sents} == {0, 1, 2, 3}


def test_verse_sentences_are_lines():
    d = _doc([Block("verse", "Mignonne, allons voir si la rose\nQui ce matin avait déclose")])
    assert unit_sentences([b.to_json() for b in d.blocks]) == [
        (0, "Mignonne, allons voir si la rose", "b1"), (0, "Qui ce matin avait déclose", "b1")]


# ------------------------------------------------------------------------------------------------ SSRF
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/", "http://10.1.2.3/x",
                                 "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
                                 "http://192.168.0.10/", "http://100.64.0.1/", "ftp://example.org/x",
                                 "file:///etc/passwd", "http://example.org:22/", "http://user:pw@example.org/"])
def test_ssrf_blocked(url):
    with pytest.raises(URLBlocked):
        fetch.fetch(url)


def test_ssrf_dns_and_redirect(monkeypatch):
    answers = {"public.example": "93.184.216.34", "evil.example": "10.0.0.5"}
    monkeypatch.setattr(fetch, "_resolve", lambda host, port: [answers[host]])
    with pytest.raises(URLBlocked):  # name resolving to a private address
        fetch.fetch("http://evil.example/page")
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.host, request.headers["host"]))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://evil.example/secret"})
        if request.url.path == "/big":
            return httpx.Response(200, content=b"x" * (fetch.MAX_BYTES + 1))
        return httpx.Response(200, content=b"<html><body><p>Bonjour</p></body></html>")
    monkeypatch.setattr(fetch, "_transport", httpx.MockTransport(handler))
    with pytest.raises(URLBlocked):  # redirect into the private network is refused before connecting
        fetch.fetch("http://public.example/start")
    assert seen == [("93.184.216.34", "public.example")]  # connected to the vetted IP with the original Host
    with pytest.raises(IngestError, match="too large"):
        fetch.fetch("http://public.example/big")
    body, final = fetch.fetch("http://public.example/ok")
    assert body.startswith(b"<html>") and final == "http://public.example/ok"
