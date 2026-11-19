// Landing-page demo: the opening of "Le Tour du monde en quatre-vingts jours" (Jules Verne, 1872, public
// domain), abridged, as one page per language pair: four read into English, four between other languages.
// A text is three sentences, each cut into phrases; a gloss list gives one gloss per phrase, in order.
import type { TranslationData } from "@/lib/api";

type Phrases = string[][];

const FR: Phrases = [
  ["En l'année 1872,", "la maison", "portant", "le numéro 7", "de Saville-row", "était habitée", "par Phileas Fogg,",
   "l'un des membres", "les plus singuliers", "du Reform-Club", "de Londres."],
  ["On ne savait", "rien", "de lui,", "sinon que", "c'était", "un fort galant homme", "et l'un", "des plus beaux",
   "gentlemen", "de la haute société", "anglaise."],
  ["On disait", "qu'il ressemblait", "à Byron,", "mais", "un Byron", "à moustaches", "et à favoris,", "qui aurait vécu",
   "mille ans", "sans vieillir."],
];
const FR_EN: Phrases = [
  ["in the year 1872,", "the house", "bearing", "the number 7", "of Saville Row", "was lived in", "by Phileas Fogg,",
   "one of the members", "the most peculiar", "of the Reform Club", "of London."],
  ["one knew", "nothing", "about him,", "except that", "he was", "a very gallant man", "and one", "of the finest",
   "gentlemen", "of high society", "English."],
  ["people said", "that he resembled", "Byron,", "but", "a Byron", "with a moustache", "and whiskers,", "who might have lived",
   "a thousand years", "without ageing."],
];
const FR_ES: Phrases = [
  ["en el año 1872,", "la casa", "que llevaba", "el número 7", "de Saville Row", "estaba habitada", "por Phileas Fogg,",
   "uno de los miembros", "más singulares", "del Reform Club", "de Londres."],
  ["no se sabía", "nada", "de él,", "salvo que", "era", "un hombre muy galante", "y uno", "de los más apuestos",
   "caballeros", "de la alta sociedad", "inglesa."],
  ["se decía", "que se parecía", "a Byron,", "pero", "un Byron", "con bigote", "y patillas,", "que habría vivido",
   "mil años", "sin envejecer."],
];

const ES: Phrases = [
  ["En el año 1872,", "la casa", "que llevaba", "el número 7", "de Saville Row", "estaba habitada", "por Phileas Fogg,",
   "uno de los miembros", "más singulares", "del Reform Club", "de Londres."],
  ["No se sabía", "nada", "de él,", "salvo que", "era", "un hombre muy galante", "y uno", "de los más distinguidos",
   "caballeros", "de la alta sociedad", "inglesa."],
  ["Se decía", "que se parecía", "a Byron,", "pero", "un Byron", "con bigote", "y patillas,", "que habría vivido",
   "mil años", "sin envejecer."],
];
const ES_EN: Phrases = [
  ["in the year 1872,", "the house", "that bore", "the number 7", "of Saville Row", "was lived in", "by Phileas Fogg,",
   "one of the members", "most peculiar", "of the Reform Club", "of London."],
  ["one knew", "nothing", "about him,", "except that", "he was", "a very gallant man", "and one", "of the most distinguished",
   "gentlemen", "of high society", "English."],
  ["people said", "that he resembled", "Byron,", "but", "a Byron", "with a moustache", "and whiskers,", "who might have lived",
   "a thousand years", "without ageing."],
];

const DE: Phrases = [
  ["Im Jahre 1872", "wurde", "das Haus", "Nummer 7", "in der Saville Row", "von Phileas Fogg", "bewohnt,",
   "einem der sonderbarsten", "Mitglieder", "des Reform Club", "in London."],
  ["Man wusste", "nichts", "über ihn,", "außer dass", "er", "ein sehr galanter Mann", "und einer", "der vornehmsten",
   "Gentlemen", "der englischen Oberschicht", "war."],
  ["Man sagte,", "er gleiche", "Byron,", "aber", "einem Byron", "mit Schnurrbart", "und Backenbart,", "der tausend Jahre",
   "gelebt hätte,", "ohne zu altern."],
];
const DE_EN: Phrases = [
  ["in the year 1872", "was", "the house", "number 7", "in Saville Row", "by Phileas Fogg", "lived in,",
   "one of the most peculiar", "members", "of the Reform Club", "in London."],
  ["one knew", "nothing", "about him,", "except that", "he", "a very gallant man", "and one", "of the finest",
   "gentlemen", "of English high society", "was."],
  ["people said", "he resembled", "Byron,", "but", "a Byron", "with a moustache", "and whiskers,", "who a thousand years",
   "might have lived,", "without ageing."],
];

