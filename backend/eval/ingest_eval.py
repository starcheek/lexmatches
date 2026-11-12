"""Ingestion evaluation over the lab corpora (mounted read-only), compared with the labs' own numbers.

    docker run --rm -v "$PWD/backend:/app" -v /root/lexmatches-lab:/root/lexmatches-lab:ro -w /app \\
        lexmatches-api python -m eval.ingest_eval [pdf|reflow|sentences|all] [--docs a,b]

pdf        corpus/pdf-digital (+ gt/): CER, WER, paragraph-start F1, heading recall, header leaks, OCR routing,
           against the PDF lab's PyMuPDF-based pipeline (bench/results.json, tool pipe_final). "generated" =
           typeset by the lab itself (exact GT, heuristics tuned on them); "real" = real-world PDFs (approximate GT).
reflow     corpus/reflow: kept-text token P/R/F1 vs gold (web captures, pastes, ebooks vs PG text) and paragraph-
           boundary F1 on the re-flow cases, against reflow/results/regression.csv and paragraph_eval.csv.
sentences  both labs' hand-segmented sentence sets.
"""
import csv
import json
import os
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import IngestError, ingest_file, ingest_text  # noqa: E402
from app.ingest.encoding import decode  # noqa: E402
from tests.ingest_metrics import boundary_f1, heading_recall, leaks, para_f1, text_scores, token_f1  # noqa: E402

LAB = Path(os.environ.get("LAB_DIR", "/root/lexmatches-lab"))
PDF_CORPUS = LAB / "corpus/pdf-digital"
REFLOW = LAB / "corpus/reflow"


def body_blocks(doc):
    return [b for b in doc.blocks if b.readable and b.type != "footnote"]


def fmt(x, nd=3):
    return "–" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


# ------------------------------------------------------------------------------------------------ PDF
def _score_blocks(blocks, gb, m, lang):
    """blocks: [(type, text)] of the body -> metrics against GT body blocks gb."""
    hyp = "\n\n".join(t for _, t in blocks)
    r = text_scores(hyp, "\n\n".join(b["text"] for b in gb), lang, m.get("eval_anchors"))
    r["para_f1"] = para_f1([t for _, t in blocks], [b["text"] for b in gb], lang)
    r["head"] = heading_recall([t for ty, t in blocks if ty == "heading"],
                               [b["text"] for b in gb if b["type"] == "heading"], lang)
    r["leak"] = leaks(hyp, m.get("artifacts"), lang)
    return r


