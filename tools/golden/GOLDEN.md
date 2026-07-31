# golden-watch

An autonomous sweep for a golden retriever puppy search out of West Hartford, CT.
Runs on a schedule, diffs the pages that matter, pings Telegram when something
looks like a litter, and keeps a dashboard of where you stand with every club and
breeder on the board.

---

## What I found before building this, and why it changed the design

I pulled the referral pages for every GRCA member club covering Connecticut and
New England. The finding that matters:

**None of them publish litters on the open web.** Not one. Every single club
routes litter listings through a volunteer's inbox.

- Yankee GRC — no listings page at all; you email the referral desk, and they
  say outright that breeders only list when a litter is imminent
- Southern Berkshire GRC — page explains the program, then hands you an address
- CT River Valley GRC — same
- Hudson Valley GRC — a contact form and a secretary in Middletown

So the "scrape the club sites for litters" plan was dead on arrival. What this
tool does instead:

1. **Watches breeder kennel sites**, which *do* announce planned breedings,
   confirmed pregnancies and go-home dates. That is the only place litter news
   appears publicly, and it is why the breeder list is the important one.
2. **Watches club event calendars**, because the events are the real back door.
   Referral volunteers rank people they have met. A fun match or a health clinic
   puts you in a field with thirty golden people and no cost of entry.
3. **Tracks referral-contact staleness** and tells you when to write again,
   rather than pretending it can scrape an inbox.
4. **Audits OFA clearances**, which is the part that actually filters.

## Verified referral contacts

In `contacts.local.yaml`, which is gitignored — this repo is public and these are real volunteers who never agreed to be republished. Checked July 2026 — volunteers rotate, so
re-verify off the club page before you send.

| Club | Territory | Contact | How |
|---|---|---|---|
| _(four clubs)_ | CT / MA / NY | in `contacts.local.yaml`, untracked | email |

Re-verified against GRCA's official club map, July 2026: fourteen member clubs
cover the northeast, and **Vermont, New Hampshire and Rhode Island have none**.
The "Green Mountain GRC" that surfaces in AKC's club search is not on GRCA's
roster. Ten of the fourteen have no referral address published — the dashboard
lists those separately as research tasks rather than nagging you about them,
since there is nowhere to send anything until you find one.