const IT: Phrases = [
  ["Nell'anno 1872,", "la casa", "al numero 7", "di Saville Row", "era abitata", "da Phileas Fogg,", "uno dei membri",
   "più singolari", "del Reform Club", "di Londra."],
  ["Non si sapeva", "nulla", "di lui,", "se non che", "era", "un uomo molto galante", "e uno", "dei più bei",
   "gentiluomini", "dell'alta società", "inglese."],
  ["Si diceva", "che somigliasse", "a Byron,", "ma", "un Byron", "con baffi", "e basette,", "che sarebbe vissuto",
   "mille anni", "senza invecchiare."],
];
const IT_EN: Phrases = [
  ["in the year 1872,", "the house", "at number 7", "of Saville Row", "was lived in", "by Phileas Fogg,", "one of the members",
   "most peculiar", "of the Reform Club", "of London."],
  ["one knew", "nothing", "about him,", "except that", "he was", "a very gallant man", "and one", "of the finest",
   "gentlemen", "of high society", "English."],
  ["people said", "that he resembled", "Byron,", "but", "a Byron", "with a moustache", "and whiskers,", "who might have lived",
   "a thousand years", "without ageing."],
];
const IT_FR: Phrases = [
  ["en l'année 1872,", "la maison", "au numéro 7", "de Saville Row", "était habitée", "par Phileas Fogg,", "l'un des membres",
   "les plus singuliers", "du Reform Club", "de Londres."],
  ["on ne savait", "rien", "de lui,", "sinon que", "c'était", "un homme fort galant", "et l'un", "des plus beaux",
   "gentlemen", "de la haute société", "anglaise."],
  ["on disait", "qu'il ressemblait", "à Byron,", "mais", "un Byron", "à moustaches", "et à favoris,", "qui aurait vécu",
   "mille ans", "sans vieillir."],
];

// European Portuguese
const PT: Phrases = [
  ["No ano de 1872,", "a casa", "com o número 7", "de Saville Row", "era habitada", "por Phileas Fogg,", "um dos membros",
   "mais singulares", "do Reform Club", "de Londres."],
  ["Nada se sabia", "a seu respeito,", "a não ser que", "era", "um homem muito galante", "e um", "dos mais belos",
   "cavalheiros", "da alta sociedade", "inglesa."],
  ["Dizia-se", "que se parecia", "com Byron,", "mas", "um Byron", "de bigode", "e suíças,", "que teria vivido",
   "mil anos", "sem envelhecer."],
];
const PT_DE: Phrases = [
  ["im Jahre 1872,", "das Haus", "mit der Nummer 7", "in der Saville Row", "wurde bewohnt", "von Phileas Fogg,", "eines der Mitglieder",
   "sonderbarsten", "des Reform Club", "in London."],
  ["nichts wusste man", "über ihn,", "außer dass", "er war", "ein sehr galanter Mann", "und einer", "der schönsten",
   "Gentlemen", "der Oberschicht", "englischen."],
  ["man sagte", "dass er glich", "Byron,", "aber", "einem Byron", "mit Schnurrbart", "und Backenbart,", "der gelebt hätte",
   "tausend Jahre", "ohne zu altern."],
];

const EN: Phrases = [
  ["In the year 1872,", "the house", "at number 7", "Saville Row", "was lived in", "by Phileas Fogg,", "one of the most peculiar",
   "members", "of the Reform Club", "of London."],
  ["Nothing", "was known", "of him,", "except that", "he was", "a very gallant man", "and one", "of the finest",
   "gentlemen", "of English high society."],
  ["People said", "that he resembled", "Byron,", "but", "a Byron", "with a moustache", "and whiskers,", "who might have lived",
   "a thousand years", "without ageing."],
];
const EN_ES: Phrases = [
  ["en el año 1872,", "la casa", "en el número 7", "de Saville Row", "estaba habitada", "por Phileas Fogg,", "uno de los más singulares",
   "miembros", "del Reform Club", "de Londres."],
  ["nada", "se sabía", "de él,", "salvo que", "era", "un hombre muy galante", "y uno", "de los más distinguidos",
   "caballeros", "de la alta sociedad inglesa."],
  ["se decía", "que se parecía", "a Byron,", "pero", "un Byron", "con bigote", "y patillas,", "que habría vivido",
   "mil años", "sin envejecer."],
];

const sentencesOf = (text: Phrases) => text.map((line) => line.join(" "));

export interface DemoSample {
  id: string;
  label: string;
  /** Language of the text, as in lib/languages.ts */
  locale: string;
  text: string;
  translation: TranslationData;
}

/** `natural`: the reading of each sentence in the target language. */
function sample(id: string, label: string, locale: string, text: Phrases, glosses: Phrases, natural: string[]): DemoSample {
  const sources = sentencesOf(text);
  return {
    id,
    label,
    locale,
    text: sources.join(" "),
    translation: {
      version: 2,
      lines: text.map((line, i) => line.map((original, k) => ({ original, translation: glosses[i][k] }))),
      sentences: sources.map((source, i) => ({ source, translation: natural[i], paragraph: 0 })),
    } as TranslationData,
  };
}

const ENGLISH = sentencesOf(EN);

/** The first one is shown when the page opens. */
export const DEMO_SAMPLES: DemoSample[] = [
  sample("fr-en", "French → English", "french", FR, FR_EN, ENGLISH),
  sample("es-en", "Spanish → English", "spanish", ES, ES_EN, ENGLISH),
  sample("de-en", "German → English", "german", DE, DE_EN, ENGLISH),
  sample("it-en", "Italian → English", "italian", IT, IT_EN, ENGLISH),
  sample("fr-es", "French → Spanish", "french", FR, FR_ES, sentencesOf(ES)),
  sample("pt-de", "Portuguese (Portugal) → German", "portuguese", PT, PT_DE, sentencesOf(DE)),
  sample("en-es", "English → Spanish", "english", EN, EN_ES, sentencesOf(ES)),
  sample("it-fr", "Italian → French", "italian", IT, IT_FR, sentencesOf(FR)),
];
