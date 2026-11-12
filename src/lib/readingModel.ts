// Page text + translated_data -> paragraphs of sentences, the unit the reader renders, highlights and
// reads aloud. Sentence i here is translated_data.lines[i] / sentences[i] (v2 contract).
import type { TranslationData, WordPair } from "./api";
import { pageToParagraphs } from "./segment";

export interface ReaderSentence {
  /** Index into translated_data.lines / sentences; also the read-aloud segment id suffix. */
  index: number;
  /** Source text; null = not translated yet and the source cannot be located (placeholder). */
  source: string | null;
  chunks: WordPair[] | null;
  translation: string | null;
}

export interface ReaderParagraph {
  key: string;
  sentences: ReaderSentence[];
}

export interface ReaderModel {
  paragraphs: ReaderParagraph[];
  sentences: ReaderSentence[];
  translated: number;
  total: number;
  /** Any gloss chunks available (enables the gloss toggle). */
  hasGlosses: boolean;
  /** Any natural sentence translations available (v2). */
  hasTranslations: boolean;
}

const pairsOf = (line: unknown): WordPair[] | null =>
  Array.isArray(line) && line.length > 0 ? (line as WordPair[]) : null;

export function buildReaderModel(originalText: string, data?: TranslationData | null): ReaderModel {
  const local = pageToParagraphs(originalText);
  const localFlat = local.flatMap((sentences, p) => sentences.map((source) => ({ source, paragraph: p })));
  const lines = Array.isArray(data?.lines) ? data!.lines : [];
  const isV2 = data?.version === 2 || Array.isArray(data?.sentences);
  const sentences: ReaderSentence[] = [];
  const paragraphOf: number[] = [];

  if (isV2 && lines.length) {
    const meta = Array.isArray(data!.sentences) ? data!.sentences : [];
    const aligned = localFlat.length === lines.length; // local split agrees with the server's
    lines.forEach((line, i) => {
      const m = meta[i];
      const chunks = pairsOf(line);
      const source = m?.source ?? (chunks ? chunks.map((c) => c.original).join(" ") : aligned ? localFlat[i].source : null);
      const paragraph = typeof m?.paragraph === "number" ? m.paragraph : aligned ? localFlat[i].paragraph : null;
      sentences.push({ index: i, source, chunks, translation: m?.translation ?? null });
      // Unknown paragraph (placeholder without alignment): stay with the previous sentence.
      paragraphOf.push(paragraph ?? paragraphOf[i - 1] ?? 0);
    });
  } else if (lines.length) {
    // Legacy v1: one entry per visual line. Lines flow together; a line ending a sentence that is
    // much shorter than its neighbours closes the paragraph.
    let p = 0;
    const lengths = lines.map((l) => (pairsOf(l) ?? []).map((c) => c.original).join(" ").length);
    const typical = [...lengths].sort((a, b) => a - b)[Math.floor(lengths.length * 0.8)] ?? 0;
    lines.forEach((line, i) => {
      const chunks = pairsOf(line);
      const source = chunks ? chunks.map((c) => c.original).join(" ") : null;
      sentences.push({ index: i, source, chunks, translation: null });
      paragraphOf.push(p);
      if (source && /[.!?…:»"”)]$/.test(source) && source.length < 0.7 * typical) p++;
    });
  } else {
    localFlat.forEach((s, i) => {
      sentences.push({ index: i, source: s.source, chunks: null, translation: null });
      paragraphOf.push(s.paragraph);
    });
  }

  const paragraphs: ReaderParagraph[] = [];
  sentences.forEach((s, i) => {
    const last = paragraphs[paragraphs.length - 1];
    if (last && paragraphOf[i] === paragraphOf[i - 1]) last.sentences.push(s);
    else paragraphs.push({ key: `p${paragraphOf[i]}-${i}`, sentences: [s] });
  });

  return {
    paragraphs,
    sentences,
    translated: sentences.filter((s) => s.chunks).length,
    total: sentences.length,
    hasGlosses: sentences.some((s) => s.chunks),
    hasTranslations: sentences.some((s) => s.translation),
  };
}
