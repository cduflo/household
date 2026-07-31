# Server-driven golden-watch — design

Converting the dashboard from a generated snapshot into the primary interaction:
a lightweight CRM for a puppy search, with outreach generators, a standardized
per-entity checklist, freeform notes, and an append-only log.

Status: **proposal, substantially revised by review. Do not implement as written.**
Read `SERVER_DESIGN_REVIEW.md` first — six independent reviewers found three
things in this document that cannot execute as specified (§15's P0, §3's
threading model, §4's key scheme) and one root-entity error (§5/§6 hang
clearances off breeders when they belong to individual dogs). The verdict was
also that most of this should not be built yet: the search has one breeder, zero
logged contacts, and `owner.local.yaml` does not exist, which means every email
draft the tool produces today is unsendable boilerplate.

What survives review, in order: the dismiss path (§10), notes (§7), and the
checklist *content* (§6) as a prose document requiring no code.

---

## 1. Why

Today the dashboard is a dead end. `dashboard.render()` is a pure function that
returns one HTML string; `gw run` and `gw dash` write it to disk and that is the
end of the write path. Everything that changes state goes through the terminal —
`gw contacted`, `gw add-breeder`, hand-editing `config.yaml`. So the artifact the
user actually looks at is the one surface that cannot record what they learned.

Concretely, four things are missing and all four need a write path:

1. **Status that moves.** Breeder `status:` lives in `config.yaml` and is only
   ever changed by hand. Nothing advances it, and `gw contacted` — which is the
   moment status genuinely changes — does not touch it.
2. **Notes.** There is nowhere to put "called, she has a Sept litter planned out
   of Tessa, wants a fenced yard." That is the single highest-value datum in a
   puppy search and it currently lives in the user's head.
3. **A durable log.** `finding` rows are transient and dismissible; `run_log` is
   four counters. Neither answers "what happened in this search, in order."
4. **Drafts where the work happens.** `gw draft club sbgrc` prints to a terminal
   the user is not looking at.

There is also a structural gap: **nothing ever sets `finding.dismissed = 1`.**
There is no acknowledge path in the entire codebase, so the "Needs you" queue
grows forever and nothing can ever leave it.

## 2. Invariants this must not break

These come from `CLAUDE.md` and are load-bearing. The server makes some of them
easier to violate, so each gets an explicit defense.

| Rule | How the server preserves it |
|---|---|
| Never `yaml.safe_dump` on `config.yaml` | The server never writes config at all. All mutable state moves to SQLite. `add-breeder`'s raw-text append stays the only writer, CLI-only. |
| Nothing sends email | No SMTP, no send endpoint. Drafts render into a textarea; "copy" is clipboard-only. "Mark sent" is a *log* action the user takes after sending it themselves. |
| The required blank stays required | `/api/draft` returns the list of unfilled placeholders alongside the text. The UI blocks "Mark sent" while `SPECIFIC` is unfilled. This makes the rule structural instead of a matter of discipline. |
| Score the diff, not the page | Untouched. The server does not participate in fetching or scoring. |
| Crawl politely | Untouched — sweeps stay in the batch process. The one new risk is a "Sweep now" button; it is rate-limited to the existing `min_interval_hours` unless explicitly forced. |
| Don't fake the OFA lookup | Untouched. |

**New invariant, and it is a hard one:** drafts contain
`owner.household`, `owner.phone` and `owner.dog_history` — the exact material
`REVIEW.md` §4 said must never enter git history. The committed
`dashboard.html` is pushed to GitHub by cron. Therefore **drafts are fetched
live over the API and are never baked into the static HTML.** See §11.

---

## 3. Architecture

Two processes, one database.

```
cron ──> gw run          batch sweep: fetch, diff, score, alert, write events
                         ↓
                    state.db  (WAL)
                         ↑
launchd ─> gw serve      localhost HTTP: dashboard + CRM write endpoints
                         ↑
                    browser at http://127.0.0.1:8420
```

**Why not fold the sweep into the server.** Considered and rejected. A crashed or
stopped server would silently stop all monitoring, which is the one job that
cannot fail quietly. Keeping the sweep in its own scheduled process means the
watcher survives the UI, and the sweep stays testable headless. The cost is
SQLite concurrency, handled in §12.

