"""Translation eval: OLD vs NEW pipeline, candidate models, consistency, blind LLM judge.

Run inside the api image with the backend mounted (needs ANTHROPIC_API_KEY from .env):
  docker compose run --rm --no-deps -v $PWD/backend:/app api python -m eval.run gen  new:claude-haiku-5-5:low
  docker compose run --rm --no-deps -v $PWD/backend:/app api python -m eval.run report
  docker compose run --rm --no-deps -v $PWD/backend:/app api python -m eval.run judge CONFIG_A CONFIG_B [judge-model]

Config = pipeline:model:effort[:opt=val,...]; pipeline is `old` (frozen pre-v2 code, eval/old_pipeline.py),
`new` (app.translation.pipeline) or `spans` (token-index variant, eval/variants.py). Options for new/spans:
ctx=0 (no glossary, no previous page), chunk=<chars>. Every API response is cached in eval/cache keyed by
the full request, so reruns are free; results land in eval/results/<config>/<passage>.json.
"""
import hashlib
import json
import os
import re
import statistics
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import anthropic
from anthropic.types import Message
from anthropic.types.beta import BetaMessage

from app.translation import pipeline
from app.translation.align import _fold
from app.translation.claude import FALLBACK_BETA, FALLBACK_MODELS, ClaudeTranslator
from eval import old_pipeline

HERE = Path(__file__).parent
CACHE, RESULTS = HERE / "cache", HERE / "results"
TESTSET = json.loads((HERE / "testset.json").read_text())
MANIFEST = {p["id"]: p for p in json.loads((HERE / "passages/manifest.json").read_text())}
# USD per 1M tokens: input, output, cache read (cache write = 1.25 x input)
PRICES = {"claude-opus-5-5": (4, 20, 0.20), "claude-sonnet-5-5": (2, 10, 0.20),
          "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-fable-5-1": (10, 50, 0.25)}

DEFAULT_CHUNK = pipeline.CHUNK_CHARS
_real = None
_log: list[dict] = []
_seen: dict[str, int] = {}
_lock = threading.Lock()


def real_client():
    global _real
    if _real is None:
        _real = anthropic.Anthropic(timeout=180.0, max_retries=3)
    return _real


class _CachedMessages:
    def __init__(self, beta: bool):
        self.beta = beta

    def create(self, **params):
        key = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:32]
        with _lock:  # an identical request repeated in one run (a retry) is a fresh sample, not a cache hit
            _seen[key] = _seen.get(key, -1) + 1
            key = f"{key}-{_seen[key]}" if _seen[key] else key
        path = CACHE / f"{key}.json"
        if path.exists() and not os.environ.get("REFRESH"):
            d = json.loads(path.read_text())
            cached = True
        else:
            t0 = time.perf_counter()  # WSL wall clock jumps; perf_counter does not
            api = real_client().beta.messages if self.beta else real_client().messages
            resp = api.create(**params)
            d = {"response": resp.model_dump(mode="json"), "latency": time.perf_counter() - t0}
            CACHE.mkdir(exist_ok=True)
            path.write_text(json.dumps(d, ensure_ascii=False))
            cached = False
        u = d["response"]["usage"]
        with _lock:
            _log.append({"model": params["model"], "cached": cached, "latency": d["latency"],
                         "input": u["input_tokens"], "output": u["output_tokens"],
                         "cache_read": u.get("cache_read_input_tokens") or 0,
                         "cache_write": u.get("cache_creation_input_tokens") or 0})
        return (BetaMessage if self.beta else Message).model_validate(d["response"])


CACHED_CLIENT = SimpleNamespace(messages=_CachedMessages(False), beta=SimpleNamespace(messages=_CachedMessages(True)))


def cost(calls: list[dict]) -> float:
    total = 0.0
    for c in calls:
        i, o, r = PRICES[c["model"]]
        total += (c["input"] * i + c["output"] * o + c["cache_read"] * r + c["cache_write"] * i * 1.25) / 1e6
    return total


# ---------------------------------------------------------------- generation

def parse_config(cfg: str):
    parts = cfg.split(":")
    opts = dict(kv.split("=") for kv in parts[3:]) if len(parts) > 3 else {}
    return parts[0], parts[1], parts[2], opts


