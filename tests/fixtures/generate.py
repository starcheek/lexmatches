"""Generate the PDF fixtures used for extraction-quality work.

Texts are public-domain French (Jules Verne 1872, Victor Hugo 1862) or written for this repo.
Regenerate (needs PyMuPDF; the api image has it):

    docker compose run --rm -v "$PWD/tests/fixtures:/fixtures" api python /fixtures/generate.py
"""
from pathlib import Path

import pymupdf

OUT = Path(__file__).parent
A4 = pymupdf.paper_rect("a4")

BASE_CSS = """
body { font-family: serif; font-size: 11pt; line-height: 1.4; }
h1 { font-size: 18pt; text-align: center; margin-bottom: 12pt; }
h2 { font-size: 14pt; margin-top: 10pt; }
h3 { font-size: 12pt; margin-top: 8pt; }
p { text-align: justify; margin: 0 0 6pt 0; }
li { margin-bottom: 2pt; }
sup { font-size: 7pt; }
"""


def write_story(path: Path, html: str, rects_for_page, css: str = BASE_CSS) -> None:
    """Flow HTML into the rects returned by rects_for_page() on as many pages as needed."""
    story = pymupdf.Story(html=html, user_css=css)
    rects = rects_for_page()
    writer = pymupdf.DocumentWriter(str(path))

    def rectfn(rect_num, filled):
        where = rects[rect_num % len(rects)]
        return (A4 if rect_num % len(rects) == 0 else None), where, None

    story.write(writer, rectfn)
    writer.close()


# 1. Clean single-column prose -------------------------------------------------------------
VERNE = [
    "En l'année 1872, la maison portant le numéro 7 de Saville-row, Burlington Gardens — maison "
    "dans laquelle Sheridan mourut en 1814 —, était habitée par Phileas Fogg, esq., l'un des membres "
    "les plus singuliers et les plus remarqués du Reform-Club de Londres, bien qu'il semblât prendre à "
    "tâche de ne rien faire qui pût attirer l'attention.",
    "À l'un des plus grands orateurs qui honorent l'Angleterre, succédait donc ce Phileas Fogg, "
    "personnage énigmatique, dont on ne savait rien, sinon que c'était un fort galant homme et l'un des "
    "plus beaux gentlemen de la haute société anglaise.",
    "On disait qu'il ressemblait à Byron — par la tête, car il était irréprochable quant aux pieds —, "
    "mais un Byron à moustaches et à favoris, un Byron impassible, qui aurait vécu mille ans sans vieillir.",
    "Anglais, à coup sûr, Phileas Fogg n'était peut-être pas Londonner. On ne le voyait jamais ni à la "
    "Bourse, ni à la Banque, ni dans aucun des comptoirs de la Cité. Ni les bassins ni les docks de "
    "Londres n'avaient jamais reçu un navire ayant pour armateur Phileas Fogg. Ce gentleman ne figurait "
    "dans aucun comité d'administration. Son nom n'avait jamais retenti dans un collège d'avocats, ni au "
    "Temple, ni à Lincoln's-inn, ni à Gray's-inn.",
    "Il n'était ni manufacturier, ni négociant, ni marchand, ni agriculteur. Il ne faisait partie ni de "
    "l'Institution royale de la Grande-Bretagne, ni de l'Institution de Londres, ni de l'Institution des "
    "Artisans, ni de l'Institution Russell, ni de l'Institution littéraire de l'Ouest, ni de "
    "l'Institution du Droit, ni de cette Institution des Arts et des Sciences réunis, qui est placée sous "
    "le patronage direct de Sa Gracieuse Majesté.",
    "Phileas Fogg était membre du Reform-Club, et voilà tout. À qui s'étonnerait de ce qu'un gentleman "
    "aussi mystérieux comptât parmi les membres de cette honorable association, on répondra qu'il passa "
    "sur la recommandation de MM. Baring frères, chez lesquels il avait un crédit ouvert. De là une "
    "certaine « surface », due à ce que ses chèques étaient régulièrement payés à vue par le débit de "
    "son compte courant, invariablement créditeur.",
    "Ce Phileas Fogg était-il riche ? Incontestablement. Mais comment il avait fait fortune, c'est ce "
    "que les mieux informés ne pouvaient dire, et Mr. Fogg était le dernier auquel il convînt de "
    "s'adresser pour l'apprendre. En tout cas, il n'était prodigue de rien, mais non avare, car partout "
    "où il manquait un appoint pour une chose noble, utile ou généreuse, il l'apportait silencieusement "
    "et même anonymement.",
    "En somme, rien de moins communicatif que ce gentleman. Il parlait aussi peu que possible, et "
    "semblait d'autant plus mystérieux qu'il était silencieux. Cependant sa vie était à jour, mais ce "
    "qu'il faisait était si mathématiquement toujours la même chose, que l'imagination, mécontente, "
    "cherchait au-delà.",
]


