-- DineFlow Supabase security baseline
-- This file is intended for the Supabase Auth + Edge Function rollout.
-- Current Django server-side queries still enforce tenant isolation in application code.

create schema if not exists public;

create or replace function public.current_restaurant_id()
returns uuid
language sql
stable
as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'restaurant_id', '')::uuid
$$;

create or replace function public.current_role()
returns text
language sql
stable
as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', '')
$$;

create or replace function public.current_permission(permission_name text)
returns boolean
language sql
stable
as $$
  select coalesce((auth.jwt() -> 'app_metadata' -> 'permissions' ->> permission_name)::boolean, false)
$$;

create or replace function public.is_owner()
returns boolean
language sql
stable
as $$
  select public.current_role() = 'OWNER'
$$;

alter table public.ordering_order enable row level security;
alter table public.core_menuitem enable row level security;
alter table public.core_stafffilter enable row level security;
alter table public.kitchen_paymentevent enable row level security;
alter table public.core_user enable row level security;

create policy "restaurant members read orders"
on public.ordering_order
for select
to authenticated
using (restaurant_id = public.current_restaurant_id());

create policy "owners and permitted staff update orders"
on public.ordering_order
for update
to authenticated
using (
  restaurant_id = public.current_restaurant_id()
  and (
    public.is_owner()
    or public.current_permission('allow_order_completion')
  )
)
with check (
  restaurant_id = public.current_restaurant_id()
);

create policy "restaurant members read items"
on public.core_menuitem
for select
to authenticated
using (restaurant_id = public.current_restaurant_id());

create policy "owners manage items"
on public.core_menuitem
for all
to authenticated
using (
  restaurant_id = public.current_restaurant_id()
  and public.is_owner()
)
with check (
  restaurant_id = public.current_restaurant_id()
  and public.is_owner()
);

create policy "restaurant members read staff filters"
on public.core_stafffilter
for select
to authenticated
using (restaurant_id = public.current_restaurant_id());

create policy "owners manage staff filters"
on public.core_stafffilter
for all
to authenticated
using (
  restaurant_id = public.current_restaurant_id()
  and public.is_owner()
)
with check (
  restaurant_id = public.current_restaurant_id()
  and public.is_owner()
);

create policy "restaurant members read payment logs"
on public.kitchen_paymentevent
for select
to authenticated
using (restaurant_id = public.current_restaurant_id());

create policy "owners read staff rows"
on public.core_user
for select
to authenticated
using (
  restaurant_id = public.current_restaurant_id()
  and public.is_owner()
);

-- Storage buckets
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('menu-images', 'menu-images', true, 5242880, array['image/jpeg', 'image/png', 'image/webp']),
  ('qr-codes', 'qr-codes', true, 1048576, array['image/png'])
on conflict (id) do nothing;

-- Public buckets bypass download authorization, but write operations still use policies.
create policy "owners manage menu images"
on storage.objects
for all
to authenticated
using (
  bucket_id = 'menu-images'
  and public.is_owner()
  and (storage.foldername(name))[1] = public.current_restaurant_id()::text
)
with check (
  bucket_id = 'menu-images'
  and public.is_owner()
  and (storage.foldername(name))[1] = public.current_restaurant_id()::text
);

create policy "owners manage qr codes"
on storage.objects
for all
to authenticated
using (
  bucket_id = 'qr-codes'
  and public.is_owner()
  and split_part(name, '.', 1) = public.current_restaurant_id()::text
)
with check (
  bucket_id = 'qr-codes'
  and public.is_owner()
  and split_part(name, '.', 1) = public.current_restaurant_id()::text
);
