"""The vocabulary of the search: stages, checklists, ratings, dated clearances.

Pure data and pure functions. No database, no HTTP, no rendering — so the rules
that matter can be tested directly and the same definitions drive the CLI, the
server and the dashboard without drifting apart.

Two decisions here came out of the design review and are load-bearing:

**Clearances belong to dogs, not kennels.** A kennel is not screened; two
individual dogs are, and the only two that matter for a puppy are the sire and
dam of one specific litter. Hanging a clearance strip off a breeder says
"Meirzah: hips on file" about an arbitrary dog in a kennel that may have thirty,
and scores a breeder with a spectacular 2019 dam identically to one with a
sloppy 2026 breeding. Note also that the sire is frequently *not* the breeder's
dog — show breeders use outside studs constantly — which is why `dog` carries a
nullable `breeder_key` and is never reached through a kennel.

**A checkbox cannot hold a fact that expires.** Eye clearances are annual. A
ticked box saying "eyes: done" is silently wrong twelve months later, and worse,
it is trusted. So clearances are stored as dated results and their state is
*derived* every time it is read.
"""
from datetime import date

# ---------------------------------------------------------------- stages
#
# Deliberately short. An earlier draft had twelve breeder stages; most had no
# moment at which a person would actually click them ("screening" happens while
# you read, nobody alt-tabs to record it) and two duplicated facts stored
# elsewhere. These are the states with a real transition behind them.

BREEDER_STAGES = ["new", "contacted", "talking", "waitlist", "deposit", "placed", "out"]
CLUB_STAGES = ["new", "contacted", "replied", "referred", "dormant"]

#: Stages that mean "stop chasing this" — no follow-up nudges.
QUIET_STAGES = {"placed", "out", "dormant"}

#: Stages that mean contact has already happened at least once.
CONTACTED_STAGES = {"contacted", "talking", "waitlist", "deposit", "placed", "replied", "referred"}

STAGE_LABELS = {
    "new": "Not contacted", "contacted": "Contacted", "talking": "In conversation",
    "waitlist": "On the list", "deposit": "Deposit down", "placed": "Puppy assigned",
    "out": "Closed", "replied": "Replied", "referred": "Sent names",
    "dormant": "Dormant",
}


def stages_for(kind):
    return BREEDER_STAGES if kind == "breeder" else CLUB_STAGES


def initial_stage(kind):
    return "new"


# ---------------------------------------------------------------- checklist
#
# Split into two lists on purpose. Nine of these are desk research you can do on
# a stranger in ten minutes; the rest only exist once someone is talking to you.
# Scoring them in one pool meant a breeder you idly clicked through outranked
# the one who wrote back with a September litter.

SCREEN = [
    ("line_classified", "Show or field line identified from titles"),
    ("site_reviewed", "Read their program, not just the puppy page"),
    ("coe_member", "GRCA Code of Ethics / club member"),
    ("scam_screen", "No scam markers: payment method, shipping, site age"),
]

DILIGENCE = [
    ("take_back", "Take-back-for-life clause in the contract"),
    ("longevity", "Asked how long the grandparents lived, and of what"),
    ("dna_pairing", "How the pair was made on the DNA panel, not just 'clear'"),
    ("rearing", "Raised in the house; ENS / Puppy Culture protocol"),
    ("matching", "They temperament-test and match, buyers don't pick"),
    ("breeding_frequency", "Litters per year, and how often this dam is bred"),
    ("video_or_visit", "Seen the dam with the litter, live"),
    ("contract_terms", "Deposit and contract terms in writing before money"),
    ("references", "Vet reference or a prior puppy buyer"),
    ("expectations", "What they want from you: updates, spay/neuter, health survey"),
]

CLUB_CHECKLIST = [
    ("intro_sent", "Introduction sent"),
    ("replied", "They replied"),
    ("shortlist_shared", "Gave them names to react to"),
    ("event_attended", "Met them at an event"),
]

#: A checked item can be four things, not two. "I checked and the answer is bad"
#: is the single most decision-relevant outcome and a done/todo box cannot hold
#: it — the user would tick `done` meaning "I did the check" and read it back
#: six weeks later as "this passed".
ITEM_STATES = ["todo", "pass", "fail", "waiting", "na"]


def checklist_for(kind, stage=None):
    """Screening items always; diligence only once there is a conversation.

    Showing all fourteen against a kennel you found ten minutes ago is how a
    checklist gets abandoned by the third breeder.
    """
    if kind == "club":
        return list(CLUB_CHECKLIST)
    items = list(SCREEN)
    if stage and stage not in ("new",):
        items += DILIGENCE
    return items


def checklist_progress(rows, kind, stage=None):
    """Returns (done, applicable, has_failure).

    `na` leaves the denominator, so marking things irrelevant cannot make a
    breeder look further along than they are. Guarded against the all-`na` case,
    which is exactly where a closed breeder ends up.
    """
    defined = {k for k, _ in checklist_for(kind, stage)}
    states = {k: v for k, v in rows.items() if k in defined}
    applicable = [k for k in defined if states.get(k) != "na"]
    done = [k for k in applicable if states.get(k) == "pass"]
    failed = any(states.get(k) == "fail" for k in defined)
    return len(done), len(applicable), failed


