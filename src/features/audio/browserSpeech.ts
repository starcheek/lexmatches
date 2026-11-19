// Web Speech API fallback: logged-out demo and languages without a server voice.

const BCP47: Record<string, string> = {
  english: "en-US", en: "en-US",
  french: "fr-FR", fr: "fr-FR",
  spanish: "es-ES", es: "es-ES",
  german: "de-DE", de: "de-DE",
  italian: "it-IT", it: "it-IT",
  portuguese: "pt-PT", "brazilian portuguese": "pt-BR", pt: "pt-BR",
  russian: "ru-RU", ru: "ru-RU",
  japanese: "ja-JP", ja: "ja-JP",
  latvian: "lv-LV", lv: "lv-LV",
  dutch: "nl-NL", nl: "nl-NL",
  polish: "pl-PL", pl: "pl-PL",
  ukrainian: "uk-UA", uk: "uk-UA",
  czech: "cs-CZ", cs: "cs-CZ",
  swedish: "sv-SE", sv: "sv-SE",
  norwegian: "nb-NO", no: "nb-NO", nb: "nb-NO",
  danish: "da-DK", da: "da-DK",
  finnish: "fi-FI", fi: "fi-FI",
  romanian: "ro-RO", ro: "ro-RO",
  hungarian: "hu-HU", hu: "hu-HU",
  greek: "el-GR", el: "el-GR",
  turkish: "tr-TR", tr: "tr-TR",
  catalan: "ca-ES", ca: "ca-ES",
};

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English", fr: "French", es: "Spanish", de: "German", it: "Italian",
  pt: "Portuguese", ru: "Russian", ja: "Japanese", lv: "Latvian",
  nl: "Dutch", pl: "Polish", uk: "Ukrainian", cs: "Czech", sv: "Swedish", nb: "Norwegian", da: "Danish",
  fi: "Finnish", ro: "Romanian", hu: "Hungarian", el: "Greek", tr: "Turkish", ca: "Catalan",
};

// Systems label the same language differently (Norwegian voices: nb-NO, no-NO or nn-NO).
const VOICE_ALIASES: Record<string, string[]> = { nb: ["nb", "no", "nn"] };

export const bcp47 = (lang: string) => BCP47[lang.toLowerCase()] ?? lang;
export const isoOf = (lang: string) => bcp47(lang).slice(0, 2).toLowerCase();

export const browserSpeechSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

/** Best installed voice for a language: "natural/neural/premium" names first, then local voices. */
export function pickVoice(lang: string): SpeechSynthesisVoice | null {
  if (!browserSpeechSupported()) return null;
  const codes = VOICE_ALIASES[isoOf(lang)] ?? [isoOf(lang)];
  const tagOf = (v: SpeechSynthesisVoice) => v.lang.toLowerCase().replace("_", "-"); // some Android voices say "nb_NO"
  const all = window.speechSynthesis.getVoices().filter((v) => codes.some((c) => tagOf(v) === c || tagOf(v).startsWith(`${c}-`)));
  // Portuguese has two accents: a voice of the right country when there is one, any Portuguese voice otherwise
  const regional = isoOf(lang) === "pt" ? all.filter((v) => tagOf(v) === bcp47(lang).toLowerCase()) : [];
  const matching = regional.length ? regional : all;
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
