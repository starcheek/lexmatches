-- Add images column to pages table to store image data
ALTER TABLE public.pages 
ADD COLUMN IF NOT EXISTS images JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.pages.images IS 'Array of image objects with base64 data and position metadata';