**Server implementation: stdlib `ThreadingHTTPServer`.** No new dependency. The
route surface is nine endpoints of mostly `json.loads` → one SQL write → JSON
back; a small dict router over `BaseHTTPRequestHandler` is roughly 150 lines and
is honest about what it is. Threading matters because an OFA lookup triggered
from the UI does network I/O and must not block the page.

Escape hatch: if the route count passes ~15 or we need sessions, uploads, or
streaming, switch to Flask. That is a contained change — the handlers are pure
functions of `(payload, con, cfg)` by design, so only the router is thrown away.

---

## 4. Data model

Config keeps declarative identity: who exists, their URL, their email, their
territory. The database owns everything that changes because time passed or the
user clicked something. New tables:

```sql
CREATE TABLE IF NOT EXISTS entity_state (
    key         TEXT PRIMARY KEY,       -- club key or breeder key
    kind        TEXT NOT NULL,          -- club | breeder
    stage       TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal',   -- high | normal | low
    archived    INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS note (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key     TEXT NOT NULL,
    body    TEXT NOT NULL,
    pinned  INTEGER NOT NULL DEFAULT 0,
    at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS note_key ON note(key, at DESC);

CREATE TABLE IF NOT EXISTS checklist (
    key    TEXT NOT NULL,
    item   TEXT NOT NULL,               -- canonical id, see §6
    state  TEXT NOT NULL,               -- todo | done | na | blocked
    note   TEXT NOT NULL DEFAULT '',
    at     REAL NOT NULL,
    PRIMARY KEY (key, item)
);

CREATE TABLE IF NOT EXISTS event (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      REAL NOT NULL,
    key     TEXT,                       -- null for system-level events
    kind    TEXT NOT NULL,              -- sweep | stage | contact | note
                                        -- checklist | ofa | signal | error
    summary TEXT NOT NULL,
    meta    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS event_at ON event(at DESC);
```

`SCHEMA` in `db.py` is already run through `executescript` on every `connect()`,
and every statement is `IF NOT EXISTS`, so adding these is additive and needs no
migration tool. Existing tables are untouched.

### Config → db seeding

`entity_state` is seeded on first connect: breeders take their `status:` from
config, clubs start at `not_contacted`. **After seeding, the database wins and
config `status:` is ignored.** That divergence is a real trap — someone edits
`status: waitlist` in config six months from now and nothing happens. Defenses:

- `config.yaml`'s breeder comment block gets an explicit "seed only, the
  dashboard owns this after first run" line.
- `gw serve` logs a warning on startup for any breeder whose config status
  disagrees with its db stage.
- Long-term: drop `status:` from `add-breeder`'s emitted block entirely once the
  dashboard is the real interaction.

---

## 5. Pipeline stages (standardized)

Defined as a constant in a new `gw/pipeline.py`, not in config — the whole point
of "standardized" is that every entity moves through the same states, so they are
code, not user data.

**Breeder:**

| Stage | Means |
|---|---|
| `researching` | On the board, not yet evaluated |
| `screening` | Reading their site, classifying line, checking OFA |
| `contacted` | Intro email sent |
| `replied` | They answered |
| `conversation` | Real back-and-forth: call, questions, video |
| `visited` | Met them or the dogs |
| `waitlist` | On their list for a named or expected litter |
| `deposit` | Money down |
| `placed` | Puppy assigned |

Terminal: `passed` (we declined), `unresponsive` (they never answered),
`declined` (they declined us — worth distinguishing, it is different information).

**Club:**

`not_contacted` → `contacted` → `replied` → `referred` (they sent names) and
terminal `dormant`.

Stage transitions are free-form (any → any) rather than a state machine. A real
search skips steps constantly and a rigid graph would just get fought. But every
transition writes an `event` row, so the *history* is exact even though the
*path* is loose.

---

## 6. The checklist

The part that actually prevents missing things. One canonical list per entity
kind, same for every entity, rendered as a strip of togglable cells with an
optional note per item. Each item is `todo | done | na | blocked`.

