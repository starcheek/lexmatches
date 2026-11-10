-- Add last_read_page column to books table
ALTER TABLE public.books ADD COLUMN last_read_page integer DEFAULT 1;