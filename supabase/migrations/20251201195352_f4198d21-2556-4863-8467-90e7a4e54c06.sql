-- Add missing RLS policies for profiles table
CREATE POLICY "Users can insert their own profile"
ON public.profiles
FOR INSERT
WITH CHECK (auth.uid() = id);

CREATE POLICY "Users can delete their own profile"
ON public.profiles
FOR DELETE
USING (auth.uid() = id);

-- Add missing DELETE policy for pages table
CREATE POLICY "Users can delete pages from their own books"
ON public.pages
FOR DELETE
USING (
  EXISTS (
    SELECT 1 FROM public.books
    WHERE books.id = pages.book_id
    AND books.user_id = auth.uid()
  )
);