def clean_prose():
    html = "<h1>Le Tour du monde en quatre-vingts jours</h1><h2>I</h2>" + "".join(f"<p>{p}</p>" for p in VERNE * 2)
    write_story(OUT / "fr_clean_prose.pdf", html, lambda: [pymupdf.Rect(72, 72, A4.width - 72, A4.height - 72)])


# 2. Two-column layout ---------------------------------------------------------------------
HUGO = [
    "En 1815, M. Charles-François-Bienvenu Myriel était évêque de Digne. C'était un vieillard "
    "d'environ soixante-quinze ans ; il occupait le siège de Digne depuis 1806.",
    "Quoique ce détail ne touche en aucune manière au fond même de ce que nous avons à raconter, il "
    "n'est peut-être pas inutile, ne fût-ce que pour être exact en tout, d'indiquer ici les bruits et "
    "les propos qui avaient couru sur son compte au moment où il était arrivé dans le diocèse.",
    "Vrai ou faux, ce qu'on dit des hommes tient souvent autant de place dans leur vie et surtout dans "
    "leur destinée que ce qu'ils font. M. Myriel était fils d'un conseiller au parlement d'Aix ; "
    "noblesse de robe. On contait de lui que son père, le réservant pour hériter de sa charge, l'avait "
    "marié de fort bonne heure, à dix-huit ou vingt ans, suivant un usage assez répandu dans les "
    "familles parlementaires.",
    "Charles Myriel, nonobstant ce mariage, avait, disait-on, beaucoup fait parler de lui. Il était bien "
    "fait de sa personne, quoique d'assez petite taille, élégant, gracieux, spirituel ; toute la "
    "première partie de sa vie avait été donnée au monde et aux galanteries.",
    "La révolution survint, les événements se précipitèrent ; les familles parlementaires décimées, "
    "chassées, traquées, se dispersèrent. M. Charles Myriel, dès les premiers jours de la révolution, "
    "émigra en Italie. Sa femme y mourut d'une maladie de poitrine dont elle était atteinte depuis "
    "longtemps. Ils n'avaient point d'enfants.",
    "Que se passa-t-il ensuite dans la destinée de M. Myriel ? L'écroulement de l'ancienne société "
    "française, la chute de sa propre famille, les tragiques spectacles de 93, plus effrayants encore "
    "peut-être pour les émigrés qui les voyaient de loin avec le grossissement de l'épouvante, "
    "firent-ils germer en lui des idées de renoncement et de solitude ?",
    "Personne n'aurait pu le dire ; tout ce qu'on savait, c'est que, lorsqu'il revint d'Italie, il "
    "était prêtre.",
]


def two_column():
    margin, gap, top = 50, 24, 60
    col_w = (A4.width - 2 * margin - gap) / 2
    html = "".join(f"<p>{p}</p>" for p in HUGO * 3)
    write_story(
        OUT / "fr_two_column.pdf",
        html,
        lambda: [
            pymupdf.Rect(margin, top, margin + col_w, A4.height - top),
            pymupdf.Rect(margin + col_w + gap, top, A4.width - margin, A4.height - top),
        ],
    )
    # Title spanning both columns on page 1 would collide with the flow, so add a running title band.
    doc = pymupdf.open(OUT / "fr_two_column.pdf")
    for page in doc:
        page.insert_htmlbox(pymupdf.Rect(margin, 25, A4.width - margin, 50),
                            "<p style='text-align:center;font-size:9pt'><i>Les Misérables — Fantine — Livre premier</i></p>")
    doc.saveIncr()
    doc.close()


# 3. Headings, lists, footnotes, running header/footer -------------------------------------
STRUCTURED_HTML = """
<h1>Chapitre II — La cuisine provençale</h1>
<p>La cuisine de Provence repose sur trois piliers : l'huile d'olive, l'ail et les herbes du
maquis<sup>1</sup>. Elle se distingue de la cuisine du Nord par sa légèreté et par la place
qu'elle accorde aux légumes du jardin.</p>
<h2>1. Les ingrédients essentiels</h2>
<p>Avant de commencer, il faut réunir quelques produits simples :</p>
<ul>
<li>une huile d'olive vierge, de préférence de la vallée des Baux ;</li>
<li>de l'ail rose, récolté au début de l'été ;</li>
<li>du thym, du romarin et de la sarriette<sup>2</sup> ;</li>
<li>des tomates mûres, des courgettes et des aubergines.</li>
</ul>
<h2>2. La ratatouille, pas à pas</h2>
<h3>2.1 Préparation</h3>
<ol>
<li>Laver les légumes et les couper en dés réguliers.</li>
<li>Faire revenir chaque légume séparément dans l'huile chaude.</li>
<li>Réunir le tout dans une cocotte avec l'ail et les herbes.</li>
<li>Laisser mijoter à feu doux pendant quarante-cinq minutes.</li>
</ol>
<h3>2.2 Conseils</h3>
<p>On ne remue la ratatouille qu'avec une cuillère en bois, et l'on se garde bien de la couvrir
complètement : la vapeur doit pouvoir s'échapper. Servie tiède, elle accompagne aussi bien un
poisson grillé qu'une simple omelette. Le lendemain, réchauffée, elle est encore meilleure<sup>3</sup>.</p>
<h2>3. La soupe au pistou</h2>
<p>Le pistou est une sauce crue faite de basilic, d'ail et d'huile d'olive, pilés ensemble dans un
mortier de marbre. On l'ajoute au dernier moment dans une soupe de haricots et de légumes d'été.
Chaque famille possède sa recette, et chacune affirme que la sienne est la seule véritable.</p>
<p>Il convient de choisir des haricots frais, blancs et rouges, ainsi que quelques pommes de terre
pour lier le bouillon. Les pâtes, souvent des coquillettes, sont ajoutées dix minutes avant la fin
de la cuisson.</p>
"""

