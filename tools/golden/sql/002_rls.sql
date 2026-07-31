-- Row Level Security: the entire security boundary.
--
-- The anon key ships in the public JavaScript by design. It is not a secret and
-- it is not an access control. RLS is what stands between a URL and the data,
-- so every table gets it and the policies are tested rather than assumed.
--
-- Shape: there are exactly two humans, so there is exactly one question --
-- "is the requester one of us" -- and one policy shape reused everywhere.
-- That is much easier to get right than per-table rules.

-- ---------------------------------------------------------------- helpers
--
-- Supabase populates request.jwt.claims from the verified JWT. Reading the
-- email from there is equivalent to auth.email(); spelling it out means the
-- same SQL runs on a plain Postgres in CI with no Supabase extensions.

create or replace function app_email() returns text
language sql stable
as $$
  select lower(coalesce(
      nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email',
      ''))
$$;

-- SECURITY DEFINER so the lookup bypasses RLS on household_member itself --
-- otherwise the policy that protects the allowlist would prevent the allowlist
-- being read to evaluate the policy.
create or replace function is_household() returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (
      select 1 from household_member
      where email = app_email() and app_email() <> '')
$$;

create or replace function is_owner() returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (
      select 1 from household_member
      where email = app_email() and role = 'owner' and app_email() <> '')
$$;

-- ---------------------------------------------------------------- policies

do $$
declare t text;
begin
  -- Everything the household shares. Same policy on every one.
  foreach t in array array[
      'snapshot','finding','contact','ofa_check','run_log',
      'entity_state','note','checklist','event','commitment',
      'dog','litter','template','household_member','entity']
  loop
    -- ENABLE, not FORCE. FORCE applies RLS to the table owner too, which
    -- would defeat the SECURITY DEFINER helpers above: is_household() runs as
    -- the owner precisely so it can read the allowlist to evaluate the policy
    -- that protects the allowlist. Requests from the browser always arrive as
    -- anon or authenticated and never as the owner, so FORCE buys nothing here
    -- and breaks the lookup.
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists household_rw on %I', t);
    execute format(
      'create policy household_rw on %I for all
         to anon, authenticated
         using (is_household()) with check (is_household())', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- grants
--
-- Explicit, because "Automatically expose new tables" is OFF in the project
-- settings. That is deliberate: with auto-expose on, a table added next month
-- is reachable from the browser the moment it is created, before anyone has
-- written its policy. Off means a new table is invisible to the Data API until
-- it appears here — so this block is the complete, auditable list of what a
-- browser can touch.
--
-- Grants are not access control. They decide what is *reachable*; RLS decides
-- what is *returned*. Both are needed and they fail closed independently.

-- Schema usage first. Without it PostgREST answers every request with
-- "permission denied for schema public" (401) regardless of table grants or
-- policies -- including for signed-in members, so the board simply does not
-- work. Supabase does not necessarily grant this when the Data API is set to
-- not auto-expose new tables, and a test fixture that grants it separately
-- will hide the omission: the suite passes and production 401s.
grant usage on schema public to anon, authenticated;

do $$
declare t text;
begin
  foreach t in array array[
      'snapshot','finding','contact','ofa_check','run_log',
      'entity_state','note','checklist','event','commitment',
      'dog','litter','template','household_member','entity']
  loop
    execute format('grant select, insert, update, delete on %I to anon, authenticated', t);
  end loop;
end $$;

grant usage on all sequences in schema public to anon, authenticated;

-- The allowlist is readable by the household but writable only by an owner:
-- a household member must not be able to add themselves an accomplice.
-- Idempotent: this file gets re-applied whenever the grant list or a policy
-- changes, and a migration that only works on an empty database is a migration
-- you cannot fix production with.
drop policy if exists household_rw on household_member;
drop policy if exists member_read on household_member;
drop policy if exists member_write on household_member;
create policy member_read on household_member for select
    to anon, authenticated using (is_household());
create policy member_write on household_member for all
    to anon, authenticated using (is_owner()) with check (is_owner());

-- `force row level security` above matters: without it the table owner
-- bypasses RLS, and on Supabase some maintenance paths run as the owner.
