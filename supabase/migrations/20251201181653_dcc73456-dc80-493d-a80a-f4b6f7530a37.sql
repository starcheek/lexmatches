-- Create storage bucket for PDF uploads
insert into storage.buckets (id, name, public)
values ('books', 'books', false);

-- Storage policies for book PDFs
create policy "Users can upload their own PDFs"
on storage.objects for insert
with check (
  bucket_id = 'books' and
  auth.uid()::text = (storage.foldername(name))[1]
);

create policy "Users can view their own PDFs"
on storage.objects for select
using (
  bucket_id = 'books' and
  auth.uid()::text = (storage.foldername(name))[1]
);

create policy "Users can delete their own PDFs"
on storage.objects for delete
using (
  bucket_id = 'books' and
  auth.uid()::text = (storage.foldername(name))[1]
);

-- Add RLS policies for pages table (users need to be able to insert/update pages)
create policy "Users can insert pages for own books"
on public.pages for insert
with check (
  exists (
    select 1 from public.books
    where books.id = pages.book_id
    and books.user_id = auth.uid()
  )
);

create policy "Users can update pages of own books"
on public.pages for update
using (
  exists (
    select 1 from public.books
    where books.id = pages.book_id
    and books.user_id = auth.uid()
  )
);

-- Enable realtime for books and pages
alter publication supabase_realtime add table public.books;
alter publication supabase_realtime add table public.pages;