**Breeder checklist** — deliberately mapped onto `REVIEW.md`'s open findings, so
working the checklist closes the audit:

*Identity*
- `line_classified` — show vs field via `gw line`, not from photos
- `site_reviewed` — read their program, not just the puppy page

*Health — the actual filter*
- `ofa_hips` — final, both parents, 24mo+
- `ofa_elbows` — final, both parents
- `ofa_eyes_current` — exam within 12 months of the breeding (`REVIEW.md` #12)
- `ofa_heart` — advanced cardiac, both parents
- `chic_verified` — CHIC number exists for both parents
- `dna_panel` — PRA1, PRA2, prcd, ICH, NCL, DM, MD and *how the pair was made*
  (`REVIEW.md` #11)
- `names_match_litter` — the OFA records are the actual sire and dam, not a
  sibling or grandparent (`REVIEW.md` #13)

*Integrity*
- `scam_screen` — payment methods, shipping language, site age (`REVIEW.md` #10)

*Relationship*
- `longevity_asked` — how long did the grandparents live, of what
- `video_or_visit` — seen the dam with the litter, live
- `contract_reviewed` — health guarantee, return clause, spay/neuter terms
- `references` — vet or prior puppy buyer

**Club checklist:** `intro_sent`, `replied`, `shortlist_shared` (gave them names
to react to), `event_attended` (the thing that actually moves you up).

Two derived signals fall out of this for free and both belong on the card:

- **Completeness %** — `done / (total - na)`. `REVIEW.md` #4 in "useful next
  work" asks for breeders sorted by clearance completeness; this delivers it.
- **Blocked items** surface into the "Needs you" queue as findings.

---

## 7. Notes

Freeform, timestamped, newest first, markdown-free (plain text; this is a
personal tool and a renderer is a liability). Pinnable — a pinned note renders on
the card itself rather than behind a disclosure, because "wants a fenced yard" is
a fact you need every time you look at that breeder, not once.

Notes are append-only in the UI. Editing is allowed for 15 minutes after
creation (typo window), then frozen. Rationale: a note whose text can change
silently is not a record. Deletion is possible but writes an `event`.

---

## 8. The log

An append-only `event` table, rendered as a reverse-chronological panel with
kind filters. This is distinct from `finding`, and the distinction is the whole
point:

- **`finding`** = "something wants your attention." Transient, dismissible, can
  and should reach zero.
- **`event`** = "this happened." Permanent, never dismissed, never auto-pruned.

Writers: the sweep (baselines stored, page changed, litter signal scored,
fetch errors), the server (stage change, note added, checklist item toggled,
contact logged, OFA audit run, sweep triggered manually), and Telegram dispatch
results.

Every event carries `key` where applicable, so an entity's card can show its own
filtered timeline — which is exactly the CRM "activity feed" and comes free from
the same table.

Retention: never prune. At the observed rate this table gains maybe 40 rows a
week; over three years that is single-digit MB.

---

## 9. Outreach generators in the UI

Each club and breeder card gets a draft panel:

- Variant selector where one exists — clubs have `draft_club_email` and
  `draft_near_term_club_email`, and which one is right depends on how close
  `target_home_date` is. The server defaults to the near-term variant when the
  date is inside the club's `contact_lead_days` window, matching `due_clubs()`.
- The rendered draft in a `<textarea>`, editable in the browser.
- **Unfilled-blank warning.** `/api/draft` returns `blanks: [...]` by scanning
  the output for `[...]` placeholders. `SPECIFIC` is always one of them for
  breeder drafts. While blanks remain, the "Mark sent" button is disabled and
  the textarea shows a warning strip.
- Copy to clipboard (primary). A `mailto:` link is offered only when the body is
  under ~1,500 chars, because longer bodies break in several mail clients; the
  club templates are already near that line.
- **"Mark sent"** — the deliberate second action. Logs a `contact` row (resetting
  the recontact clock exactly as `gw contacted` does), advances stage
  `not_contacted → contacted`, writes an `event`, and stores the *actual sent
  text* in the event's `meta`. Storing what was really sent matters: the user
  edits these in the textarea, and six weeks later "what did I actually tell
  them" is a question with consequences.

Edits in the textarea are not persisted back to the templates. If a phrasing
change is worth keeping it belongs in `nudge.py`, and that is a code edit.

---

## 10. HTTP API

All state-changing routes are `POST`, take JSON, return JSON, and write an
`event`.

| Route | Purpose |
|---|---|
| `GET /` | The live dashboard |
| `GET /api/draft?key=&variant=` | `{text, blanks[], variant, mailto_ok}` |
| `POST /api/stage` | `{key, stage}` |
| `POST /api/note` | `{key, body, pinned}` |
| `POST /api/checklist` | `{key, item, state, note}` |
| `POST /api/contact` | `{key, channel, summary, body}` — the "Mark sent" path |
| `POST /api/dismiss` | `{finding_id}` — the acknowledge path that does not exist today |
| `POST /api/sweep` | Trigger a sweep; respects `min_interval_hours` unless `force` |
| `GET /api/events?since=&kind=` | Log feed |

Errors return `{error: "..."}` with a 4xx and never a stack trace.

---

## 11. Rendering: one renderer, two modes

`dashboard.render(cfg, ..., live=False)`. The card-building functions
(`breeder_card`, `club_card`, `finding_card`, `clearance_strip`) are shared; the
`live` flag adds the control markup and the one `<script>` block. This avoids the
obvious failure where a static renderer and a live renderer drift apart.

What `live=False` **must** omit, non-negotiably:

- All draft text and any `owner.household`, `owner.phone`, `owner.dog_history`
- Note bodies (they will contain personal detail about breeders and about the
  household)

The static file is pushed to a GitHub repo by cron. Even private, `REVIEW.md` §4
is right that this material should not be in git history. So the static mirror
degrades to what it is today plus stage badges and checklist completeness — a
status board, not a record.

Open question for §16: whether the static mirror is worth keeping at all once
the live dashboard exists.

---

## 12. Concurrency

Two processes writing one SQLite file. Required:

- `PRAGMA journal_mode=WAL` — set once, persists in the file. Readers no longer
  block on the writer, which matters because the sweep holds the longest writes.
- `PRAGMA busy_timeout=5000` on every connection, in `db.connect()`.
- Short transactions in the server. No transaction spans a network call — the
  OFA endpoint fetches first, then opens a write.
- `.gitignore` gains `state.db-wal` and `state.db-shm`.

The sweep's snapshot writes are the large ones (full page text per target). With
WAL and six targets this is not a contention problem in practice, but the
`busy_timeout` is what makes the failure mode "briefly slow" instead of
"`database is locked` traceback in the browser."

---

## 13. Security

The threat model is not "attacker on the network." It is "a web page in another
tab makes requests to my localhost server," plus "personal data reaches GitHub."

- **Bind `127.0.0.1` explicitly.** Never `0.0.0.0` — the machine joins coffee-shop
  and airport wifi.
- **Validate the `Host` header** against `127.0.0.1:PORT` / `localhost:PORT`.
  This is the DNS-rebinding defense; without it a hostile page can resolve its
  own domain to 127.0.0.1 and talk to the server as same-origin.
- **Require `Content-Type: application/json` and a custom header** (`X-GW: 1`)
  on all writes. Both push a cross-origin request into CORS preflight, which a
  simple form-POST CSRF cannot satisfy.
- **No CORS headers.** Nothing external should ever be allowed to read a
  response.
- No auth beyond the above. Single user, single machine, loopback only; a
  password would be theater and would end up in a shell history or a plist.
- The `FONTS` constant currently pulls from `fonts.googleapis.com`. On a page
  that will now render household details, that is an outbound request from a
  page containing personal data. Self-host the two fonts or drop to system
  stacks. Low severity, easy fix, and it also makes the dashboard work offline.

---

## 14. Deployment

A LaunchAgent at `~/Library/LaunchAgents/com.chrisduflo.golden-watch.plist` with
`RunAtLoad` and `KeepAlive`, so the server is up after a reboot without thought.

Worth doing at the same time: **move the sweep from cron to launchd**
`StartCalendarInterval`. cron silently skips a run if the Mac is asleep at 07:00;
launchd runs a missed calendar job when the machine wakes. For a twice-daily
watcher on a laptop that is a meaningful difference, and it consolidates
scheduling in one place.

---

## 15. Plan

**P0 — fix before anything else.** `nudge.build_findings()` inserts a fresh
`finding` row per due entity on *every* sweep, with `notified = 0`. Verified in
the live db: two runs produced two rows per club key. Tonight's sweep will create
15 more and re-alert them, twice a day indefinitely.

**The fix as originally written here does not work, and would brick the tool.**
`finding` has no unique constraint on `key` (`db.py:20-31`), so `ON CONFLICT(key)`
is a prepare-time error; and `CREATE UNIQUE INDEX ... WHERE kind='nudge'` fails
outright on the current database because 15 keys already carry 2 rows. Since
`connect()` runs `executescript(SCHEMA)` on *every* connection (`db.py:63`), that
failure would take down every `gw` command, not just the sweep. Correct sequence:

1. Dedupe: `DELETE FROM finding WHERE kind='nudge' AND id NOT IN
   (SELECT MAX(id) FROM finding WHERE kind='nudge' GROUP BY key)`
2. `CREATE UNIQUE INDEX ... ON finding(key) WHERE kind='nudge'`
3. Upsert with the matching partial conflict target
4. Add `last_notified_at` — without it, "re-notify every N days" has nowhere to
   live, and neither leaving nor clearing `notified` is correct.

All four steps need a `PRAGMA user_version` migration runner, which `IF NOT
EXISTS` cannot express (SQLite has no `ADD COLUMN IF NOT EXISTS`).

**And the upsert alone still cannot empty the queue.** `build_findings` only
adds; nothing retracts a nudge once contact is logged. Either reconcile
(`dismissed=1 WHERE kind='nudge' AND key NOT IN (<due>)`) or compute nudges at
render time and drop them from `finding` entirely.

**Cheaper fix first:** 12 of the 16 club entries have no email address and
`method: unknown` (verified). `due_clubs()` should skip clubs with no contact
route — that alone drops the spam from 15 to 3, today, with no schema change.

Also P0-adjacent: there is no dismiss path anywhere. `POST /api/dismiss` is the
first one, which is why it ships in phase 2 rather than later.

| Phase | Ships |
|---|---|
| 0 | Nudge upsert fix. Independent of everything below. |
| 1 | Schema additions, `entity_state` seeding, `gw serve` read-only — the live dashboard renders but nothing writes. Proves WAL and the Host check. |
| 2 | Writes: stage, notes, checklist, contact, dismiss. The CRM exists. |
| 3 | Draft panel with blank-guard and "Mark sent". |
| 4 | Event log panel with filters; per-entity timelines. |
| 5 | LaunchAgent for the server, sweep moved to launchd, decide the fate of the static mirror. |

Phases 1–4 are each independently useful and independently revertable.

---

## 16. Open questions

**0. Blocking, and it invalidates §5 and §6 as written: is the root entity a
breeder or a litter?** Clearances belong to individual dogs — specifically the
sire and dam of one litter — not to kennels. `ofa_check` is keyed on
`kennel_prefix` and `clearance_strip()` renders one strip per breeder, so a
kennel with a spectacular 2019 dam and a sloppy 2026 breeding scores identically.
The sire is frequently not the breeder's dog at all. `names_match_litter` in §6
is a checkbox standing in for a missing `dog` and `litter` table. Resolve this on
paper before any schema is written; everything in §5 and §6 hangs off it.

1. **Keep the committed static `dashboard.html`?** It is a snapshot with no
   controls that must omit the most useful content. Options: keep as a status
   board, reduce to a JSON export, or drop it and let the repo hold code and
   config only.
2. **Port.** 8420 is a placeholder.
3. **Does the sweep move to launchd** with the server, or stay in cron?
4. **Should `status:` be removed from `config.yaml`** once seeded, or kept as
   documentation of intent?
5. **Multi-device.** The design assumes one machine. Reaching this from a phone
   means exposing the server, which changes the entire security section. Out of
   scope, but it is the most likely future ask, and the answer is probably
   Tailscale rather than authentication.
