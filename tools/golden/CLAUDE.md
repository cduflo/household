# CLAUDE.md

Context for working in this repo.

## What this is

A scheduled watcher for a golden retriever puppy search out of West Hartford, CT.
It diffs pages, scores the diffs for litter announcements, alerts Telegram, and
renders a static dashboard. One user, run from cron or GitHub Actions.

## The finding that shaped the design

**No GRCA member club in New England publishes litters on the open web.** Yankee,
Southern Berkshire, CT River Valley and Hudson Valley all route litter listings
through a volunteer's inbox. Verified July 2026.

So `clubs:` in config is **not a scrape target**. It is a contact cadence — the
tool tracks staleness and tells the user when to write. If you find yourself
adding a scraper for club litter listings, the listings do not exist. Check the
page before writing the parser.

What *does* change publicly: individual breeder kennel sites, which announce
planned breedings and confirmed pregnancies, and club event calendars.

## Layout

```
config.yaml       declarative only: who exists, addresses, territories. Heavily
                  commented — never machine-write it except via append_breeder.
gw/db.py          sqlite + PRAGMA user_version migration runner
gw/model.py       pure domain: stages, checklists, dated clearances, ratings
gw/crm.py         CRM reads/writes; every mutation logs an event
gw/serve.py       localhost HTTP command station
gw/dashboard.py   collect() + render(); neither writes a file
gw/fetch.py       polite http + text normalization + line-level diff
gw/signal.py      scores diffs for litter language; transparent regex, no ML
gw/lines.py       show vs field classification from AKC titles
gw/ofa.py         OFA lookup (best-effort) + clearance audit (exact)
gw/nudge.py       cadence + email draft generation
gw/notify.py      telegram
gw/cli.py         entry point
state.db          gitignored, never committed — see below
scripts/sweep.sh  cron entry point: sweep, then snapshot the db to iCloud
scripts/install-agent.sh   LaunchAgent for the server (not for the sweep)
tests/            pytest; run `.venv/bin/python -m pytest tests/`
```

## The dashboard is the interaction

`gw serve` (default :8420, LaunchAgent keeps it up) is where the work happens:
initiate (drafts, add a breeder, log a reply), track (stage, checklist, notes,
whose court the ball is in), rate (1–5 plus derived clearance completeness),
plan (dates in the next 60 days). The CLI remains for the cron sweep and one-off
lookups.

**Config is declarative; the database owns anything that changes.** A breeder's
`status:` in config.yaml is read exactly once, to seed `entity_state.stage`
(`crm.sync_entities`). After that the database is authoritative and config's
value is ignored — two writers for one fact is how they silently diverge.

**`state.db` never enters git.** It holds notes, contact history and rendered
drafts, which interpolate the household paragraph, a phone number and a child's
age. An earlier GH Action claimed to commit it; that step actually exited 1
every time (git refuses an ignored pathspec), so it never worked and the claim
here was false. The workflow has been deleted — without carried state a remote
sweep re-baselines every run and alerts on nothing. Durability is
`scripts/sweep.sh`'s `sqlite3.backup()` snapshot into iCloud, 14 kept.

## Rules that are load-bearing

**Never call `yaml.safe_dump` on config.yaml.** It strips every comment, and the
comments carry the reasoning. `cli.append_breeder()` writes raw text for this
reason. This bug already happened once.

**Nothing sends email.** `gw draft` prints; the dashboard renders into a
textarea with a Copy button. Breeders screen buyers harder than buyers screen
breeders and a mail-merge inquiry is the fastest way onto the ignore pile. Every
draft leaves one required blank — a specific true sentence about *their* dogs —
that the user fills in. Do not automate that away, and do not add an SMTP path.

The blank is **warned about, never enforced**. Gating "log sent" on it means
fighting a regex over a stale textarea after the mail has already gone, and the
only way out is typing filler into the one line that has to be true.

**Clearances belong to dogs, not kennels.** A kennel is not screened; the sire
and dam of one specific breeding are. `model.audit_pairing` is the unit that
means something, and `dog.breeder_key` is nullable because the sire is usually
another kennel's stud. Never add a clearance field to a breeder.

**Never store a fact that expires.** Eye clearances are annual, so state is
derived from a stored date on every read (`model.eye_state`). A ticked "eyes:
done" box is silently wrong twelve months later and, worse, is believed.

**Migrations are append-only and versioned.** SQLite has no
`ADD COLUMN IF NOT EXISTS`, and `executescript` implicitly commits, so schema
changes past the initial CREATE go in `db.MIGRATIONS` behind `user_version`.
`connect()` runs on every command — a migration that throws bricks the tool.

**Nudges upsert and reconcile, never plain-insert.** A plain INSERT per sweep is
what made Telegram re-alert fifteen overdue clubs twice a day forever.

**Score the diff, not the page.** `fetch.added_lines()` returns only new lines.
A breeder site that permanently says "we occasionally have puppies" must never
fire; the day they add "Sadie is due September 14" it must. Scoring the whole
page breaks this.

**Crawl politely.** These are volunteer clubs on cheap shared hosting.
`request_delay_seconds` and `min_interval_hours` exist for a reason. Do not
parallelize the fetch loop.

**Don't fake the OFA lookup.** OFA publishes no API and the advanced-search query
params are not contractual. When parsing fails, `ofa.lookup()` returns a search
URL rather than a guess. Keep it that way. The *audit* logic (`ofa.audit`) is
exact and can be trusted: finals require 24 months, eye exams expire in 12, CHIC
requires all four screenings.

**No Facebook scraping.** A lot of litter chatter lives there and scraping it
gets the account banned.

## Targeting

`preferences.line: show` — goldens are one breed but two populations. American
conformation lines are the fit for a family companion; field lines carry drive
that does not switch off. `lines.py` reads AKC titles to tell them apart. Note
that JH, WC, WCX, CD, agility and dock titles are earned by *both* and prove
nothing — only CH/GCH/BISS vs FC/AFC/MH are discriminating.

`preferences.sex: female` is a stated preference, not a filter. Breeders match
individual puppies to homes and rigidity costs waitlist position.

## Useful next work

- Parse club event calendars into structured dates and alert N days ahead, split
  by conformation vs field focus
- AKC show results as a source of local conformation kennel names
- Detect when a watched breeder page adds an OFA number and auto-run the audit
- Dashboard: sort breeders by clearance completeness, not config order
