# household

Every household tool in one place: a static board per tool, one Google sign-in,
one Postgres behind row level security.

    https://cduflo.github.io/household/

## Why this repo is public, and what that means

It holds HTML, CSS, JS and the Supabase **anon key** — all public by design.
The anon key identifies the project; it is not a credential. Row Level Security
decides what a signed-in person may read, and an anonymous caller holding it
gets zero rows from every table. That is asserted by 24 tests.

**Nothing identifying anybody is tracked here.** Not the household, not a phone
number, not the referral volunteers whose addresses were harvested from club
pages and who never agreed to be republished. Those live in gitignored local
overlays (`*.local.yaml`) and in Postgres behind RLS.

Never add a `service_role` key or a database password. Those bypass RLS.

## Layout

    docs/            ← GitHub Pages serves ONLY this folder
      index.html       landing page
      shared/          auth.js, config.js, base.css, vendored supabase-js
      golden/          the puppy search board
      lease/           the lease comparison board
    tools/
      golden/          Python: the sweep, OFA logic, drafts, schema, 131 tests

Pages is pointed at `docs/`, so nothing under `tools/` is ever served — but the
repo is public, so the real protection is that no secret is in it at all.

## Adding a tool

1. `docs/<tool>/index.html` + `<tool>.js`
2. `import { gate } from "../shared/auth.js"` — sign-in, the allowlist check and
   the stranger message all come free
3. Tool-specific tables get a `<tool>_` prefix; `note`, `event` and
   `commitment` are shared across every tool via their `app` column

No new Google client, no new Supabase project, no DNS. The redirect pattern
`/household/**` already covers it.

## Auth

oauth2-proxy is not involved and neither is a server. Supabase Auth answers
"is this a real Google account", which is not authorisation — anyone has one.
The `household_member` table answers "is it one of ours", and RLS enforces that
in the database. A stranger who signs in reads nothing and is told so.