class Recorder:
    """Wraps a Translator and keeps the raw model output for the deterministic metrics."""

    def __init__(self, inner):
        self.inner, self.name, self.raw = inner, inner.name, []

    def translate(self, chunk):
        res = self.inner.translate(chunk)
        with _lock:
            self.raw.append({"sentences": chunk.sentences, "results": res.sentences, "glossary_in": chunk.glossary,
                             "context": bool(chunk.context), "context_tr": bool(chunk.context_translation),
                             "glossary_out": res.glossary})
        return res


def run_new(pid, text, src, tgt, model, effort, opts, state, spans=False):
    ctx = opts.get("ctx", "1") != "0"
    pipeline.CHUNK_CHARS = int(opts.get("chunk", DEFAULT_CHUNK))  # v1 runs (no tag) used chunk=1500
    pipeline.FIRST_CHUNK_ALONE = opts.get("first", "1") != "0"
    if spans:
        from eval.variants import SpanTranslator
        inner = SpanTranslator("unused", model, effort)
    else:
        inner = ClaudeTranslator("unused", model, effort)
    inner.client = CACHED_CLIENT
    if opts.get("think") == "off":  # measured: faster, but shifted glosses and loops -> not used by the app
        inner.client = SimpleNamespace(messages=SimpleNamespace(
            create=lambda **p: CACHED_CLIENT.messages.create(**p, thinking={"type": "disabled"})), beta=None)
    rec = Recorder(inner)
    sents = pipeline.page_sentences(text)
    entries = [None] * len(sents)
    gl = state.setdefault("glossary", {})

    def on_chunk(terms):
        for k, v in terms.items():
            if ctx and k not in gl and len(gl) < pipeline.GLOSSARY_CAP:
                gl[k] = v

    stats = pipeline.translate_sentences(rec, sents, entries, src, tgt, state.get("previous", ("", "")) if ctx else ("", ""),
                                         (lambda: dict(gl)) if ctx else (lambda: {}), on_chunk)
    data = pipeline.build_data(sents, entries)
    state["previous"] = pipeline._tail([(s, e["sentence"]["translation"]) for (_, s), e in zip(sents, entries)])
    return {"data": data, "raw": rec.raw, "stats": stats, "glossary_after": dict(gl)}


def run_old(pid, text, src, tgt, model, effort):
    def call(system, user, schema):
        oc = {"format": {"type": "json_schema", "schema": schema}}
        if effort:
            oc["effort"] = effort
        params = dict(model=model, max_tokens=16000, system=system,
                      messages=[{"role": "user", "content": user}], output_config=oc)
        if model in FALLBACK_MODELS:
            r = CACHED_CLIENT.beta.messages.create(**params, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"})
        else:
            r = CACHED_CLIENT.messages.create(**params)
        return json.loads(next((b.text for b in r.content if b.type == "text"), "{}"))

    src_lines, lines, st = old_pipeline.translate_page(call, text, src, tgt)
    data = {"lines": lines, "fullTranslation": old_pipeline.full_translation(lines)}
    return {"data": data, "source_lines": src_lines,
            "stats": {"calls": st.calls, "retries": st.retries, "splits": st.splits, "best_effort": st.best_effort}}


def gen(cfg: str, only: list[str] | None = None):
    kind, model, effort, opts = parse_config(cfg)
    outdir = RESULTS / cfg.replace(":", "__")
    outdir.mkdir(parents=True, exist_ok=True)
    states: dict[str, dict] = {}
    for pid in TESTSET["order"]:
        if only and pid not in only:
            continue
        meta = MANIFEST[pid]
        text = (HERE / f"passages/{pid}.txt").read_text()
        state = states.setdefault(meta["book"], {})
        del _log[:]
        t0 = time.perf_counter()
        try:
            if kind == "old":
                out = run_old(pid, text, meta["source"], meta["target"], model, effort)
            else:
                out = run_new(pid, text, meta["source"], meta["target"], model, effort, opts, state, spans=kind == "spans")
        except Exception as e:  # noqa: BLE001 - a failed page is a result too
            print(f"{pid:22s} FAILED: {e}", flush=True)
            (outdir / f"{pid}.failed").write_text(str(e))
            continue
        (outdir / f"{pid}.failed").unlink(missing_ok=True)
        wall = time.perf_counter() - t0
        calls = list(_log)
        prev_file = outdir / f"{pid}.json"
        latency = wall
        if calls and all(c["cached"] for c in calls) and prev_file.exists() and not os.environ.get("REFRESH"):
            latency = json.loads(prev_file.read_text())["latency"]  # keep the live measurement
        out.update(id=pid, config=cfg, chars=len(text), latency=latency, calls=calls, cost=cost(calls))
        prev_file.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"{pid:22s} {latency:6.1f}s  ${out['cost']:.4f}  calls={len(calls)} cached={sum(c['cached'] for c in calls)}",
              flush=True)


