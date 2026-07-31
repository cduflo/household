"""Contact cadence.

Every New England club gates litter listings behind a volunteer's inbox. Nothing
to scrape, so the automation tracks staleness instead: when a club or breeder has
gone quiet past its interval, it surfaces as a follow-up with a draft ready.

Drafts are drafts. Nothing sends itself. Breeders screen buyers harder than
buyers screen breeders and they can spot a mail merge instantly -- a form letter
is the fastest way onto the ignore pile. The automation's job is to make sure
you never forget to write; the writing stays yours.
"""
import time
from datetime import date, timedelta

from . import model

DAY = 86400

SEASONS = {(3, 4, 5): "spring", (6, 7, 8): "summer",
           (9, 10, 11): "autumn", (12, 1, 2): "winter"}


def days_since(ts):
    return (time.time() - ts) / DAY


def _parse_date(raw):
    if not raw:
        return None
    try:
        y, m, d = (int(x) for x in str(raw).split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def season_of(d):
    return next(name for months, name in SEASONS.items() if d.month in months)


def effective_target(cfg, today=None):
    """The date the search is actually working toward right now.

    `target_home_date` is an intention and it expires. Nothing used to roll it
    forward, so once it passed, every window computed against it was measured
    from a date in the past -- which is why the Yankee near-term ask, the one
    that says "we're hoping for autumn", would have kept firing at an unpaid
    volunteer every 30 days through the following winter.

    `target_fallback_date` exists in config for exactly this and was referenced
    nowhere in the code. Returns None when both have passed: better to aim at
    nothing and say so than to keep quietly aiming at yesterday.
    """
    today = today or date.today()
    prefs = cfg.get("preferences", {})
    for raw in (prefs.get("target_home_date"), prefs.get("target_fallback_date")):
        d = _parse_date(raw)
        if d and today <= d:
            return d
    return None


def has_contact_route(club):
    """Is there anywhere to actually send this?

    Twelve of the sixteen club entries carry no address and `method: unknown`.
    Treating those as "overdue" generated a nag twice a day for something that
    cannot be acted on -- you cannot write to Greater Pittsburgh GRC, eight
    hours away, without first finding an address for it.
    """
    if club.get("method") == "reference":
        return False                       # a document, not a person
    if club.get("referral_email"):
        return True
    return club.get("method") == "web_form"


def unroutable_clubs(cfg):
    """Clubs with no contact route yet.

    Surfaced separately rather than dropped. These are research tasks -- find
    the referral address -- and silently skipping them would quietly lose ten
    real clubs off the board.
    """
    return [c for c in cfg.get("clubs", [])
            if c.get("method") != "reference" and not has_contact_route(c)]


def due_clubs(con, cfg, today=None):
    """Which clubs need a note now.

    Two models, because the clubs work two different ways.

    A fixed interval suits clubs that keep a standing list you can join. Yankee
    told us in writing that they do not: breeders list only when a litter is
    within a few weeks, and the instruction is to write about two months before
    you want a puppy home. Polling them on a 45-day timer from a year out
    produces nothing but a polite "too soon" and some goodwill damage. For those
    clubs set `contact_lead_days` and the trigger becomes a date, not a
    countdown.
    """
    from . import crm, db

    today = today or date.today()
    out = []
    target = effective_target(cfg, today)

    for club in cfg.get("clubs", []):
        if not has_contact_route(club):
            continue
        state = crm.get_state(con, "club", club["key"]) or {}
        if (state.get("stage") or "new") in model.QUIET_STAGES:
            continue

        arrived, on = _scheduled(state, today)
        if arrived is not None:
            if arrived:
                out.append({"club": club, "days": None,
                            "reason": f"you said you'd check back on {on}"})
            continue

        last = db.last_contact(con, club["key"])
        lead = club.get("contact_lead_days")

        if lead:
            # A date-triggered club is silent unless there is a live target to
            # measure from. Once both target dates are behind us there is
            # nothing to ask for, and the window must close rather than stay
            # open forever.
            if not target:
                continue
            opens = target - timedelta(days=lead)
            if today < opens:
                continue                       # too early — writing now wastes the ask
            if last and days_since(last["at"]) < 30:
                continue
            out.append({"club": club, "days": None,
                        "reason": f"inside the {lead}-day window before {target.isoformat()}"})
            continue

        interval = club.get("recontact_days", 45)
        if last is None:
            out.append({"club": club, "days": None, "reason": "never contacted"})
        elif days_since(last["at"]) >= interval:
            out.append({
                "club": club,
                "days": round(days_since(last["at"])),
                "reason": f"{round(days_since(last['at']))} days since last contact",
            })
    return out


def _scheduled(state, today):
    """An explicit date the other side gave you, if it has arrived.

    Returns (arrived, iso) or (None, None) when nothing is scheduled. A breeder
    who says "check back after Tessa's next season, around October" has told you
    the cadence; an interval timer firing in the meantime is goodwill burn, and
    a timer firing *instead* of the date they named is worse.
    """
    raw = (state or {}).get("next_contact_on") or ""
    when = model.parse_iso(raw)
    if not when:
        return None, None
    return today >= when, raw


def due_breeders(con, cfg, interval_days=30, today=None):
    """Breeders needing a follow-up.

    Reads the stage from `entity_state`, not from config `status:`. Config is
    seed-only, so a breeder moved to `out` in the dashboard must stop generating
    nudges -- otherwise every stage change made in the UI is invisible here and
    the board nags forever about someone you already closed.
    """
    from . import crm, db

    today = today or date.today()
    out = []
    for b in cfg.get("breeders", []):
        state = crm.get_state(con, "breeder", b["key"]) or {}
        stage = state.get("stage") or "new"
        if stage in model.QUIET_STAGES:
            continue

        arrived, on = _scheduled(state, today)
        if arrived is not None:
            if arrived:
                out.append({"breeder": b, "days": None,
                            "reason": f"you said you'd check back on {on}"})
            continue                       # a named date overrides the interval

        last = db.last_contact(con, b["key"])
        if last is None:
            if stage in model.CONTACTED_STAGES:
                continue
            out.append({"breeder": b, "days": None, "reason": "not yet contacted"})
        elif days_since(last["at"]) >= interval_days:
            out.append({
                "breeder": b,
                "days": round(days_since(last["at"])),
                "reason": f"{round(days_since(last['at']))} days quiet",
            })
    return out


CLUB_TEMPLATE = """Subject: Golden Retriever puppy referral — {owner_name}, {owner_base}

Hi {contact},

I'm {owner_name}, in {owner_base}, writing about {club_name}'s puppy referral.

The short version: {dog_history}. We're ready for another, we're looking for a companion home rather than a show prospect, and we're prepared to wait for the right litter. {sex_line}

About us — {household}

What we want is {temperament}. We're {lifestyle}.

I know to check OFA for hips, elbows, eyes and heart on both parents. The thing I care most about and can't read off a certificate is longevity, so when I talk to a breeder I plan to ask how long the grandparents lived and what they died of. If that's the wrong question, I'd like to know what a better one is.

{ask_line}{event_line}

{vet_line}Thank you for volunteering your time to do this.

{owner_name}
{owner_phone}
"""

# Fall 2026 is a different ask than "put us on your list."
#
# A puppy going home in October was born in August. Those litters are on the
# ground or in utero right now, which means the question is no longer "may we
# join your waitlist" -- it's "is there an unplaced puppy in a litter that
# already exists." Good breeders do have them: deposits fall through, a family's
# circumstances change, and a breeder who kept back two picks releases one. That
# is a specific question and it deserves a short, specific email.
NEAR_TERM_CLUB_TEMPLATE = """Subject: Golden puppy — {owner_name}, {owner_base} — hoping for {season}

Hi {contact},

I'm {owner_name}, in {owner_base}. I know the usual answer is to get on a list and wait, and we're prepared to do that. But I want to ask the narrower question first, in case it's worth asking: does any {club_name} breeder have an unplaced puppy in a litter already on the ground, or one due in the next few weeks?

We're hoping for {season}. I understand that's compressed, and that it usually means someone else's deposit fell through rather than a litter planned around us. If the answer is no, I'd genuinely rather be told so and put on a list for {next_season} — we're in no rush and {next_season} suits us fine.

Us, briefly: {dog_history}. {household}

What we want is {temperament}. {sex_line}

I know to check OFA for hips, elbows, eyes and heart on both parents, and I'd ask about longevity in the line — how long the grandparents lived and what they died of. We can drive; anywhere in New England, New York or eastern Pennsylvania is reachable for the right puppy.

Thank you for volunteering your time to do this.

{owner_name}
{owner_phone}
"""

BREEDER_TEMPLATE = """Subject: Inquiry about a future litter — {owner_name}, {owner_base}

Hi{contact_clause},

I came across {kennel_name} and wanted to introduce myself rather than just ask what's available. I'm {owner_name}, in {owner_base}.

{specific_line}

{dog_history_cap}. We're looking for a companion home placement — not a show prospect, and not looking to co-own. I understand that's a different conversation than the one you have with someone wanting a ring prospect. {sex_line}

About us — {household}

What we're hoping for is {temperament}. This would be a dog that comes everywhere with us; we're {lifestyle}.

Two things I'd want to ask you if we get that far: how long the grandparents on both sides lived and what they died of, and how you paired the parents on the DNA panel — PRA1, PRA2, ichthyosis, NCL. I'd rather ask that now than pretend I don't care about it.

We're hoping for autumn but spring is entirely fine — we'd rather wait for the right litter than push a timeline. {vet_line}Happy to make the drive to meet you and your dogs.

{owner_name}
{owner_phone}
"""

FALLBACK = {
    "household": "[your household — who's home, kids and ages, the yard situation]",
    "temperament": "[what you actually want in the dog]",
    "lifestyle": "[how the dog fits your week]",
}

# The one thing that never gets filled in automatically. This line is what
# separates a letter that gets answered from one that gets deleted, and it has
# to be true, so it stays your job.
SPECIFIC = ("[ONE specific, true sentence about THEIR dogs — a particular dam, a title, "
            "something in their program you actually noticed. Do not skip it and do not fake it.]")


def _fields(cfg):
    owner = cfg.get("owner", {})
    prefs = cfg.get("preferences", {})
    history = owner.get("dog_history", "")
    sex = prefs.get("sex")
    flexible = prefs.get("sex_is_flexible", True)
    if not sex:
        sex_line = ""
    elif flexible:
        sex_line = (f"We'd lean toward a {sex}, though we're not rigid about it — "
                    "we'd rather have the right puppy than the right sex.")
    else:
        # Firm and up front. A hedged hard requirement is the worst of both:
        # it reads as flexible, so a breeder works you up the list and finds the
        # mismatch late, which wastes their time and costs you the goodwill.
        sex_line = (f"One thing I'll say plainly so you're not matching us to the wrong "
                    f"litter: we're set on a {sex}. I know that narrows things and costs us "
                    "position on a list, and we'd rather wait than have you work around it.")
    return {
        "owner_name": owner.get("name", "[your name]"),
        "owner_base": owner.get("base", "[your town]"),
        "owner_phone": owner.get("phone", "[your phone]"),
        "household": owner.get("household") or FALLBACK["household"],
        "temperament": owner.get("temperament") or FALLBACK["temperament"],
        "lifestyle": owner.get("lifestyle") or FALLBACK["lifestyle"],
        "sex_line": sex_line,
        "dog_history": history or "[have you owned dogs before? say so either way]",
        "dog_history_cap": (history[0].upper() + history[1:]) if history else
                           "[have you owned dogs before? say so either way]",
        "vet_line": ("Happy to provide our vet as a reference, and to answer anything else "
                     "about our home. " if owner.get("vet_reference") else ""),
    }


def _seasons_for(cfg, today):
    """What to call the target window in prose.

    These were hardcoded as "autumn" and "spring", which is fine in July 2026
    and reads like an unmaintained form letter by the following February --
    exactly the impression this template exists to avoid.
    """
    target = effective_target(cfg, today)
    season = season_of(target) if target else "whenever suits a litter"
    fallback = _parse_date(cfg.get("preferences", {}).get("target_fallback_date"))
    if fallback and target and fallback > target:
        nxt = season_of(fallback)
    elif target:
        nxt = season_of(target + timedelta(days=182))
    else:
        nxt = "the season after"
    return season, nxt


def draft_near_term_club_email(club, cfg, today=None):
    today = today or date.today()
    season, next_season = _seasons_for(cfg, today)
    f = _fields(cfg)
    return NEAR_TERM_CLUB_TEMPLATE.format(
        contact=(club.get("referral_contact") or "there").split(" (")[0].split()[0],
        club_name=club["name"],
        season=season,
        next_season=next_season,
        **{k: v for k, v in f.items() if k in
           ("owner_name", "owner_base", "owner_phone", "household",
            "temperament", "sex_line", "dog_history")},
    )


def draft_club_email(club, cfg, known_kennels=None):
    """Ask the volunteer to edit a list rather than compose one.

    Referral volunteers are unpaid and triaging. Handing them two names to react
    to is a smaller ask than "who should I talk to", and it shows you did
    something before writing.
    """
    f = _fields(cfg)
    known = known_kennels or [b["name"] for b in cfg.get("breeders", [])][:3]
    if known:
        f["ask_line"] = (f"I've found {' and '.join(known)} so far — "
                         "would you add or subtract from that list?")
    else:
        f["ask_line"] = ("I haven't got a shortlist yet. If there are breeders in the region "
                         "you'd point me toward, I'd be grateful for the steer.")

    event = club.get("next_event")
    f["event_line"] = (f" I'm also planning to come to {event}, and I'd be glad to "
                       "introduce myself there." if event else
                       " And if there's a club event worth coming to, I'd like to be there.")

    return CLUB_TEMPLATE.format(
        contact=(club.get("referral_contact") or "there").split(" (")[0].split()[0],
        club_name=club["name"],
        **f,
    )


def draft_breeder_email(breeder, cfg):
    f = _fields(cfg)
    contact = breeder.get("contact_name", "")
    return BREEDER_TEMPLATE.format(
        contact_clause=f" {contact}" if contact else " there",
        kennel_name=breeder["name"],
        specific_line=SPECIFIC,
        **f,
    )


def build_findings(con, cfg):
    """Reconcile overdue contacts against the board.

    Upsert, not insert. The original was a plain INSERT per due entity per
    sweep, so every run minted fresh unnotified rows and Telegram re-sent the
    same fifteen overdue clubs twice a day. Then retire anything no longer due,
    because a queue that only grows is one you stop reading.
    """
    from . import db
    live = []

    for item in due_clubs(con, cfg):
        club = item["club"]
        who = club.get("referral_email") or club["url"]
        key = f"nudge:{club['key']}"
        db.upsert_nudge(con, key, club["name"], club["url"], 2,
                        f"Referral contact due — {item['reason']}. Send to {who}.")
        live.append(key)

    for item in due_breeders(con, cfg):
        b = item["breeder"]
        key = f"nudge:{b['key']}"
        db.upsert_nudge(con, key, b["name"], b.get("site", ""), 1,
                        f"Breeder follow-up due — {item['reason']}.")
        live.append(key)

    db.reconcile_nudges(con, live)
    return live
