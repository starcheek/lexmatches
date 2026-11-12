-- Per-book translation glossary: {"source term": "rendering"}; first decision wins (see translation/pipeline.py).
ALTER TABLE books ADD COLUMN IF NOT EXISTS glossary jsonb NOT NULL DEFAULT '{}'::jsonb;