# ---------------------------------------------------------------- metrics

def _norm(s: str) -> str:
    return "".join(_fold(c) for c in s if not c.isspace())


def _words(s: str) -> int:
    if re.search(r"[぀-ヿ一-鿿]", s):
        return max(1, round(len(re.sub(r"\W", "", s)) / 2.5))  # ~chars per Japanese "word"
    return len(s.split())


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else 0


def load(cfg: str) -> dict[str, dict]:
    d = RESULTS / cfg.replace(":", "__")
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}


def deterministic(cfg: str) -> dict:
    res = load(cfg)
    kind = cfg.split(":")[0]
    m = {"pages": len(res), "units": 0, "punct_units": 0, "sentences": 0, "exact": 0, "repaired": 0,
         "fallbacks": 0, "calls": 0, "retries": 0, "unit_words": [], "lat_per_kchar": [], "lat": [],
         "input": 0, "output": 0, "cache_read": 0, "cost": 0.0, "coverage_fail": 0}
    for r in res.values():
        m["lat"].append(r["latency"])
        m["lat_per_kchar"].append(r["latency"] / r["chars"] * 1000)
        m["cost"] += r["cost"]
        for c in r["calls"]:
            m["input"] += c["input"] + c["cache_read"] + c["cache_write"]
            m["output"] += c["output"]
            m["cache_read"] += c["cache_read"]
        st = r["stats"]
        m["calls"] += len(r["calls"])
        m["retries"] += st.get("retries", 0) + st.get("splits", 0)
        if kind == "old":
            m["fallbacks"] += st.get("best_effort", 0)
            for src, line in zip(r["source_lines"], r["data"]["lines"]):
                m["sentences"] += 1
                pairs = [p for p in line if isinstance(p, dict)]
                exact = _norm("".join(p.get("original", "") for p in pairs)) == _norm(src)
                m["exact"] += exact
                m["coverage_fail"] += bool(old_pipeline.repair_line(src, pairs)[1])
                for p in pairs:
                    m["units"] += 1
                    m["unit_words"].append(_words(p.get("original", "")))
                    m["punct_units"] += not any(ch.isalnum() for ch in p.get("original", ""))
        else:
            m["fallbacks"] += st.get("fallbacks", 0)
            for call in r["raw"]:
                for sent, res_ in zip(call["sentences"], call["results"]):
                    units = (res_ or {}).get("u") or []
                    m["punct_units"] += sum(1 for u in units if u and not any(ch.isalnum() for ch in str(u[0])))
            # exact = the model's own chunks reproduced the sentence on the first try
            first = {}
            for call in r["raw"]:
                for sent, res_ in zip(call["sentences"], call["results"]):
                    first.setdefault(sent, res_)
            for s, line in zip(r["data"]["sentences"], r["data"]["lines"]):
                m["sentences"] += 1
                units = (first.get(s["source"]) or {}).get("u") or []
                m["exact"] += _norm("".join(str(u[0]) for u in units if u)) == _norm(s["source"])
                m["repaired"] += bool(s.get("repaired"))
                for p in line:
                    m["units"] += 1
                    m["unit_words"].append(_words(p["original"]))
    uw = m.pop("unit_words")
    lat, lpk = m.pop("lat"), m.pop("lat_per_kchar")
    n = max(1, m["pages"])
    return {
        "pages": m["pages"], "failed pages": len(list((RESULTS / cfg.replace(":", "__")).glob("*.failed"))),
        "sentences/lines": m["sentences"],
        "exact %": 100 * m["exact"] / max(1, m["sentences"]),
        "repaired %": 100 * m["repaired"] / max(1, m["sentences"]),
        "coverage-fail %": 100 * m["coverage_fail"] / max(1, m["sentences"]) if kind == "old" else 0.0,
        "fallback": m["fallbacks"], "calls": m["calls"], "retry+split": m["retries"],
        "words/unit p50": _pct(uw, 0.5), "p90": _pct(uw, 0.9), "max": max(uw or [0]),
        "units>3w %": 100 * sum(w > 3 for w in uw) / max(1, len(uw)),
        "punct-only units (raw)": m["punct_units"],
        "lat/page p50 s": _pct(lat, 0.5), "p95 s": _pct(lat, 0.95),
        "s/1k chars p50": _pct(lpk, 0.5), "s/1k p95": _pct(lpk, 0.95),
        "in tok/page": m["input"] / n, "out tok/page": m["output"] / n,
        "cache read %": 100 * m["cache_read"] / max(1, m["input"]),
        "$/page": m["cost"] / n, "$ total": m["cost"],
    }


