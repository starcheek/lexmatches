// Book locales are stored as lower-case English names ("french"); the API maps them to ISO codes
// (backend/app/languages.py: keep both lists in step).
export const LANGUAGES = [
  { value: "catalan", label: "Catalan" },
  { value: "czech", label: "Czech" },
  { value: "danish", label: "Danish" },
  { value: "dutch", label: "Dutch" },
  { value: "english", label: "English" },
  { value: "finnish", label: "Finnish" },
  { value: "french", label: "French" },
  { value: "german", label: "German" },
  { value: "greek", label: "Greek" },
  { value: "hungarian", label: "Hungarian" },
  { value: "italian", label: "Italian" },
  { value: "japanese", label: "Japanese" },
  { value: "latvian", label: "Latvian" },
  { value: "norwegian", label: "Norwegian" },
  { value: "polish", label: "Polish" },
  { value: "brazilian portuguese", label: "Portuguese (Brazil)" },
  { value: "portuguese", label: "Portuguese (Portugal)" },
  { value: "romanian", label: "Romanian" },
  { value: "russian", label: "Russian" },
  { value: "spanish", label: "Spanish" },
  { value: "swedish", label: "Swedish" },
  { value: "turkish", label: "Turkish" },
  { value: "ukrainian", label: "Ukrainian" },
] as const;

/** "french" -> "French"; unknown values are capitalised as-is. */
export const languageLabel = (value?: string | null) =>
  LANGUAGES.find((l) => l.value === value?.toLowerCase())?.label ??
  (value ? value.charAt(0).toUpperCase() + value.slice(1) : "");
