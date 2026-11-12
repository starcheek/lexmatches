// Web Speech API fallback: logged-out demo and languages without a server voice.

const BCP47: Record<string, string> = {
  english: "en-US", en: "en-US",
  french: "fr-FR", fr: "fr-FR",
  spanish: "es-ES", es: "es-ES",
  german: "de-DE", de: "de-DE",
  italian: "it-IT", it: "it-IT",
  portuguese: "pt-BR", pt: "pt-BR",
  russian: "ru-RU", ru: "ru-RU",
  japanese: "ja-JP", ja: "ja-JP",
  latvian: "lv-LV", lv: "lv-LV",
};

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English", fr: "French", es: "Spanish", de: "German", it: "Italian",
  pt: "Portuguese", ru: "Russian", ja: "Japanese", lv: "Latvian",
};

export const bcp47 = (lang: string) => BCP47[lang.toLowerCase()] ?? lang;
export const isoOf = (lang: string) => bcp47(lang).slice(0, 2).toLowerCase();

export const browserSpeechSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

/** Best installed voice for a language: "natural/neural/premium" names first, then local voices. */
export function pickVoice(lang: string): SpeechSynthesisVoice | null {
  if (!browserSpeechSupported()) return null;
  const iso = isoOf(lang);
  const matching = window.speechSynthesis
    .getVoices()
    .filter((v) => v.lang.toLowerCase() === iso || v.lang.toLowerCase().startsWith(`${iso}-`));
  return (
    matching.find((v) => /premium|enhanced|natural|neural/i.test(v.name)) ??
    matching.find((v) => v.localService) ??
    matching[0] ??
    null
  );
}

/** Character offset of each whitespace token in `text` (for onboundary charIndex -> word index). */
export function tokenOffsets(text: string): number[] {
  const offsets: number[] = [];
  const re = /\S+/g;
  for (let m = re.exec(text); m; m = re.exec(text)) offsets.push(m.index);
  return offsets;
}