# ---------------------------------------------------------------- clearances
#
# The rules are GRCA's and OFA's, not ours. `ofa.audit` already encodes them for
# a parsed blob; these work on stored dated facts for a specific dog.

MIN_FINAL_AGE_MONTHS = 24
EYE_VALID_MONTHS = 12


def _months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def parse_iso(raw):
    if not raw:
        return None
    try:
        y, m, d = (int(x) for x in str(raw)[:10].split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def hip_elbow_state(result, exam_date, dob):
    """Finals require 24 months. OFA will not issue a number earlier, so a
    breeder quoting a younger evaluation is quoting a preliminary — which
    carries no number and is not a clearance."""
    if not result:
        return "todo", "Not on file"
    exam, born = parse_iso(exam_date), parse_iso(dob)
    if exam and born:
        age = _months_between(born, exam)
        if age < MIN_FINAL_AGE_MONTHS:
            return "fail", f"Preliminary — evaluated at {age} months, finals need 24"
    elif not exam:
        return "waiting", f"{result} — no exam date, confirm it was 24 months or older"
    return "pass", result


def eye_state(exam_date, asof=None):
    """CAER exams expire. GRCA expects one within twelve months of the breeding,
    so this is a fact with a shelf life and it is re-derived on every read."""
    asof = asof or date.today()
    exam = parse_iso(exam_date)
    if not exam:
        return "todo", "Not on file"
    months = _months_between(exam, asof)
    if months >= EYE_VALID_MONTHS:
        return "fail", f"Expired — exam {exam.isoformat()}, {months} months ago"
    return "pass", f"Current — {exam.isoformat()}"


def heart_state(result, exam_date):
    if not result:
        return "todo", "Not on file"
    return "pass", f"{result}" + (f" — {exam_date}" if exam_date else "")


def audit_dog(dog, asof=None):
    """Derive every clearance state for one dog. Never stored, always computed."""
    out = {}
    out["hips"] = hip_elbow_state(dog.get("hips"), dog.get("hips_date"), dog.get("dob"))
    out["elbows"] = hip_elbow_state(dog.get("elbows"), dog.get("elbows_date"), dog.get("dob"))
    out["eyes"] = eye_state(dog.get("eyes_date"), asof)
    out["heart"] = heart_state(dog.get("heart"), dog.get("heart_date"))
    return out


def audit_pairing(sire, dam, asof=None):
    """The clearance picture for an actual breeding.

    This is the unit that means something. A litter is only as cleared as its
    weaker parent, and a missing sire is not a neutral absence — the sire is
    usually another kennel's dog and is the half most often left unstated.
    """
    result = {"sire": None, "dam": None, "flags": [], "score": 0, "complete": False}
    for role, dog in (("sire", sire), ("dam", dam)):
        if not dog:
            result["flags"].append(f"No {role} recorded. Half the clearances are unknown.")
            continue
        result[role] = audit_dog(dog, asof)

    if not (sire and dam):
        return result

    passing = 0
    for trait in ("hips", "elbows", "eyes", "heart"):
        states = [result["sire"][trait][0], result["dam"][trait][0]]
        if all(s == "pass" for s in states):
            passing += 1
        else:
            for role in ("sire", "dam"):
                state, detail = result[role][trait]
                if state != "pass":
                    result["flags"].append(f"{role.capitalize()} {trait}: {detail}")
    result["score"] = passing
    result["complete"] = passing == 4

    for role, dog in (("sire", sire), ("dam", dam)):
        if not dog.get("chic"):
            result["flags"].append(
                f"{role.capitalize()} has no CHIC number. CHIC issues once all four "
                "breed screenings are on file.")
    return result


# ---------------------------------------------------------------- ratings

RATING_LABELS = {0: "Unrated", 1: "Poor", 2: "Weak", 3: "Worth pursuing",
                 4: "Strong", 5: "Top of the list"}


def clamp_rating(value):
    try:
        return max(0, min(5, int(value)))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- planning

def days_until(iso, today=None):
    d = parse_iso(iso)
    if not d:
        return None
    return (d - (today or date.today())).days


def upcoming(commitments, within_days=60, today=None):
    """Dates worth seeing on the front page.

    The single highest-value item in this whole search is a date on a calendar —
    a club health clinic is a room full of breeders, and referral volunteers rank
    people they have met. A tool that tracks everything except when to show up
    has automated the wrong ten percent.
    """
    today = today or date.today()
    out = []
    for c in commitments:
        n = days_until(c.get("on_date"), today)
        if n is None or n < 0 or n > within_days:
            continue
        out.append({**c, "days": n})
    return sorted(out, key=lambda c: c["days"])
