"""Standalone interlinear HTML export (port of the former `export-book` edge function)."""
from html import escape
from pathlib import Path

TEMPLATE = (Path(__file__).parent / "export_template.html").read_text(encoding="utf-8")


def render_export(book: dict, pages: list[dict], page_numbers: list[int]) -> str:
    parts: list[str] = []
    for page in pages:
        data = page.get("translated_data")
        if not isinstance(data, dict):
            continue
        parts.append(f'\n    <div class="page">\n      <div class="page-header">Page {page["page_number"]}</div>\n')
        for line in data.get("lines") or []:
            parts.append('      <div class="line">')
            for pair in line or []:
                original = escape(str((pair or {}).get("original", "")))
                translation = escape(str((pair or {}).get("translation", "")))
                parts.append(
                    '\n        <span class="word-pair">'
                    f'\n          <span class="original">{original}</span>'
                    f'\n          <span class="translation">{translation}</span>'
                    "\n        </span>"
                )
            parts.append("\n      </div>")
        parts.append("\n    </div>\n")

    title = escape(book["title"])
    return (
        TEMPLATE.replace("__LANG__", escape(book["target_locale"]))
        .replace("__TITLE__", title)
        .replace("__LOCALES__", f'{escape(book["original_locale"].upper())} → {escape(book["target_locale"].upper())}')
        .replace("__RANGE__", f"{page_numbers[0]} - {page_numbers[-1]}")
        .replace("__PAGES__", "".join(parts))
    )
