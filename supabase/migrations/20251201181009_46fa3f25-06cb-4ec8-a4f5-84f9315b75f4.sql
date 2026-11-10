-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- Create app_role enum for user roles
create type public.app_role as enum ('admin', 'user');

-- Create profiles table
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  openai_api_key text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.profiles enable row level security;

-- Profiles RLS policies
create policy "Users can view own profile"
  on public.profiles for select
  using (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = id);

-- Create user_roles table
create table public.user_roles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade not null,
  role app_role not null,
  unique (user_id, role)
);

alter table public.user_roles enable row level security;

-- User roles RLS policies
create policy "Users can view own roles"
  on public.user_roles for select
  using (auth.uid() = user_id);

-- Function to check user roles
create or replace function public.has_role(_user_id uuid, _role app_role)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.user_roles
    where user_id = _user_id
      and role = _role
  )
$$;

-- Create settings table for translation prompts
create table public.settings (
  id uuid primary key default gen_random_uuid(),
  key text unique not null,
  value text not null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.settings enable row level security;

-- Settings RLS policies (admin only)
create policy "Admins can manage settings"
  on public.settings for all
  using (public.has_role(auth.uid(), 'admin'));

-- Create books table
create table public.books (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade not null,
  title text not null,
  original_locale text not null,
  target_locale text not null,
  status text default 'pending' check (status in ('pending', 'processing', 'completed', 'failed')),
  total_pages integer default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.books enable row level security;

-- Books RLS policies
create policy "Users can view own books"
  on public.books for select
  using (auth.uid() = user_id);

create policy "Users can insert own books"
  on public.books for insert
  with check (auth.uid() = user_id);

create policy "Users can update own books"
  on public.books for update
  using (auth.uid() = user_id);

create policy "Users can delete own books"
  on public.books for delete
  using (auth.uid() = user_id);

-- Create pages table
create table public.pages (
  id uuid primary key default gen_random_uuid(),
  book_id uuid references public.books(id) on delete cascade not null,
  page_number integer not null,
  original_text text not null,
  translated_data jsonb,
  status text default 'pending' check (status in ('pending', 'processing', 'completed', 'failed')),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(book_id, page_number)
);

alter table public.pages enable row level security;

-- Pages RLS policies
create policy "Users can view pages of own books"
  on public.pages for select
  using (
    exists (
      select 1 from public.books
      where books.id = pages.book_id
      and books.user_id = auth.uid()
    )
  );

-- Function to handle new user creation
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id,
    new.email,
    new.raw_user_meta_data->>'full_name'
  );
  
  -- Add default user role
  insert into public.user_roles (user_id, role)
  values (new.id, 'user');
  
  return new;
end;
$$;

-- Trigger for new user creation
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Function to update updated_at timestamp
create or replace function public.update_updated_at_column()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- Add updated_at triggers
create trigger update_profiles_updated_at before update on public.profiles
  for each row execute procedure public.update_updated_at_column();

create trigger update_settings_updated_at before update on public.settings
  for each row execute procedure public.update_updated_at_column();

create trigger update_books_updated_at before update on public.books
  for each row execute procedure public.update_updated_at_column();

create trigger update_pages_updated_at before update on public.pages
  for each row execute procedure public.update_updated_at_column();

-- Insert default settings
insert into public.settings (key, value) values
  ('global_translation_prompt', 'You are a language translation assistant. Translate the provided text accurately while preserving meaning and context. Provide word-by-word translations aligned with the original text, as well as a full translation of the complete text.'),
  ('french_translation_prompt', 'Translate this French text to English, providing both literal word-by-word translations and a natural full translation.');
