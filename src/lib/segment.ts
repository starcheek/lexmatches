// Client copy of backend/app/translation/segment.py::page_to_paragraphs (plain page text ->
// paragraphs -> sentences). It lets the reader show paragraphs and read sentences aloud before a page is
// translated, with the same sentence indices the translation will use (translated_data.lines[i]).
// If the backend segmentation changes, the reader still works: translated sentences come from
// translated_data; this split is only used for sentences that are not translated yet, and only when
// its sentence count matches the server's (see readingModel.ts).

const CJK = /[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]/;
const SOFT_HYPHEN_END = /(?<=[\p{L}\p{N}_])[\u00ad\u2010]$/u;
const ASCII_HYPHEN_END = /(?<=\p{L})-$/u;
const ENDS_SENTENCE = /[.!?…:»"”’)\]]$/;
const STARTS_DIALOGUE = /^[—–«“„"]|^- /;
const BOUNDARY = /[.!?…]+[»"”’)\]]*\s+/g;
const ABBREV =
  /(?:^|\s)(?:[A-ZА-ЯЁ]|Mr|Mrs|Ms|Dr|St|Mme|Mlle|MM|Mgr|Jr|Sr|Prof|Hr|Fr|Nr|vs|etc|cf|z\.B|usw|bzw|т|г|гг|им|ул|см|tj|u\.c|piem|Sr\.ª|Dr\.ª|D)\.$/;
const MAX_SENTENCE = 500;
// Python str.isdigit(): decimal digits plus superscript/subscript digits (footnote markers like "²").
const IS_DIGIT = /^(?:\p{Nd}|[²³¹⁰-⁹₀-₉])$/u;
const isUpper = (c: string) => c !== "" && c === c.toUpperCase() && c !== c.toLowerCase();
const isLower = (c: string) => c !== "" && c === c.toLowerCase() && c !== c.toUpperCase();

function join(lines: string[]): string {
  let text = "";
  for (const line of lines) {
    if (!text) text = line;
    else if (SOFT_HYPHEN_END.test(text) && isLower(line[0])) text = text.slice(0, -1) + line;
    else if (ASCII_HYPHEN_END.test(text) && isLower(line[0])) text += line;
    else if (CJK.test(text[text.length - 1]) || CJK.test(line[0])) text += line;
    else text += " " + line;
  }
  return text.replace(/\u00ad/g, "");
}

function splitLong(sentence: string): string[] {
  if (sentence.length <= MAX_SENTENCE) return [sentence];
  const mid = Math.floor(sentence.length / 2);
  for (const sep of ["; ", ": ", ", ", " "]) {
    const cuts: number[] = [];
    for (let i = sentence.indexOf(sep); i >= 0; i = sentence.indexOf(sep, i + 1)) cuts.push(i + sep.length);
    if (cuts.length) {
      const cut = cuts.reduce((best, c) => (Math.abs(c - mid) < Math.abs(best - mid) ? c : best));
      return [...splitLong(sentence.slice(0, cut).trim()), ...splitLong(sentence.slice(cut).trim())];
    }
  }
  return [sentence];
}

export function splitSentences(paragraph: string): string[] {
  let parts: string[];
  if (CJK.test(paragraph) && !/[A-Za-z]{3}/.test(paragraph)) {
    parts = paragraph.match(/[^。！？]+(?:[。！？]+[」』）〉》"”]*)?/g) ?? [paragraph];
  } else {
    parts = [];
    let start = 0;
    for (const m of paragraph.matchAll(BOUNDARY)) {
      const end = (m.index ?? 0) + m[0].length;
      const rest = paragraph.slice(end).replace(/^[«»„“"‘‹›([¿¡—–\- ]+/, "");
      const head = paragraph.slice(start, end).trimEnd();
      if ((isUpper(rest[0] ?? "") || IS_DIGIT.test(rest[0] ?? "")) && !ABBREV.test(head)) {
        parts.push(head);
        start = end;
      }
    }
    parts.push(paragraph.slice(start));
  }
  return parts.filter((p) => p.trim()).flatMap((p) => splitLong(p.trim()));
}

/** Paragraphs of sentences, same heuristics as the backend (blank line / short sentence-final line / dialogue). */
export function pageToParagraphs(text: string): string[][] {
  const lines = (text || "").replace(/\r/g, "").split("\n").map((l) => l.trim());
  const lengths = lines.filter(Boolean).map((l) => l.length).sort((a, b) => a - b);
  if (!lengths.length) return [];
  const typical = lengths[Math.floor(lengths.length * 0.8)];
  const paragraphs: string[][] = [];
  let current: string[] = [];
  for (const line of lines) {
    if (!line) {
      if (current.length) paragraphs.push(current);
      current = [];
      continue;
    }
    const last = current[current.length - 1];
    if (
      current.length &&
      (typical > 150 || (ENDS_SENTENCE.test(last) && (last.length < 0.7 * typical || STARTS_DIALOGUE.test(line))))
    ) {
      paragraphs.push(current);
      current = [];
    }
    current.push(line);
  }
  if (current.length) paragraphs.push(current);
  return paragraphs.map((p) => splitSentences(join(p))).filter((s) => s.length);
}
