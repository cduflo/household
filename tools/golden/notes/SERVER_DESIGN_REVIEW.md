# Adversarial review — `SERVER_DESIGN.md`

Six independent reviewers, each asked to find what is wrong rather than what is
good, none shown the others' work. Findings that two or more reviewers reached
separately are marked **[converged]** — those are the ones to trust most.

Every factual claim below was re-verified against the live repo and database
before being written down.

---

## 1. The systems engineer

**The threading model crashes on the first concurrent request. [converged]**
`db.connect()` (`db.py:60`) uses `sqlite3` defaults, so `check_same_thread` is
`True`. §3's "handlers are pure functions of `(payload, con, cfg)`" implies a
shared connection; used from a `ThreadingHTTPServer` worker that raises
`ProgrammingError`. Connect per request instead — measured at 0.37 ms including
the full `executescript(SCHEMA)`, so it is free. Do *not* reach for
`check_same_thread=False` on a shared connection; that converts a loud crash
into interleaved transaction state where one thread's `commit()` lands another
thread's half-written row.

**Nothing serializes two sweeps, and "Sweep now" makes overlap normal.**
Both `cli.py:84` and `cli.py:131` gate on the *stored* `snapshot.fetched_at`.
Cron fires at 19:00, the user clicks Sweep now, both read the same stale
timestamp, both fetch — doubling request rate on volunteer shared hosting, the
exact thing §2 claims is "untouched." Worse: the breeder loop's error path
(`cli.py:136`) never calls `put_snapshot`, so a *failing* breeder URL has no
rate limit at all. Needs an `fcntl.flock` held by both `gw run` and
`/api/sweep`.

**`GET /` must not call `build_dashboard()`.** That function writes the file
(`cli.py:190`) and `dashboard.py:264` stamps `datetime.now()` into the masthead,
so every page load produces different bytes. `sweep.sh:19` guards its commit with
`git diff --quiet` — that guard becomes permanently false, so every sweep commits
and pushes forever. Split into `collect()` and a caller that writes.

**`KeepAlive: true` plus an occupied port is a silent infinite respawn loop.**
Boolean `KeepAlive` restarts on *every* exit including `EADDRINUSE`, throttled to
one relaunch per 10s, logging to a file nobody configured — while an older copy
answers the browser and everything looks fine. Use
`KeepAlive: {SuccessfulExit: false}` with explicit `StandardOutPath`.

**The cron→launchd migration in §14 is a regression and the doc lists only the
upside.** LaunchAgents load into a logged-in GUI session: at the login window, or
after a reboot where nobody logged back in, the sweep does not run *at all*.
`cron` is a system daemon and runs regardless. The trade is "misses runs while
asleep" for "misses runs while logged out," and launchd coalesces multiple missed
calendar firings into one anyway. Keep cron.

**§12's concurrency analysis solves a problem this code doesn't have.** "The
sweep holds the longest writes" is false — `db.py` commits after every single
statement (lines 82, 91, 118, 141, 156) and the largest `snapshot.text` in the
live db is 3.7 KB. WAL is fine but it addresses nothing on the actual risk list.

---

## 2. The security and privacy engineer

**§9 and §11 contradict each other, and the loser is the household. [converged]**
§9 stores "the *actual sent text*" in `event.meta`. That text contains
`owner.phone` (`nudge.py:207`), `owner.household` (`:209`), `dog_history`, and
via the overlay a child's age. §11's non-negotiable omit list covers drafts and
note bodies — **it never mentions events.** The phase-4 event panel renders them,
`cli.py:190` writes the file, `sweep.sh` pushes it that night. Git history is not
revocable. Store a hash and the subject line, never the body.

**`live=False` is a deny-list guarding an auto-push.** `cli.py:38-45` merges the
whole `owner.local.yaml` overlay into `cfg`, and `render()` reaches into `owner`
freely. Add one field to a card, forget the guard, and cron publishes it within
hours. Invert it: build a redacted `cfg` at the call site so the static renderer
never *receives* the values, and add a test that greps the rendered artifact for
every value in `owner.local.yaml` and refuses to write on a hit.