Southern Berkshire is your closest club by a wide margin and its calendar is
already on the watchlist: hunt tests and WC/WCX at Nod Brook WMA, dock diving,
a fun match at Tails U Win in Manchester, public education at the Big E in
September. Hudson Valley runs an all-breed health clinic in September, which is
a room full of breeders getting hips and hearts done.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m gw.cli run --force   # first run stores baselines, finds nothing
```

Personal details go in `owner.local.yaml` (untracked — copy
`owner.local.yaml.sample`). **Until that file exists every draft renders
`[your phone]` and `[your household]` placeholders and is not sendable.**

Telegram: make a bot with @BotFather, message it once, then read your chat id
from `https://api.telegram.org/bot<TOKEN>/getUpdates`. Put both in `config.yaml`
or export `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

Schedule it. Twice a week is plenty — these are six pages that change a few
times a year, and the sites are volunteer-run on cheap shared hosting:

```
0 7 * * 1,4  /path/to/golden-watch/scripts/sweep.sh
```

`sweep.sh` runs the sweep, then snapshots `state.db` into iCloud (14 kept) and
alerts Telegram if the sweep fails. Nothing is pushed to git: the database holds
notes, contact history and rendered drafts carrying household details, and that
does not belong in git history even in a private repo.

## The dashboard

```
gw serve --open         the command station at http://127.0.0.1:8420/
./scripts/install-agent.sh   keep it running, and after a reboot
```

Everything day-to-day happens there: draft and copy an email, log what you sent
and what came back, move a breeder's stage, tick the screening checklist, rate
them, add a litter with its sire and dam, and put the dates that matter in the
next-60-days strip. The CLI below is for the cron sweep and one-off lookups.

## Commands

```
gw run                  sweep, alert, rebuild the offline dashboard copy
gw run --force          ignore the 12-hour minimum interval
gw dash                 rebuild the dashboard offline
gw clubs                who is overdue for a note
gw draft club sbgrc     print an email draft
gw draft breeder <key>  same, for a breeder
gw contacted sbgrc      log that you sent it; resets the clock
gw ofa Meirzah          look up a kennel prefix and audit what comes back
gw ofa --text "GR-118822G27F-VPI ..."   audit a claim a breeder emailed you
gw add-breeder "Name" --prefix Kennel --site https://...
gw dismiss <id>         acknowledge a finding
```

## Show lines vs field lines

`preferences.line: show` in the config. Goldens are one breed but two
populations that split decades ago — American conformation lines run blockier,
lighter, lower drive; field lines run leaner, darker, with a work ethic that
does not switch off. For a family companion in a house where two people work
from home, show is the fit.

The titles on the parents tell you which you're looking at before anyone
describes a temperament to you:

```
gw line --url https://somekennel.com/our-dogs
gw line --text "GCH CH Sunfire's Something Grand OS  x  CH Meirzah Aria RN JH"
```

`CH / GCH / BISS` are conformation. `FC / AFC / MH` are field. The trap is that
`JH, WC, WCX, CD`, agility and dock titles are earned by both populations and
prove nothing about line — a lot of people read a JH as a field marker and it
isn't. The classifier knows the difference and will say "ask directly" rather
than guess.

It also flags marketing vocabulary. "English cream" is a sales term, not a
variety; cream sits inside the English standard and the US conformation ring
favors mid-gold, so heavy use of the phrase correlates with volume sellers
rather than show programs.

One practical note on targeting show breeders: they are harder to get puppies
from, and some want co-ownership or first pick for the ring. Being clear that
you want a **pet-quality puppy from a show litter** actually helps — every show
litter has puppies that won't be campaigned, and those breeders need good pet
homes for them.

## The clearance audit

The dashboard's signature row — four stamped cells for hips, elbows, eyes and
heart — hangs off a **litter**, not a kennel, and reads dated records rather
than the breeder's claim.

That distinction is the whole point. A kennel is not screened; the sire and dam
of one specific breeding are, and those are the only two dogs that matter for
the puppy you are being offered. A kennel-level strip scores a breeder with a
spectacular 2019 dam identically to one with a sloppy 2026 breeding. Note also
that the sire is frequently *not* the breeder's dog — show breeders use outside
studs constantly — so half the clearances usually live at a kennel you are not
tracking.

Three checks that catch the common misrepresentations:

- **Hips and elbows before 24 months are preliminaries, not clearances.** OFA
  will not issue a final number earlier. Prelims carry no number at all, so a
  breeder quoting one as a clearance is either confused or counting on you being.
- **Eye exams expire.** ACVO/CAER results are annual; GRCA expects one within
  twelve months of the breeding. A 2019 eye clearance on a 2026 litter is a
  historical document.
- **No CHIC number is a question.** CHIC issues only once all four breed-required
  screenings are on file.

`gw ofa --text` is the one you'll use most: paste what a breeder emails you and
check the arithmetic before you reply.

## What this does not do

**It does not send email.** That is deliberate and it is the single most
important design decision here. Breeders screen buyers far harder than buyers
screen breeders, and a mail-merge inquiry — especially one that leads with price
— is the fastest route to being ignored by exactly the people you want. `gw draft`
gives you a skeleton with the household details blanked out and one required line
about *their* dogs. Fill those in yourself, every time. The automation makes sure
you never forget to write; the writing stays yours.

It also does not scrape Facebook (where a lot of litter chatter actually lives
and where scraping will get you banned), does not touch marketplaces, and does
not pretend the OFA lookup is an API — OFA publishes no API, so when parsing
fails the tool hands you the search URL rather than a guess.

## Realistic expectations

Six to eighteen months on a waitlist at a good breeder. This tool does not
shorten that. It stops you from missing the window when it opens, and it keeps
you from wasting a spring on a broker with a nice website.
