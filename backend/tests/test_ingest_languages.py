"""Ingestion tables for the added languages (nl pl uk cs sv no da fi ro hu el tr ca, plus es it): function words,
one-letter words in letter-spaced PDF text, chapter headings, the PDF text-layer gate, legacy codecs, language codes."""
import pytest

from app.ingest import ingest_file, langid, ocr
from app.ingest.encoding import decode
from app.ingest.formats.pdf_layout import _letterspacing
from app.ingest.formats.pdf_structure import CHAPTER
from app.ingest.formats.text import func_density
from app.ingest.levels import HEADING_RX, LEVEL1

EL = ("Το πρωί ο Νίκος ξύπνησε νωρίς και άνοιξε το παράθυρο. Η θάλασσα ήταν ήσυχη και ο ουρανός καθαρός, "
      "χωρίς ούτε ένα σύννεφο. Άνοιξε την πόρτα, κατέβηκε στην κουζίνα, έφτιαξε καφέ και κάθισε στην αυλή να "
      "διαβάσει την εφημερίδα. Η γειτόνισσα του φώναξε από το μπαλκόνι ότι το λεωφορείο για την πόλη θα αργούσε "
      "σήμερα, γιατί ο δρόμος ήταν κλειστός μετά τη χθεσινή καταιγίδα. Ο Νίκος χαμογέλασε, δεν βιαζόταν καθόλου.")
TR = ("Sabah erkenden kalkan Ayşe, pencereyi açıp denize baktı. Hava güneşliydi ve martılar limanın üzerinde "
      "dönüp duruyordu. Kahvaltıdan sonra çarşıya inip taze ekmek, peynir ve zeytin aldı. Dönüş yolunda eski bir "
      "arkadaşıyla karşılaştı; birlikte çay içip çocukluklarını konuştular. Öğleden sonra bahçedeki ağaçların "
      "altında kitap okudu ve akşam olunca ailesiyle birlikte yemeğe oturdu. İstanbul'a gitmeyi düşünüyordu.")
CS = ("Ráno se Petr probudil brzy a otevřel okno. Venku svítilo slunce a na zahradě zpívali ptáci. Šel do kuchyně, "
      "uvařil si kávu a posadil se ke stolu, aby si přečetl noviny. Sousedka na něj zavolala, že autobus do města "
      "dnes pojede později, protože silnice je po včerejší bouřce zavřená. Petr se usmál, nikam nespěchal.")
UK = ("Вранці Оксана прокинулася рано і відчинила вікно. Надворі світило сонце, а в саду співали птахи. Вона "
      "пішла на кухню, зварила каву і сіла біля столу, щоб почитати газету. Сусідка гукнула їй, що автобус до "
      "міста сьогодні запізниться, бо дорога після вчорашньої грози закрита. Оксана усміхнулася, бо нікуди не "
      "поспішала, і ґанок був ще мокрий.")
SV = ("Hon gick långsamt hem och tänkte på vad hennes far hade berättat om kriget och åren därefter, när allt var "
      "så svårt. På kvällen satt hon länge vid fönstret och såg ut över sjön, där isen ännu låg kvar.")
NO = ("Hun gikk sakte hjem og tenkte på hva faren hadde fortalt om krigen og årene etterpå, da alt var så vanskelig. "
      "Øya lå stille i morgenlyset, og bølgene slo mot svabergene.")


# ------------------------------------------------------------------------------------------------ function words
@pytest.mark.parametrize("lang,prose,menu", [
    ("nl", "Hij liep langzaam naar huis en dacht aan wat zijn vader hem over de oorlog had verteld.",
     "Home Nieuws Sport Weer Contact Inloggen Zoeken"),
    ("pl", "Rano Zosia wyszła z domu i poszła nad rzekę, a potem usiadła na ławce i zaczęła czytać.",
     "Strona główna Wiadomości Sport Pogoda Kontakt Zaloguj"),
    ("el", "Ο Νίκος άνοιξε το παράθυρο και κάθισε στην αυλή για να διαβάσει την εφημερίδα με τον καφέ του.",
     "Αρχική Ειδήσεις Αθλητικά Καιρός Επικοινωνία Σύνδεση"),
    ("tr", "Kahvaltıdan sonra çarşıya inip ekmek aldı ve bir arkadaşıyla çay içip çok uzun konuştu.",
     "Anasayfa Haberler Spor Hava Durumu İletişim Giriş"),
    ("fi", "Hän käveli kotiin ja ajatteli, mitä isä oli kertonut sodasta, mutta ei sanonut mitään.",
     "Etusivu Uutiset Urheilu Sää Yhteystiedot Kirjaudu"),
    ("es", "Los niños jugaban en la plaza mientras sus madres hablaban de la cosecha y del pan.",
     "Inicio Noticias Deportes Tiempo Contacto Buscar"),
])
def test_func_density_prose_vs_menu(lang, prose, menu):
    assert func_density(prose.split(), lang) > 0.25
    assert func_density(menu.split(), lang) < 0.1


def test_func_density_unknown_language_ignores_single_letters():
    assert func_density("A B C D E F G H I J K L M N O P R S T U W Y Z".split(), None) == 0
    assert func_density("Home News Sport Weather Video Live More Men Women Kids Sale".split(), None) < 0.15