FOOTNOTES = [
    "¹ Le maquis désigne la végétation dense des collines méditerranéennes.",
    "² La sarriette est appelée « pèbre d'ase » en provençal.",
    "³ C'est l'avis unanime des cuisinières de Marseille.",
]


def structured():
    path = OUT / "fr_structured_footnotes.pdf"
    body = pymupdf.Rect(72, 80, A4.width - 72, A4.height - 140)
    write_story(path, STRUCTURED_HTML, lambda: [body])
    doc = pymupdf.open(path)
    for i, page in enumerate(doc):
        page.insert_htmlbox(pymupdf.Rect(72, 36, A4.width - 72, 60),
                            "<p style='font-size:9pt'>Cuisine de Provence</p>")
        page.insert_htmlbox(pymupdf.Rect(72, 36, A4.width - 72, 60),
                            "<p style='font-size:9pt;text-align:right'>Chapitre II</p>")
        page.draw_line(pymupdf.Point(72, 62), pymupdf.Point(A4.width - 72, 62), width=0.5)
        notes = FOOTNOTES if i == 0 else FOOTNOTES[2:]
        page.draw_line(pymupdf.Point(72, A4.height - 130), pymupdf.Point(200, A4.height - 130), width=0.5)
        page.insert_htmlbox(pymupdf.Rect(72, A4.height - 125, A4.width - 72, A4.height - 70),
                            "".join(f"<p style='font-size:8pt;margin:0'>{n}</p>" for n in notes))
        page.insert_htmlbox(pymupdf.Rect(72, A4.height - 50, A4.width - 72, A4.height - 30),
                            f"<p style='text-align:center;font-size:9pt'>— {12 + i} —</p>")
    doc.saveIncr()
    doc.close()


# 4. Hyphenated line breaks ----------------------------------------------------------------
HYPHEN_TEXT = (
    "Cependant les voyageurs continuaient leur route à travers une contrée magnifique, où les "
    "montagnes succédaient aux plaines immenses, et les forêts impénétrables aux marécages "
    "inquiétants. Le conducteur, extraordinairement silencieux, surveillait attentivement "
    "l'horizon, c'est-à-dire la ligne indécise où le ciel rejoignait la terre. Peut-être "
    "craignait-il quelque rencontre désagréable ; peut-être, au contraire, espérait-il "
    "apercevoir les premières habitations du village. Personne, d'ailleurs, ne songeait à "
    "l'interroger, tant son visage exprimait une préoccupation profonde. Les chevaux, épuisés "
    "par une marche ininterrompue depuis l'aube, ralentissaient insensiblement l'allure, et "
    "l'obscurité commençait à envahir la vallée lorsque la voiture s'arrêta brusquement devant "
    "une auberge solitaire, dont les fenêtres éclairées promettaient un repos bien mérité."
)


def hyphen_wrap(text: str, width: int) -> list[str]:
    """Greedy wrap that breaks long words with a trailing hyphen, like a typeset book."""
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) <= width:
            line = candidate
            continue
        room = width - len(line) - (1 if line else 0) - 1  # space + hyphen
        if len(word) >= 7 and room >= 3 and len(word) - room >= 3 and "-" not in word:
            lines.append(f"{line} {word[:room]}-".strip())
            line = word[room:]
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def hyphenated():
    doc = pymupdf.open()
    paragraphs = [HYPHEN_TEXT, HYPHEN_TEXT.replace("Cependant", "Le lendemain,")]
    y_limit = A4.height - 72
    page, y = None, None
    for para in paragraphs * 2:
        for k, line in enumerate(hyphen_wrap(para, 52)):
            if page is None or y > y_limit:
                page, y = doc.new_page(width=A4.width, height=A4.height), 80
            page.insert_text((90 if k == 0 else 72, y), line, fontname="tiro", fontsize=12)
            y += 17
        y += 10
    doc.save(OUT / "fr_hyphenated.pdf", garbage=3, deflate=True)
    doc.close()


if __name__ == "__main__":
    clean_prose()
    two_column()
    structured()
    hyphenated()
    for pdf in sorted(OUT.glob("*.pdf")):
        with pymupdf.open(pdf) as d:
            print(f"{pdf.name}: {d.page_count} pages, {pdf.stat().st_size // 1024} KiB")