def _variants_used(text: str, variants: list[str]) -> set[str]:
    spans = []
    for v in variants:
        for mt in re.finditer(rf"(?<![\w]){v}", text, re.I):  # no right boundary: inflected endings
            spans.append((mt.start(), -(mt.end() - mt.start()), v))
    used, end = set(), -1
    for start, neg, v in sorted(spans):
        if start >= end:
            used.add(v)
            end = start - neg
    return used


def consistency(cfg: str) -> dict:
    """Per tracked term: renderings found in the natural translation of sentences that contain it."""
    res = load(cfg)
    out = {}
    for book, terms in TESTSET["terms"].items():
        pids = [p for p in TESTSET["order"] if MANIFEST[p]["book"] == book and p in res]
        for term, variants in terms.items():
            by_form: dict[str, tuple[set, int]] = {}  # same source form must get the same rendering
            for pid in pids:
                r = res[pid]
                if cfg.startswith("old"):
                    units = [(" ".join(p.get("original", "") for p in line), " ".join(p.get("translation", "") for p in line))
                             for line in r["data"]["lines"]]
                else:
                    units = [(s["source"], s["translation"]) for s in r["data"]["sentences"]]
                for src, tr in units:
                    m = re.search(term, src, re.I)
                    if m:
                        found = _variants_used(tr, variants)
                        used, hits = by_form.get(m.group(0).lower(), (set(), 0))
                        by_form[m.group(0).lower()] = (used | found, hits + bool(found))
            for form, (used, hits) in by_form.items():
                if hits >= 2:
                    out[f"{book}:{form}"] = sorted(used)
    consistent = sum(len(v) == 1 for v in out.values())
    return {"terms": len(out), "consistent": consistent, "detail": out}


def report(cfgs: list[str]):
    rows = {c: deterministic(c) for c in cfgs}
    keys = list(next(iter(rows.values())).keys())
    width = max(len(c) for c in cfgs)
    print("metric".ljust(26) + "".join(c.rjust(max(14, len(c) + 2)) for c in cfgs))
    for k in keys:
        cells = []
        for c in cfgs:
            v = rows[c][k]
            cells.append((f"{v:.4f}" if k.startswith("$") else f"{v:.1f}" if isinstance(v, float) else str(v)).rjust(max(14, len(c) + 2)))
        print(k.ljust(26) + "".join(cells))
    print()
    for c in cfgs:
        con = consistency(c)
        print(f"consistency {c}: {con['consistent']}/{con['terms']} terms rendered one way")
        for t, v in con["detail"].items():
            if len(v) != 1:
                print(f"    {t}: {v}")
    _ = width


# ---------------------------------------------------------------- judge

JUDGE_SYSTEM = """You are an expert literary translator and language teacher. You compare two versions of interlinear study material made from the same source passage for a learner who reads the source text with a translation underneath. Each version has a full translation of the passage and an interlinear part: the source cut into chunks, each with a gloss.

Score each version from 1 to 10 on:
- translation: is the full translation faithful (meaning, tone, nothing missing or added) and natural in the target language?
- glosses: is each chunk's gloss correct in this context and literal enough to show what the source words mean?
- chunking: are the chunks learner-sized, meaningful units that follow the source (not whole clauses, not lone punctuation, nothing skipped)?
Then say which version a learner should get (A, B or tie) and give a one-sentence reason. Judge only quality; ignore length and formatting."""