def eval_pdf(only=None):
    """Lab numbers are recomputed here from the lab's stored block output (bench/out/pipe_final/*.json) with the
    same metric code: the lab's own results.json scored its .txt dumps, which is not comparable."""
    man = json.loads((PDF_CORPUS / "manifest.json").read_text())["items"]
    raw = {}
    rp = LAB / "pdf-digital/bench/results.json"
    if rp.exists():
        raw = {r["doc"]: r for r in json.loads(rp.read_text()) if r["tool"] == "pymupdf_text"}
    rows = []
    for m in man:
        stem = m["file"][:-4]
        gtp = PDF_CORPUS / "gt" / f"{stem}.json"
        if (only and stem not in only) or not gtp.exists() or m.get("perf_only"):
            continue
        lang = m["language"]
        t0 = time.perf_counter()
        try:
            doc = ingest_file((PDF_CORPUS / m["file"]).read_bytes(), lang)
            err = None
        except IngestError as e:
            doc, err = None, f"{e.code}: {e}"
        sec = time.perf_counter() - t0
        g = json.loads(gtp.read_text())
        gb = [b for b in g["blocks"] if b["type"] not in ("footnote", "toc", "boilerplate")]
        r = {"doc": stem, "real": bool(m.get("ground_truth_approx")), "pages": m["pages"], "sec": sec, "error": err}
        if doc is not None:
            r.update(_score_blocks([(b.type, b.text) for b in body_blocks(doc)], gb, m, lang))
            r["ocr"] = doc.route_to_ocr or bool(doc.ocr_pages)
        else:
            r["ocr"] = err is not None and "scanned" in err
        out = LAB / "pdf-digital/bench/out/pipe_final" / f"{stem}.json"
        if out.exists():
            ir = json.loads(out.read_text())
            lb = [(b["type"], b["text"]) for b in ir["blocks"] if b.get("role", "body") == "body" and b["type"] != "footnote"]
            L = _score_blocks(lb, gb, m, lang)
            r.update(lab_cer=L["cer"], lab_para=L["para_f1"], lab_head=L["head"], lab_leak=L["leak"],
                     lab_ocr=ir["meta"].get("route_to_ocr"))
        else:
            r.update(lab_cer=None, lab_para=None, lab_head=None, lab_leak=None, lab_ocr=None)
        r["raw_cer"] = raw.get(stem, {}).get("cer")
        rows.append(r)
    print("\n### PDF (app pipeline on pypdfium2 vs PDF lab pipeline on PyMuPDF)\n")
    print("| doc | set | pages | CER app | CER lab | CER raw PyMuPDF | WER app | para-F1 app | para-F1 lab | "
          "head app | head lab | leaks app | leaks lab | OCR app | OCR lab | s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (r["real"], r["doc"])):
        print(f"| {r['doc']} | {'real' if r['real'] else 'generated'} | {r['pages']} | {fmt(r.get('cer'))} | "
              f"{fmt(r['lab_cer'])} | {fmt(r['raw_cer'])} | {fmt(r.get('wer'))} | {fmt(r.get('para_f1'), 2)} | "
              f"{fmt(r['lab_para'], 2)} | {fmt(r.get('head'), 2)} | {fmt(r['lab_head'], 2)} | {fmt(r.get('leak'))} | "
              f"{fmt(r['lab_leak'])} | {r['ocr']} | {r['lab_ocr']} | {r['sec']:.1f} |" +
              (f" {r['error']}" if r["error"] else ""))
    for real in (False, True):
        sub = [r for r in rows if r["real"] == real and r.get("cer") is not None and r["doc"] != "fr_broken_tounicode"]
        if sub:
            mean = lambda k: sum(r[k] for r in sub if r.get(k) is not None) / max(1, sum(1 for r in sub if r.get(k) is not None))  # noqa: E731
            print(f"| **mean {'real' if real else 'generated'}** (n={len(sub)}) | | | {mean('cer'):.3f} | "
                  f"{mean('lab_cer'):.3f} | {mean('raw_cer'):.3f} | | {mean('para_f1'):.2f} | {mean('lab_para'):.2f} | "
                  f"| | {sum(r.get('leak') or 0 for r in sub)} | {sum(r.get('lab_leak') or 0 for r in sub)} | | |")
    return rows


# ------------------------------------------------------------------------------------------------ reflow
PG_REF = {"fr_candide": "gutenberg/fr_candide.txt", "de_verwandlung": "gutenberg/de_verwandlung.txt",
          "en_les_miserables_big": "gutenberg/en_les_miserables_big.txt"}


def _pg_body(p: Path) -> str:
    t = p.read_text(encoding="utf-8-sig")
    s, e = re.search(r"\*\*\* ?START OF.*\n", t), re.search(r"\*\*\* ?END OF", t)
    return t[s.end():e.start()] if s and e else t


def _run_item(it):
    path = REFLOW / it["file"]
    data = path.read_bytes()
    if it["kind"] == "paste_text" or (it["kind"] == "web" and it["file"].endswith(".txt")):
        return ingest_text(decode(data)[0])
    if it["kind"] == "web" and it["file"].endswith((".html")):
        if it["file"].endswith(("ctrl_a.html", "selection.html")):
            return ingest_text("", html_text=data.decode("utf-8"))  # rich clipboard paste
        meta = json.loads((path.parent / "meta.json").read_text())
        return ingest_file(data, url=meta["url"])  # the URL path without network: captured body + its URL
    return ingest_file(data)


def eval_reflow(only=None):
    man = json.loads((REFLOW / "manifest.json").read_text())["items"]
    lab = {}
    rp = LAB / "reflow/results/regression.csv"
    if rp.exists():
        with open(rp) as f:
            lab = {r["file"]: r for r in csv.DictReader(f)}
    rows = []
    for it in man:
        f = it["file"]
        if f.endswith(("dom.html", "selection.html", "reader.txt")) or (only and not any(o in f for o in only)):
            continue
        gold = None
        if it.get("ground_truth"):
            gold = (REFLOW / it["ground_truth"]).read_text(encoding="utf-8")
        else:
            for k, p in PG_REF.items():
                if os.path.basename(f).startswith(k) and not f.endswith(".txt") and "bad_" not in f:
                    gold = _pg_body(REFLOW / p)
            if f.startswith("derived/bad_") or f.startswith("derived/drm_false"):
                gold = _pg_body(REFLOW / PG_REF["fr_candide"])
        t0 = time.perf_counter()
        r = {"file": f, "kind": it["kind"], "lang": it["language"]}
        try:
            doc = _run_item(it)
            r.update(ok=True, fmt=doc.source_format, det=doc.language_detected, kept=sum(b.readable for b in doc.blocks))
            if gold is not None:
                main = "\n".join(b.text for b in doc.blocks if b.readable and b.type != "footnote")
                r["P"], r["R"], r["F1"] = token_f1(main, gold)
        except IngestError as e:
            r.update(ok=False, error=f"{e.code}")
        except Exception as e:  # noqa: BLE001 - report, keep going
            r.update(ok=False, error=f"CRASH {type(e).__name__}: {str(e)[:80]}")
        r["sec"] = time.perf_counter() - t0
        L = lab.get(f, {})
        r["lab_F1"] = float(L["F1"]) if L.get("F1") else None
        r["lab_error"] = L.get("error") or ""
        rows.append(r)
    print("\n### Reflow / web / paste (kept-text token F1 vs gold; app vs reflow lab)\n")
    print("| file | kind | lang | detected | P | R | F1 app | F1 lab | error app | error lab | s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['file']} | {r['kind']} | {r['lang']} | {r.get('det') or '–'} | {fmt(r.get('P'))} | {fmt(r.get('R'))} "
              f"| {fmt(r.get('F1'))} | {fmt(r['lab_F1'])} | {r.get('error', '')} | {r['lab_error']} | {r['sec']:.2f} |")
    groups = {}
    for r in rows:
        if r.get("F1") is not None:
            key = ("heldout:" if "/ho_" in r["file"] else "") + (r["file"].rsplit("/", 1)[-1] if r["kind"] == "web" else r["kind"])
            groups.setdefault(key, []).append(r)
    print("\n| group | n | mean F1 app | mean F1 lab |\n|---|---|---|---|")
    for k, rs in sorted(groups.items()):
        labs = [r["lab_F1"] for r in rs if r["lab_F1"] is not None]
        print(f"| {k} | {len(rs)} | {sum(r['F1'] for r in rs) / len(rs):.3f} | "
              f"{(sum(labs) / len(labs)) if labs else float('nan'):.3f} |")
    _paragraphs()
    return rows


PARA_ITEMS = [("derived/de_verwandlung_hardwrap_noblank.txt", "derived/de_verwandlung.gold.txt", "file"),
              ("gutenberg/de_verwandlung.txt", "derived/de_verwandlung.gold.txt", "file"),
              ("derived/de_verwandlung_oneline_paras.txt", "derived/de_verwandlung.gold.txt", "file"),
              ("derived/ru_dama_librustyle.cp1251.txt", "derived/ru_dama.gold.txt", "file"),
              ("derived/ws_fr_mousquetaires_pdfviewer_copy.txt", "gold/ws_fr_mousquetaires.txt", "paste"),
              ("derived/wp_de_brezel_pdfviewer_copy.txt", "gold/wp_de_brezel.txt", "paste"),
              ("derived/ws_ru_dama_pdfviewer_copy.txt", "gold/ws_ru_dama.txt", "paste")]


def _paragraphs():
    lab = {}
    rp = LAB / "reflow/results/paragraph_eval.csv"
    if rp.exists():
        with open(rp) as f:
            lab = {r["file"]: r for r in csv.DictReader(f) if r["cond"] == "full"}
    print("\n| re-flow case | paragraph-boundary F1 app | lab | broken hyphenated words app |\n|---|---|---|---|")
    for f, g, mode in PARA_ITEMS:
        gold = [ln for ln in (REFLOW / g).read_text().split("\n") if ln.strip()]
        raw = (REFLOW / f).read_bytes()
        doc = ingest_text(decode(raw)[0]) if mode == "paste" else ingest_file(raw)
        paras = [b.text for b in doc.blocks if b.readable]
        broken = sum(len(re.findall(r"\w[\-‐­]\s+[a-zà-ÿа-яё]", p)) for p in paras)
        print(f"| {f} | {boundary_f1(paras, gold):.3f} | {lab.get(f, {}).get('F1', '–')} | {broken} |")


# ------------------------------------------------------------------------------------------------ sentences
def eval_sentences():
    import importlib.util
    from app.ingest.sentences import segment
    spec = importlib.util.spec_from_file_location("sg", LAB / "reflow/scripts/sent_gold.py")
    sg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sg)
    sets = {"pdf lab": [(lang, t, e) for lang, cases in
                        json.loads((LAB / "pdf-digital/tests/data/sentences.json").read_text()).items() for t, e in cases],
            "reflow lab": [(lang, ("" if lang == "ja" else " ").join(s), s) for lang, items in sg.GOLD.items() for s in items]}
    print("\n| sentence set | exact paragraphs |\n|---|---|")
    for name, cases in sets.items():
        ok = sum([text[a:b].strip() for a, b in segment(text, lang)] == exp for lang, text, exp in cases)
        print(f"| {name} | {ok}/{len(cases)} |")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = set(sys.argv[sys.argv.index("--docs") + 1].split(",")) if "--docs" in sys.argv else None
    what = args[0] if args else "all"
    if what in ("pdf", "all"):
        eval_pdf(only)
    if what in ("reflow", "all"):
        eval_reflow(only)
    if what in ("sentences", "all"):
        eval_sentences()