**XSS here is full API access, and the sink is remote page text.**
`finding.excerpt` is verbatim text from any watched host (`fetch.py:91` →
`signal.py:97` → `dashboard.py:198`). It is escaped *today* by `e()`
(`dashboard.py:148`) — server-side only. The moment §10's `GET /api/events` feeds
client-side rendering, `e()` never runs, and because `X-GW` is a header that
same-origin JS sets trivially, an XSS from a compromised breeder site can drive
every write endpoint and read `/api/draft`. No CSP and no `X-Frame-Options` are
specified, so a hostile tab can also iframe the server and clickjack "Mark sent."
Needs a strict CSP, `frame-ancestors 'none'`, and `textContent` everywhere.

**`sweep.sh` commits the whole index, not the two named paths.** Line 20-22 does
`git add dashboard.html config.yaml` then a **bare** `git commit`, which commits
everything already staged. Use `git commit --only <paths>`. Also `.gitignore`
lists `state.db` but not `state.db-wal`, and §12 defers that to "later" — the
`-wal` file holds recent writes verbatim.

**The four volunteers are the ones who did not consent. [converged]**
§11's omit list covers the *owner's* data and says nothing about
`referral_contact` / `referral_email`. The tracked `dashboard.html` today
contains four live `mailto:` links and three volunteers' full names. "Private
repo" is a setting that can be flipped or shared.

**`GET /api/draft` returns a phone number and a child's age with no cache
control** — bookmarkable, in history, written to `~/Library/Caches`. Make it a
POST and set `Cache-Control: no-store` globally.

**Google Fonts, from a page rendering a child's age.** `dashboard.py:140-145`
hands Google the IP, UA and referrer on every load — and the link is in the
*committed* HTML, so it fires for anyone who ever opens the artifact.

---

## 3. The product designer

**The dashboard cannot add a breeder — the one write that grows the search stays
in the terminal. [converged]** §4 keeps `add-breeder` CLI-only to protect the
config comments. So at the exact moment the tool pays off — a referral desk
replies with three kennel names — the user must open a terminal and type three
invocations. That is the highest-value interaction in the product and the "key
interaction" surface refuses to do it.

**Nothing in the design has a date on it.** README calls club events "the real
back door"; `CLAUDE.md`'s first "useful next work" is parsing calendars into
structured dates; `REVIEW.md`'s final action is "put the September 13 health
clinic in the calendar." The proposal ships four tables and nine endpoints with
no upcoming-dates concept anywhere. The user opens a beautifully complete
dashboard on September 14 and the clinic was yesterday. One `commitment` table
and a "Next 60 days" strip outranks the entire checklist feature.

**The blanks guard fires after the email is already gone.** Real sequence: copy
draft → paste into Gmail → write the specific sentence *there* → send → return →
"Mark sent" is disabled because the textarea still holds the placeholder. The
guard blocks *bookkeeping* over a stale buffer, and the only escape is typing
filler to satisfy a regex — the exact behavior the rule exists to prevent. Worse
for HVGRC, whose `method: web_form` means there is no email to gate. Warn at
copy time, never block the log.

**`todo|done|na|blocked` cannot express "I checked, and the answer is bad."**
A sire with no final hip number is the most decision-relevant fact this tool can
produce and there is no cell for it. The user ticks `done` meaning "I did the
check" and reads it six weeks later as "hips are clear." Needs
`todo|pass|fail|waiting(since)|na`.

**The completeness % will mis-sort the board. [converged]** Nine of the fifteen
items are desk research doable on a stranger in ten minutes; five only exist for
breeders you actually talk to. So a breeder you idly clicked through reads 60%
while the one who replied warmly with a September litter reads 20% — and §6
proposes exactly that number as the sort key.

**Two visually identical cell strips on one card will mean opposite things.**
The clearance strip reads the OFA *record*; the new checklist strip reads the
user's own *ticks*. Six months on, a green cell is ambiguous: did OFA say that,
or did I? And the card grows past 1,000px inside a `minmax(330px,1fr)` grid.
Split into a summary card and a real record page at `/e/<key>`.

**"Needs you" becomes structurally incapable of reaching zero. [converged]**
Fourteen clubs on 45–90 day timers, plus blocked checklist items, in a queue
whose empty state says "Nothing needs you right now." A queue that is always full
is a queue you stop reading.

**The metrics that move for free are the ones the design surfaces.**
Completeness rises when you read a website; the log grows when cron runs. The
real scoreboard is four numbers — emails sent, replies received, events attended,
waitlists joined — and today three are zero and the fourth is one.

