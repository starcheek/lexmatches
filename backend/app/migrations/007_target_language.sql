-- Changing a book's target language (PATCH /api/books/{id}): what was translated into the language being left
-- is kept here and put back if the reader returns to it, so nothing is translated twice.
-- pages.translations_cache = {"<target_locale>": {"data": <translated_data>, "status": "<page status>"}}
-- books.glossary_cache     = {"<target_locale>": <glossary>}
ALTER TABLE pages ADD COLUMN IF NOT EXISTS translations_cache jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE books ADD COLUMN IF NOT EXISTS glossary_cache jsonb NOT NULL DEFAULT '{}'::jsonb;