# ------------------------------------------------------------------------------------------------ letter spacing
def test_letterspacing_join_vs_one_letter_words():
    assert _letterspacing("R o z d z i a ł", "pl") == "Rozdział"  # four of its letters are Polish words
    assert _letterspacing("K a p i t o l a", "cs") == "Kapitola"
    assert _letterspacing("Г л а в а", "ru") == "Глава"
    assert _letterspacing("i w z a", "pl") == "i w z a"  # every token a real one-letter word
    assert _letterspacing("a v k s", "cs") == "a v k s"


# ------------------------------------------------------------------------------------------------ headings
HEADINGS = ["Rozdział pierwszy", "Rozdział I", "Część pierwsza", "Część II", "Kapitola první", "Hoofdstuk 3",
            "Deel 2", "Eerste hoofdstuk", "Kapitel 4", "Kapittel 7", "Del 1", "Första kapitlet", "Første del",
            "Luku 5", "1. luku", "Ensimmäinen luku", "I. fejezet", "Első fejezet", "Második rész", "1. Bölüm",
            "Birinci Bölüm", "BİRİNCİ KISIM", "Κεφάλαιο πρώτο", "ΚΕΦΑΛΑΙΟ 1", "Μέρος δεύτερο", "Capitolul I",
            "Partea a doua", "Capítol 1", "Primera part", "Capítulo primero", "Primera parte", "Capitolo primo",
            "Parte prima", "Розділ перший", "Частина друга", "Część pierwsza: Powrót", "1. Kapitel"]
NOT_HEADINGS = ["Część ludzi uciekła z miasta", "Parte de la gente se fue", "Del otro lado del río",
                "Suurin osa ihmisistä on kotona", "Luku on suuri", "Část peněz zmizela beze stopy",
                "Deel dit artikel met vrienden", "Bölüm başkanı bugün gelmedi", "Μέρος της πόλης κάηκε"]


@pytest.mark.parametrize("line", HEADINGS)
def test_chapter_headings(line):
    assert HEADING_RX.match(line), line
    assert CHAPTER.match(line), line


@pytest.mark.parametrize("line", NOT_HEADINGS)
def test_sentence_starters_are_not_headings(line):
    assert not HEADING_RX.match(line), line
    assert not CHAPTER.match(line), line


def test_heading_levels():
    for line in ("Część pierwsza", "I. rész", "Μέρος πρώτο", "Birinci Kısım", "Del 2", "Księga II", "Partea a doua"):
        assert LEVEL1.match(line), line
    for line in ("Rozdział pierwszy", "1. fejezet", "Κεφάλαιο 1", "Birinci Bölüm", "DEL MAR AL CIELO"):
        assert not LEVEL1.match(line), line


def test_toc_headings():
    from app.ingest.levels import TOC_HEAD
    for line in ("Spis treści", "Obsah", "Inhoud", "Innehåll", "Indholdsfortegnelse", "Sisällys", "Cuprins",
                 "Tartalomjegyzék", "Περιεχόμενα", "İÇİNDEKİLER", "Зміст", "Índex", "Sumari"):
        assert TOC_HEAD.match(line), line


# ------------------------------------------------------------------------------------------------ PDF text-layer gate
def test_ocr_gate_greek_and_new_latin_languages():
    assert ocr.text_garbage(EL, "el") < 0.3
    assert ocr.text_garbage(TR, "tr") < 0.3
    assert ocr.text_garbage(CS, "cs") < 0.3
    garbage = " ".join(["ΒκΓδΖθ ΛμΝξΠρ ΣτΦχΨ ΘκΛμνΞ ΓζΔβΚλ"] * 10)  # broken ToUnicode map: no vowels, mixed case
    assert ocr.text_garbage(garbage, "el") >= 0.5
    assert ocr.text_garbage(EL, "en") >= 0.5  # Greek layer in a document said to be English: wrong script


# ------------------------------------------------------------------------------------------------ legacy codecs
@pytest.mark.parametrize("text,enc,lang", [
    (EL, "cp1253", "el"), (EL, "iso8859-7", "el"), (TR, "cp1254", "tr"), (CS, "iso8859-2", "cs"),
    (CS, "cp1250", "cs"), (UK, "koi8-u", "uk"), (UK, "cp1251", "uk"), (SV, "cp1252", "sv"), (NO, "cp1252", "no"),
])
def test_legacy_encodings_new_languages(text, enc, lang):
    decoded, rep = decode(text.encode(enc))
    assert rep["method"] == "decode+langid" and decoded == text, rep
    assert ingest_file(text.encode(enc)).language == lang


# ------------------------------------------------------------------------------------------------ language codes
def test_norm_lang_new_codes():
    for code, want in (("nb", "no"), ("nn", "no"), ("nb-NO", "no"), ("nob", "no"), ("nno", "no"), ("nor", "no"),
                       ("ell", "el"), ("gre", "el"), ("el-GR", "el"), ("ces", "cs"), ("cze", "cs"), ("nld", "nl"),
                       ("dut", "nl"), ("swe", "sv"), ("dan", "da"), ("fin", "fi"), ("ron", "ro"), ("rum", "ro"),
                       ("hun", "hu"), ("tur", "tr"), ("cat", "ca"), ("ukr", "uk"), ("pol", "pl")):
        assert langid.norm_lang(code) == want, code
