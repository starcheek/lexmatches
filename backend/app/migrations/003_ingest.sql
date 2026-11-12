-- Structured ingestion (app/ingest): pages become reading units built from document structure.
-- pages.page_number = reading-unit index; pages.blocks = the unit's IR blocks with sentences;
-- pages.original_text = the unit's body text (search, legacy clients). Rows from before this migration keep
-- blocks = NULL and one row per PDF page; translation segments them on the fly.
ALTER TABLE pages ADD COLUMN IF NOT EXISTS source_page_start integer;  -- PDF page span of the unit (NULL otherwise)
ALTER TABLE pages ADD COLUMN IF NOT EXISTS source_page_end integer;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS chapter_title text;         -- current level-1/2 heading / TOC entry

ALTER TABLE books ADD COLUMN IF NOT EXISTS source_format text;  -- pdf | epub | fb2 | docx | odt | rtf | markdown | txt | html | paste | paste_html | url
ALTER TABLE books ADD COLUMN IF NOT EXISTS author text;
ALTER TABLE books ADD COLUMN IF NOT EXISTS detected_language text;
ALTER TABLE books ADD COLUMN IF NOT EXISTS warnings jsonb NOT NULL DEFAULT '[]'::jsonb;  -- [{code, message, pages?}]
ALTER TABLE books ADD COLUMN IF NOT EXISTS ingest jsonb;  -- {meta, audit, removed_blocks, units}: extraction report

UPDATE books SET source_format = 'pdf' WHERE source = 'pdf' AND source_format IS NULL;
UPDATE books SET source_format = 'paste' WHERE source = 'text' AND source_format IS NULL;
