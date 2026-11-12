"""Extraction metrics shared by tests/test_ingest*.py and eval/ingest_eval.py (same definitions as the labs).

  cer / wer        edit distance after evaluation normalisation (quotes, dashes, whitespace; NOT ligatures,
                   soft hyphens or broken hyphenation: those are what the levels must fix)
  para_f1          paragraph-start F1 (PDF lab): a GT paragraph is found if a block starts with the same ~30 chars
  boundary_f1      paragraph-boundary F1 over the aligned token stream (reflow lab para_eval)
  heading_recall   GT headings found among output headings
  token_f1         bag-of-tokens P/R/F1 of kept text vs gold (reflow lab; character tokens for Japanese)
  leaks            occurrences of known running-header strings in the output
"""
import difflib
import re
import unicodedata
from collections import Counter

from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

_Q1 = dict.fromkeys(map(ord, "‘’‚‛′`´"), "'")
_Q2 = dict.fromkeys(map(ord, "“”„‟″"), '"')
_D = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")


def norm(s: str, lang: str = "en") -> str:
    s = unicodedata.normalize("NFC", s).translate(_Q1).translate(_Q2).translate(_D)
    s = re.sub("[   \f]", " ", s)
    s = re.sub(r"--+", "-", s)
    s = re.sub(r"(?m)^\s*(?:[-*•◦▪]|\d+\.)\s+", "", s)
    s = re.sub(r"[#*_`|>]", "", s)
    return re.sub(r"\s+", "" if lang in ("ja", "zh") else " ", s).strip()


def _crop(s: str, anchors, lang: str) -> str:
    if not anchors:
        return s
    a, b = (norm(x, lang) for x in anchors)
    i = s.find(a)
    if i < 0:
        al = fuzz.partial_ratio_alignment(a, s)
        i = al.dest_start if al and al.score > 80 else 0
    j = s.rfind(b)
    if j < 0 or j < i:
        al = fuzz.partial_ratio_alignment(b, s[i:])
        j = i + al.dest_end - len(b) if al and al.score > 80 else len(s)
    return s[i:j + len(b)]


def text_scores(hyp: str, gt: str, lang: str, anchors=None) -> dict:
    h, g = _crop(norm(hyp, lang), anchors, lang), _crop(norm(gt, lang), anchors, lang)
    cer = Levenshtein.distance(h, g) / max(1, len(g))
    th, tg = (list(h), list(g)) if lang in ("ja", "zh") else (h.split(" "), g.split(" "))
    wer = None if lang in ("ja", "zh") else Levenshtein.distance(th, tg) / max(1, len(tg))
    return {"cer": cer, "wer": wer}


def para_f1(hyp_paras, gt_paras, lang: str, k: int = 30) -> float:
    hk = [norm(p, lang)[:k] for p in hyp_paras if norm(p, lang)]
    gk = [norm(p, lang)[:k] for p in gt_paras if norm(p, lang)]
    if not gk or not hk:
        return 0.0
    hset, used, matched = Counter(hk), Counter(), 0
    pool = list(hset)
    for g in gk:
        if hset[g] - used[g] > 0:
            used[g] += 1
            matched += 1
        elif len(g) >= 12:
            m = process.extractOne(g, pool, scorer=fuzz.ratio, score_cutoff=88)
            if m and hset[m[0]] - used[m[0]] > 0:
                used[m[0]] += 1
                matched += 1
    r, p = matched / len(gk), min(1.0, sum(used.values()) / len(hk))
    return 2 * p * r / max(1e-9, p + r)


def heading_recall(hyp_headings, gt_headings, lang: str):
    if not gt_headings:
        return None
    hn = [norm(h, lang) for h in hyp_headings]
    hit = 0
    for g in gt_headings:
        gn = norm(g, lang)
        if any(fuzz.ratio(gn, x) >= 85 or (len(gn) > 3 and gn in x and len(x) < 2 * len(gn) + 10) for x in hn):
            hit += 1
    return hit / len(gt_headings)


def leaks(hyp: str, artifacts, lang: str) -> int:
    h = norm(hyp, lang)
    return sum(h.count(norm(a, lang)) for a in artifacts or [])


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"\w+", unicodedata.normalize("NFKC", text).lower()):
        out.extend(w) if _CJK.search(w) else out.append(w)
    return out


def token_f1(pred: str, gold: str) -> tuple[float, float, float]:
    p, g = Counter(_tokens(pred)), Counter(_tokens(gold))
    inter = sum((p & g).values())
    P, R = inter / max(1, sum(p.values())), inter / max(1, sum(g.values()))
    return P, R, (2 * P * R / (P + R) if P + R else 0.0)


def boundary_f1(pred_paras, gold_paras) -> float:
    def stream(paras):
        toks, bounds = [], set()
        for p in paras:
            toks += [t.lower() for t in re.findall(r"\w+", p)]
            bounds.add(len(toks))
        return toks, bounds
    pt, pb = stream(pred_paras)
    gt, gb = stream(gold_paras)
    m = {}
    for a, b, n in difflib.SequenceMatcher(None, pt, gt, autojunk=False).get_matching_blocks():
        for k in range(n + 1):
            m[a + k] = b + k
    tp = len({m[x] for x in pb if x in m} & gb)
    P, R = tp / max(1, len(pb)), tp / max(1, len(gb))
    return 2 * P * R / max(1e-9, P + R)