---

## 4. The pragmatist at the kitchen table

**The four emails are unsent, and the blocker is a missing 15-line file — not a
missing server.** Verified: the `contact` table has **zero rows**, and
`owner.local.yaml` **does not exist** — only the `.sample`. So every draft today
renders `[your phone]`, `[your household — who's home, kids and ages...]`,
`[have you owned dogs before? say so either way]`. **The drafts are not
sendable.** Meanwhile `nudge.py` already contains all six of `REVIEW.md`'s
pre-send fixes. The writing is done. The gap between "tool built" and "emails
sent" is one untracked file and about thirty minutes.

**Yes, this is the project eating itself, and the number that proves it is one.**
Nine endpoints, four tables, a fifteen-item checklist, WAL, a DNS-rebinding
defense and a LaunchAgent — to manage a pipeline containing **one breeder and
zero conversations**. The doc's own §1 says notes are "the single highest-value
datum… and it currently lives in the user's head." Nothing is in his head. No one
has been called.

**Phase 0 is misdiagnosed. [converged]** 30 alerts = 15 findings × 2 runs, and
the insert-per-sweep bug is real. But **12 of the 16 club entries have no email
address and `method: unknown`** (verified). No email will ever clear them and
neither will an upsert — you would be dismissing Greater Pittsburgh, eight hours
away, twice a day forever. Fix `due_clubs()` to skip clubs with no contact route
and the spam drops 15 → 3 today, permanently.

**October 2026 is already gone, and phases 1–5 are how you'd spend the window
discovering that. [converged]** Home Oct 15 → whelped ~Aug 20 → bred ~mid-June.
Those litters are on the ground and spoken for. The honest target is the April
2027 fallback, whose litters are bred in Dec–Jan — which makes the **December 5
Big E specialty**, already sitting in `config.yaml`, the anchor date of the
search.

**Portugal collapses the schedule, and there is one hard date: August 1.**
`ygrc` has `contact_lead_days: 75` against `target_home_date: 2026-10-15`, so its
window opens **2026-08-01** — four days out. Largest club in New England, and
Kaele already wrote in June, so it is a warm follow-up. Send before the flight.

**Three things genuinely earn their place, and none need HTTP.** The dismiss path
(a real gap — nothing in the codebase ever sets `dismissed = 1`; eight lines in
`cli.py`). Notes (worth having *before* the first call, so you can take them
during it; `gw note <key> "..."` plus one table). And the checklist *content* —
the best writing in the document, turning the vet geneticist's findings into
questions you ask on a call. Ship it as `docs/BREEDER_CHECKLIST.md`: zero code,
all of the value, available this week.

**The cheapest real improvement is one the proposal never mentions: stop sweeping
twice a day.** Six pages that change a few times a year, polled 730 times a year.
`REVIEW.md` #14 already said weekly. One crontab edit, 14× less alert volume,
kinder to volunteer hosting.

---

## 5. The data modeling skeptic

**The P0 upsert cannot execute, and the index that would enable it cannot be
created on the current db. [converged]** Tested against a copy of the real
`state.db`: `ON CONFLICT(key)` → `does not match any PRIMARY KEY or UNIQUE
constraint`; `CREATE UNIQUE INDEX ... WHERE kind='nudge'` → `UNIQUE constraint
failed: finding.key`, because 15 keys already have 2 rows each. And since
`connect()` runs `executescript` on **every** connection (`db.py:63`), that
failure bricks *every* `gw` command, not just the sweep. Correct order: dedupe
DML → partial index → upsert with a matching partial conflict target — gated on
a `PRAGMA user_version` bump, which `IF NOT EXISTS` cannot express.

**`state.db` has no durability path, and the documented one is broken.
[converged]** `CLAUDE.md` says the file is "committed by the GH Action." It is
not: `.gitignore:1` ignores it and `git add -A state.db …` exits 1 (verified),
which under Actions' `bash -e` fails the whole step — so `dashboard.html` and
`config.yaml` never commit either. Today that costs a re-baseline. Under this
design it costs every note, every checklist state and the entire contact history.

**"Additive `IF NOT EXISTS` means no migration tool" is false.** SQLite has no
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — it is a syntax error. The first time
you add a column you cannot express it idempotently, and `executescript` issues
an implicit COMMIT so a multi-statement migration is not atomic. You need the
`user_version` runner *before* the first schema change.

