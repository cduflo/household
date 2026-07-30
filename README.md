# household

Static boards for a two-person household, served by GitHub Pages, backed by
Supabase (Postgres + Google auth + row level security).

    https://cduflo.github.io/household/

## Why this repo is public and that is fine

It contains HTML, CSS, JS and the Supabase **anon key** — all of which are
public by design. The anon key is not a credential: it identifies the project,
and Row Level Security decides what any given signed-in person may read. An
anonymous caller holding it gets zero rows from every table, which is tested.

**Never add** a `service_role` key or a database password here. Those bypass
RLS entirely. They live in `~/golden-watch/.env.supabase`, which is gitignored.

GitHub Pages serves *every file in the source folder*, so this repo exists
separately from the tool repos precisely so that no config, database or
personal file can ever be published by accident.

## Layout

    index.html      landing page, links to each tool
    golden/         golden-watch — the puppy search board
    shared/         css and js reused by every tool