JUDGE_SCHEMA = {"type": "object", "properties": {
    **{side: {"type": "object", "properties": {k: {"type": "integer"} for k in ("translation", "glosses", "chunking")},
              "required": ["translation", "glosses", "chunking"], "additionalProperties": False} for side in ("A", "B")},
    "preferred": {"type": "string", "enum": ["A", "B", "tie"]}, "reason": {"type": "string"}},
    "required": ["A", "B", "preferred", "reason"], "additionalProperties": False}


def render(r: dict) -> str:
    lines = r["data"]["lines"]
    inter = "\n".join(" · ".join(f"{p.get('original', '')} [{p.get('translation', '')}]" for p in line if isinstance(p, dict))
                      for line in lines if line)
    return f"Full translation:\n{r['data']['fullTranslation']}\n\nInterlinear (chunk [gloss]):\n{inter}"


def judge(cfg_a: str, cfg_b: str, judge_model: str = "claude-fable-5-1", effort: str = "medium"):
    ra, rb = load(cfg_a), load(cfg_b)
    only = os.environ.get("ONLY", "").split(",") if os.environ.get("ONLY") else None
    pids = [p for p in TESTSET["order"] if p in ra and p in rb and (not only or p in only)]
    tally = {cfg_a: {"win": 0, "translation": [], "glosses": [], "chunking": []},
             cfg_b: {"win": 0, "translation": [], "glosses": [], "chunking": []}}
    ties, rows = 0, []
    del _log[:]
    for pid in pids:
        meta = MANIFEST[pid]
        swap = int(hashlib.md5(f"{pid}{cfg_a}{cfg_b}".encode()).hexdigest(), 16) % 2 == 1
        first, second = (cfg_b, cfg_a) if swap else (cfg_a, cfg_b)
        res = {cfg_a: ra[pid], cfg_b: rb[pid]}
        text = (HERE / f"passages/{pid}.txt").read_text()
        user = (f"Source language: {meta['source']}; target language: {meta['target']}.\n\nSOURCE PASSAGE:\n{text}\n\n"
                f"=== VERSION A ===\n{render(res[first])}\n\n=== VERSION B ===\n{render(res[second])}")
        params = dict(model=judge_model, max_tokens=16000, system=JUDGE_SYSTEM,
                      messages=[{"role": "user", "content": user}],
                      output_config={"effort": effort, "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}})
        r = CACHED_CLIENT.messages.create(**params)
        v = json.loads(next(b.text for b in r.content if b.type == "text"))
        side = {"A": first, "B": second}
        for s in ("A", "B"):
            for k in ("translation", "glosses", "chunking"):
                tally[side[s]][k].append(v[s][k])
        if v["preferred"] == "tie":
            ties += 1
        else:
            tally[side[v["preferred"]]]["win"] += 1
        rows.append({"id": pid, "A": first, "B": second, **v})
        winner = side.get(v["preferred"], "tie")
        print(f"{pid:22s} winner={winner:40s} {v['reason'][:150]}", flush=True)
    out = HERE / "results" / f"judge__{cfg_a.replace(':', '__')}__VS__{cfg_b.replace(':', '__')}__{judge_model}.json"
    out.write_text(json.dumps({"rows": rows, "cost": cost(_log)}, ensure_ascii=False, indent=1))
    print(f"\njudge={judge_model} passages={len(pids)} ties={ties} cost=${cost(_log):.3f}")
    for c, t in tally.items():
        print(f"  {c:45s} wins={t['win']:2d}  " + "  ".join(
            f"{k}={statistics.mean(t[k]):.2f}" for k in ("translation", "glosses", "chunking")))


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "gen":
        only = os.environ.get("ONLY", "").split(",") if os.environ.get("ONLY") else None
        for c in args:
            print(f"== {c}")
            gen(c, only)
    elif cmd == "report":
        report(args or sorted(p.name.replace("__", ":") for p in RESULTS.iterdir() if p.is_dir()))
    elif cmd == "judge":
        judge(*args)
