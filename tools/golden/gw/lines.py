"""Tell show lines from field lines by reading the titles on the parents.

Goldens are one breed but two populations that diverged decades ago. American
conformation lines are blockier, lighter coated, and generally lower drive.
Field lines are leaner, darker, and bred for a work ethic that does not switch
off. Both are wonderful dogs. Only one of them is what somebody means when they
say "steady family companion who naps under the desk while I take a call."

The tell is the alphabet in front of and behind the registered name. Breeders
put it in the pedigree because it is the currency of their world, which makes it
free signal for you.
"""
import re

# Conformation. CH before the name, GCH and its tiers, specialty wins.
SHOW_TITLES = {
    "CH": "Champion",
    "GCH": "Grand Champion",
    "GCHB": "Grand Champion Bronze",
    "GCHS": "Grand Champion Silver",
    "GCHG": "Grand Champion Gold",
    "GCHP": "Grand Champion Platinum",
    "BISS": "Best in Specialty Show",
    "BIS": "Best in Show",
    "NSS": "National Specialty",
}

# Field. These are earned in cover and water, not on a mat.
FIELD_TITLES = {
    "FC": "Field Champion",
    "AFC": "Amateur Field Champion",
    "NFC": "National Field Champion",
    "NAFC": "National Amateur Field Champion",
    "MH": "Master Hunter",
    "SH": "Senior Hunter",
    "QA2": "Qualified All-Age",
}

# Earned by both populations. Presence proves nothing about line.
NEUTRAL_TITLES = {
    "JH": "Junior Hunter",
    "WC": "Working Certificate",
    "WCX": "Working Certificate Excellent",
    "CD": "Companion Dog",
    "CDX": "Companion Dog Excellent",
    "UD": "Utility Dog",
    "OTCH": "Obedience Trial Champion",
    "RN": "Rally Novice",
    "RA": "Rally Advanced",
    "RAE": "Rally Advanced Excellent",
    "MACH": "Master Agility Champion",
    "PACH": "Preferred Agility Champion",
    "NA": "Novice Agility",
    "OA": "Open Agility",
    "AX": "Agility Excellent",
    "DJ": "Dock Junior",
    "DS": "Dock Senior",
    "DM": "Dock Master",
    "FCAT": "FastCAT",
    "CGC": "Canine Good Citizen",
    "TDI": "Therapy Dog",
    "VC": "GRCA Versatility Certificate",
    "VCX": "GRCA Versatility Excellent",
    "OS": "GRCA Outstanding Sire",
    "OD": "GRCA Outstanding Dam",
}

# Marketing vocabulary that correlates with volume operations rather than
# conformation programs. Not proof of anything, but worth a second look.
CAUTION_TERMS = [
    (r"\benglish\s+cream\b", "\"English cream\" is a sales term, not a variety. "
                             "Goldens are one breed and cream sits inside the English standard; "
                             "US conformation rings favor mid-gold. Heavy use of the phrase "
                             "correlates with volume sellers more than with show programs."),
    (r"\b(white|platinum|rare)\s+golden", "Color marketed as rare. There is no rare color in this breed."),
    (r"\bmini(ature)?\s+golden", "Miniature goldens are crosses, not goldens."),
    (r"\bakc\s+registered\b(?!.{0,40}(champion|conformation))", "AKC registration alone says nothing about quality; "
                                                               "it only means the parents were registered."),
]

# Word boundary matching so "CH" does not fire inside "CHIC" or "Chester".
_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5}\d?)(?![A-Za-z0-9])")


def extract_titles(text):
    found = {"show": [], "field": [], "neutral": []}
    for token in _TOKEN.findall(text or ""):
        if token in SHOW_TITLES:
            found["show"].append(token)
        elif token in FIELD_TITLES:
            found["field"].append(token)
        elif token in NEUTRAL_TITLES:
            found["neutral"].append(token)
    for bucket in found.values():
        bucket[:] = sorted(set(bucket))
    return found


def classify(text):
    """Return show | field | dual | unknown, plus the evidence."""
    t = extract_titles(text)
    show, field = len(t["show"]), len(t["field"])

    if show and field:
        line = "dual"
    elif show:
        line = "show"
    elif field:
        line = "field"
    else:
        line = "unknown"

    cautions = [why for pattern, why in CAUTION_TERMS
                if re.search(pattern, text or "", re.I)]

    return {
        "line": line,
        "show_titles": t["show"],
        "field_titles": t["field"],
        "neutral_titles": t["neutral"],
        "cautions": cautions,
        "note": _note(line, t),
    }


def _note(line, t):
    if line == "show":
        return f"Conformation program. Titles seen: {', '.join(t['show'])}."
    if line == "field":
        return (f"Field program. Titles seen: {', '.join(t['field'])}. "
                "Expect more drive than a pet home usually wants.")
    if line == "dual":
        return (f"Dual-purpose. Show: {', '.join(t['show'])} · Field: {', '.join(t['field'])}. "
                "Ask which side this particular litter leans toward.")
    if t["neutral"]:
        return (f"Performance titles only ({', '.join(t['neutral'])}) — earned by both "
                "populations, so this does not tell you the line. Ask directly.")
    return "No titles found. Ask for the sire and dam's registered names and look them up."


def matches_preference(classification, preferred):
    """preferred is 'show', 'field', or 'any'."""
    if preferred in (None, "any"):
        return True
    line = classification["line"]
    if line == "unknown":
        return None          # unresolved, not a rejection
    return line in (preferred, "dual")
