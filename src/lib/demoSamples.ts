// Landing-page demo: the opening of "Le Tour du monde en quatre-vingts jours" (Jules Verne, 1872, public
// domain), abridged, as one page per language pair. Each line is one sentence, cut into [phrase, gloss].
import type { TranslationData } from "@/lib/api";

type Line = [string, string][];

interface Sample {
  id: string;
  /** Book locales as in lib/languages.ts */
  from: string;
  to: string;
  label: string;
  lines: Line[];
  /** Natural translation of each line */
  sentences: string[];
}

const ENGLISH = [
  "In the year 1872, the house at number 7 Saville Row was lived in by Phileas Fogg, one of the most peculiar members of the Reform Club of London.",
  "Nothing was known of him, except that he was a very gallant man and one of the finest gentlemen of English high society.",
  "People said that he resembled Byron, but a Byron with a moustache and whiskers, who might have lived a thousand years without ageing.",
];

const SAMPLES: Sample[] = [
  {
    id: "fr-en", from: "french", to: "english", label: "French → English",
    lines: [
      [["En l'année 1872,", "in the year 1872,"], ["la maison", "the house"], ["portant", "bearing"], ["le numéro 7", "the number 7"],
       ["de Saville-row", "of Saville Row"], ["était habitée", "was lived in"], ["par Phileas Fogg,", "by Phileas Fogg,"],
       ["l'un des membres", "one of the members"], ["les plus singuliers", "the most peculiar"], ["du Reform-Club", "of the Reform Club"],
       ["de Londres.", "of London."]],
      [["On ne savait", "one knew"], ["rien", "nothing"], ["de lui,", "about him,"], ["sinon que", "except that"], ["c'était", "he was"],
       ["un fort galant homme", "a very gallant man"], ["et l'un", "and one"], ["des plus beaux", "of the finest"],
       ["gentlemen", "gentlemen"], ["de la haute société", "of high society"], ["anglaise.", "English."]],
      [["On disait", "people said"], ["qu'il ressemblait", "that he resembled"], ["à Byron,", "Byron,"], ["mais", "but"],
       ["un Byron", "a Byron"], ["à moustaches", "with a moustache"], ["et à favoris,", "and whiskers,"], ["qui aurait vécu", "who might have lived"],
       ["mille ans", "a thousand years"], ["sans vieillir.", "without ageing."]],
    ],
    sentences: ENGLISH,
  },
  {
    id: "es-en", from: "spanish", to: "english", label: "Spanish → English",
    lines: [
      [["En el año 1872,", "in the year 1872,"], ["la casa", "the house"], ["que llevaba", "that bore"], ["el número 7", "the number 7"],
       ["de Saville Row", "of Saville Row"], ["estaba habitada", "was lived in"], ["por Phileas Fogg,", "by Phileas Fogg,"],
       ["uno de los miembros", "one of the members"], ["más singulares", "most peculiar"], ["del Reform Club", "of the Reform Club"],
       ["de Londres.", "of London."]],
      [["No se sabía", "one knew"], ["nada", "nothing"], ["de él,", "about him,"], ["salvo que", "except that"], ["era", "he was"],
       ["un hombre muy galante", "a very gallant man"], ["y uno", "and one"], ["de los más distinguidos", "of the most distinguished"],
       ["caballeros", "gentlemen"], ["de la alta sociedad", "of high society"], ["inglesa.", "English."]],
      [["Se decía", "people said"], ["que se parecía", "that he resembled"], ["a Byron,", "Byron,"], ["pero", "but"],
       ["un Byron", "a Byron"], ["con bigote", "with a moustache"], ["y patillas,", "and whiskers,"], ["que habría vivido", "who might have lived"],
       ["mil años", "a thousand years"], ["sin envejecer.", "without ageing."]],
    ],
    sentences: ENGLISH,
  },
  {
    id: "de-en", from: "german", to: "english", label: "German → English",
    lines: [
      [["Im Jahre 1872", "in the year 1872"], ["wurde", "was"], ["das Haus", "the house"], ["Nummer 7", "number 7"],
       ["in der Saville Row", "in Saville Row"], ["von Phileas Fogg", "by Phileas Fogg"], ["bewohnt,", "lived in,"],
       ["einem der sonderbarsten", "one of the most peculiar"], ["Mitglieder", "members"], ["des Reform Club", "of the Reform Club"],
       ["in London.", "in London."]],
      [["Man wusste", "one knew"], ["nichts", "nothing"], ["über ihn,", "about him,"], ["außer dass", "except that"], ["er", "he"],
       ["ein sehr galanter Mann", "a very gallant man"], ["und einer", "and one"], ["der vornehmsten", "of the finest"],
       ["Gentlemen", "gentlemen"], ["der englischen Oberschicht", "of English high society"], ["war.", "was."]],
      [["Man sagte,", "people said"], ["er gleiche", "he resembled"], ["Byron,", "Byron,"], ["aber", "but"],
       ["einem Byron", "a Byron"], ["mit Schnurrbart", "with a moustache"], ["und Backenbart,", "and whiskers,"],
       ["der tausend Jahre", "who a thousand years"], ["gelebt hätte,", "might have lived,"], ["ohne zu altern.", "without ageing."]],
    ],
    sentences: ENGLISH,
  },
  {
    id: "it-en", from: "italian", to: "english", label: "Italian → English",
    lines: [
      [["Nell'anno 1872,", "in the year 1872,"], ["la casa", "the house"], ["al numero 7", "at number 7"],
       ["di Saville Row", "of Saville Row"], ["era abitata", "was lived in"], ["da Phileas Fogg,", "by Phileas Fogg,"],
       ["uno dei membri", "one of the members"], ["più singolari", "most peculiar"], ["del Reform Club", "of the Reform Club"],
       ["di Londra.", "of London."]],
      [["Non si sapeva", "one knew"], ["nulla", "nothing"], ["di lui,", "about him,"], ["se non che", "except that"], ["era", "he was"],
       ["un uomo molto galante", "a very gallant man"], ["e uno", "and one"], ["dei più bei", "of the finest"],
       ["gentiluomini", "gentlemen"], ["dell'alta società", "of high society"], ["inglese.", "English."]],
      [["Si diceva", "people said"], ["che somigliasse", "that he resembled"], ["a Byron,", "Byron,"], ["ma", "but"],
       ["un Byron", "a Byron"], ["con baffi", "with a moustache"], ["e basette,", "and whiskers,"], ["che sarebbe vissuto", "who might have lived"],
       ["mille anni", "a thousand years"], ["senza invecchiare.", "without ageing."]],
    ],
    sentences: ENGLISH,
  },
  {
    id: "ptbr-en", from: "brazilian portuguese", to: "english", label: "Portuguese (Brazil) → English",
    lines: [
      [["No ano de 1872,", "in the year 1872,"], ["a casa", "the house"], ["de número 7", "number 7"],
       ["da Saville Row", "of Saville Row"], ["era habitada", "was lived in"], ["por Phileas Fogg,", "by Phileas Fogg,"],
       ["um dos membros", "one of the members"], ["mais singulares", "most peculiar"], ["do Reform Club", "of the Reform Club"],
       ["de Londres.", "of London."]],
      [["Não se sabia", "one knew"], ["nada", "nothing"], ["sobre ele,", "about him,"], ["a não ser que", "except that"], ["era", "he was"],
       ["um homem muito galante", "a very gallant man"], ["e um", "and one"], ["dos mais belos", "of the finest"],
       ["cavalheiros", "gentlemen"], ["da alta sociedade", "of high society"], ["inglesa.", "English."]],
      [["Dizia-se", "people said"], ["que se parecia", "that he resembled"], ["com Byron,", "Byron,"], ["mas", "but"],
       ["um Byron", "a Byron"], ["de bigode", "with a moustache"], ["e costeletas,", "and whiskers,"], ["que teria vivido", "who might have lived"],
       ["mil anos", "a thousand years"], ["sem envelhecer.", "without ageing."]],
    ],
    sentences: ENGLISH,
  },
  {
    id: "en-es", from: "english", to: "spanish", label: "English → Spanish",
    lines: [
      [["In the year 1872,", "en el año 1872,"], ["the house", "la casa"], ["at number 7", "en el número 7"],
       ["Saville Row", "de Saville Row"], ["was lived in", "estaba habitada"], ["by Phileas Fogg,", "por Phileas Fogg,"],
       ["one of the most peculiar", "uno de los más singulares"], ["members", "miembros"], ["of the Reform Club", "del Reform Club"],
       ["of London.", "de Londres."]],
      [["Nothing", "nada"], ["was known", "se sabía"], ["of him,", "de él,"], ["except that", "salvo que"], ["he was", "era"],
       ["a very gallant man", "un hombre muy galante"], ["and one", "y uno"], ["of the finest", "de los más distinguidos"],
       ["gentlemen", "caballeros"], ["of English high society.", "de la alta sociedad inglesa."]],
      [["People said", "se decía"], ["that he resembled", "que se parecía"], ["Byron,", "a Byron,"], ["but", "pero"],
       ["a Byron", "un Byron"], ["with a moustache", "con bigote"], ["and whiskers,", "y patillas,"], ["who might have lived", "que habría vivido"],
       ["a thousand years", "mil años"], ["without ageing.", "sin envejecer."]],
    ],
    sentences: [
      "En el año 1872, la casa del número 7 de Saville Row estaba habitada por Phileas Fogg, uno de los miembros más singulares del Reform Club de Londres.",
      "Nada se sabía de él, salvo que era un hombre muy galante y uno de los caballeros más distinguidos de la alta sociedad inglesa.",
      "Se decía que se parecía a Byron, pero un Byron con bigote y patillas, que habría vivido mil años sin envejecer.",
    ],
  },
];

export interface DemoSample {
  id: string;
  label: string;
  locale: string;
  text: string;
  translation: TranslationData;
}

/** The first one is shown when the page opens. */
export const DEMO_SAMPLES: DemoSample[] = SAMPLES.map((s) => {
  const sources = s.lines.map((line) => line.map(([original]) => original).join(" "));
  return {
    id: s.id,
    label: s.label,
    locale: s.from,
    text: sources.join(" "),
    translation: {
      version: 2,
      lines: s.lines.map((line) => line.map(([original, translation]) => ({ original, translation }))),
      sentences: sources.map((source, i) => ({ source, translation: s.sentences[i], paragraph: 0 })),
    } as TranslationData,
  };
});
