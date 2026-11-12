// Book locales are stored as lower-case English names ("french"); the API maps them to ISO codes.
export const LANGUAGES = [
  { value: "english", label: "English" },
  { value: "french", label: "French" },
  { value: "german", label: "German" },
  { value: "italian", label: "Italian" },
  { value: "japanese", label: "Japanese" },
  { value: "latvian", label: "Latvian" },
  { value: "portuguese", label: "Portuguese" },
  { value: "russian", label: "Russian" },
  { value: "spanish", label: "Spanish" },
] as const;

/** "french" -> "French"; unknown values are capitalised as-is. */
export const languageLabel = (value?: string | null) =>
  LANGUAGES.find((l) => l.value === value?.toLowerCase())?.label ??
  (value ? value.charAt(0).toUpperCase() + value.slice(1) : "");