**`entity_state.key` as a bare TEXT PK collides clubs with breeders — and it is
reachable today.** `cmd_add_breeder` checks the new key only against
`cfg["breeders"]` (`cli.py:304`); nothing checks club keys, so
`gw add-breeder "Yankee Goldens" --key ygrc` succeeds right now. `log_contact`
keys on `target_key` alone, so one `gw contacted ygrc` resets both clocks. Use a
`(kind, key)` composite everywhere.

**Renaming a breeder key silently rewinds it to zero.** All state orphans under
the old key, the new key re-seeds at config `status:`, and the `snapshot` key
`breeder:<old>:0` orphans too — so `if not prev: baseline stored; continue`
fires and **a litter announcement live on the page at rename time is never
scored.** That is a missed litter, the one failure the tool exists to prevent.

**Nudges still can't reach zero after the upsert. [converged]**
`build_findings` only ever adds; nothing retracts a nudge once contact is logged.
The 15 rows in the db today will render forever. Either reconcile
(`dismissed=1 WHERE key NOT IN (<due>)`) or — better — compute nudges at render
time and drop them from `finding` entirely, leaving that table to mean only "the
world changed."

**The `notified` flag on an upserted row has no correct setting.** Leave it and
a club silent for 200 days never pings again; clear it and you have the current
bug minus row growth. The doc's "re-notify every N days" has nowhere to live —
the row carries no last-notified timestamp, and `found_at` is doing double duty.
Needs `last_notified_at`, i.e. the ADD COLUMN that needs the migration runner.

**Checklist item ids in code + `(key,item)` PK means a rename discards completed
work** — the verified eye clearance evaporates and reappears as `todo`, which the
user may trust. Plus `done/(total-na)` divides by zero on an all-`na` entity.

---

## 6. The breeder-relations domain expert

**There is no LITTER entity, and that is the central modeling error.
[converged]** Clearances do not belong to kennels. They belong to individual
dogs, and the only dogs that matter are the sire and dam of *one specific
litter*. `ofa_check` is keyed on `kennel_prefix` and `clearance_strip()` renders
one strip per breeder — so "Meirzah: Hips On file" is a statement about an
arbitrary dog in a kennel that may have thirty. A breeder with a spectacular 2019
dam and a sloppy 2026 breeding scores identically. **The design's own
`names_match_litter` checklist item is the tell: it is a checkbox trying to paper
over a missing table.**

**The sire is usually not the breeder's dog.** Serious show breeders use another
kennel's stud constantly, shipping chilled or frozen semen. Half the clearances
you need live at a kennel you are not tracking. A breeder-rooted entity graph
structurally cannot hold the sire.

**The pipeline is a sales funnel, not a placement process.** What actually
happens between `waitlist` and a puppy: breeding planned → progesterone timing →
confirmed pregnant (ultrasound ~28d, x-ray ~55d for count) → whelped → 3-week
update → **pick order assigned** → 7–8 week temperament evaluation and matching →
go-home → a contract relationship for the dog's life. That is six months of state
with no rows. And `waitlist` as a binary is wrong: the datum is *pick number on a
named litter*, intersected with the sex constraint. "On the list" at #5 for
females in a litter of seven is not the same fact as #2, and only one of them
means you get a dog.

**`deposit` is not a stage, and the design has it backwards.** Most good breeders
take a deposit to *join* the list, before any litter exists — so it sits before
`waitlist`, not after `visited`. The real fields are amount, date, refundable
(usually not), and **transferable to the next litter** (usually yes, and that is
the question to ask). §6 also puts `contract_reviewed` in the *Relationship*
block, after `video_or_visit` — money moves before that in a real search.

**The cadence is how you get quietly blacklisted.** 30 days on breeders and 45 on
clubs is a clock; relationship contact is event-driven. Real rhythm: intro, then
**one** polite follow-up at ~2 weeks, then stop. Silence is an answer. The single
highest-value missing field is `next_contact_at`, set from what the breeder
actually said ("check back after Tessa's next season, around October"). That
trumps every interval. Second missing concept: *do I have anything new to say* —
a timer firing at a volunteer with no new information is pure goodwill burn.

