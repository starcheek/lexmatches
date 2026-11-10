-- Add daily translation tracking fields to profiles table
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS daily_translations_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_translation_date DATE DEFAULT CURRENT_DATE;