**Most of a real search is inbound, and the design has one write path.**
`db.contact` already has a `direction` column and nothing ever writes `'in'`. The
most valuable inbound event — a referral desk replying with three kennel names —
has no path at all, and referral **provenance** is the strongest opening line you
will ever have ("Rose at CRVGRC suggested I write to you"). Also `last_contact()`
doesn't filter by direction, so *their* reply resets *your* outbound clock, which
is backwards. What every relationship needs is one field: **whose court is the
ball in.** "They asked me a question three days ago" is a five-alarm state that
the current model renders as "recently contacted, all good."

**`ofa_eyes_current` is not checkable at breeder level.** CAER currency is
defined relative to a *breeding date*, which a breeder does not have and a litter
does. Once ticked `done` it is silently wrong twelve months later. Never let a
human tick a box whose truth expires — store the dated fact on the dog and derive
the state.

**Two live cadence bugs.** `contact_lead_days: 75` on Yankee opens the window
2026-08-01; after Oct 15 passes, `date.today() < opens` is false forever, so the
near-term template — *"We're hoping for autumn"* — fires at that volunteer every
30 days indefinitely, reading in February like someone who never updated their
form letter. And `target_fallback_date: 2027-04-15` appears **nowhere in the
code**; nothing ever rolls the target forward.

**What a breeder would think if they saw this screen.** The one-click generator
on every card is the problem, not the templates: `NEAR_TERM_CLUB_TEMPLATE` asks
specifically for someone else's fallen-through deposit, and fired at thirteen New
England clubs in a week it is a mail merge — these volunteers overlap and talk.
Individually damning: `priority: high|normal|low` applied to people doing you a
favor; the stage `deposit — "Money down"` (you are being chosen, not
purchasing); storing the verbatim text of everything you told them; and above
all the `SPECIFIC` placeholder — documentary proof that the one personal sentence
is a slot in a form.

**`placed` is not terminal; the missing state is `withdrawn`.** When you accept a
puppy you owe every other breeder and volunteer a short note releasing your spot.
In a community this small, the people you ghosted are the people you need in five
years — or next spring when this litter doesn't work out.

---

# Ranked verdict

**Do this week, and it outranks everything below**

1. Write `owner.local.yaml`. Until it exists every draft is unsendable
   boilerplate. Fifteen lines; the sample is already there.
2. Send Yankee **before August 1** — its lead window opens then and Kaele's June
   note makes it a warm follow-up, not a cold open.
3. Send SBGRC, CRVGRC, HVGRC. Fill the `SPECIFIC` blank by hand each time.
4. Put the September 13 HVGRC health clinic and the **December 5 Big E
   specialty** in a real calendar.
5. Say the honest date out loud to the household: **spring 2027**, not October.

**Fix in the tool, this evening, ~1 hour total**

6. `due_clubs()` skips clubs with no contact route. Spam 15 → 3, permanently.
7. Dedupe the 30 existing nudge rows, then upsert — in that order, behind a
   `user_version` migration runner, or `connect()` throws and bricks every
   command.
8. `gw dismiss <id>` — the acknowledge path that has never existed.
9. Drop the sweep to weekly in crontab.
10. Remove `state.db` from `watch.yml`'s add list; fix `sweep.sh` to
    `git commit --only`; add `state.db-wal`/`-shm` to `.gitignore`; correct
    `CLAUDE.md`'s false claim that the Action commits the database.
11. Fix the Yankee near-term template firing forever after the target date
    passes, and make `target_fallback_date` actually roll the target forward.

**Before writing one line of server code**

12. Decide the litter/dog model. Clearances belong to dogs, not kennels; the
    sire usually isn't the breeder's dog. Everything in §5 and §6 is built on
    the wrong root entity, and it is much cheaper to fix on paper.
13. Answer §16 Q1 (does the static mirror survive) — it determines whether the
    dual-mode renderer needs to exist at all.
14. Ship `docs/BREEDER_CHECKLIST.md` as prose. It is the best content in the
    design and it needs no code, no server and no tables.

**If and when the server is actually built**

15. Per-request SQLite connections; `(kind, key)` composite keys; a sweep
    mutex; `collect()` split from `build_dashboard()`; strict CSP with
    `frame-ancestors 'none'`; redacted `cfg` built at the call site with a test
    that greps the artifact; never persist sent email bodies.
