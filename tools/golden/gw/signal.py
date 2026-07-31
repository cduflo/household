"""Decide whether new text on a page is actually a litter announcement.

Runs on the diff, not the whole page, so a breeder site that permanently says
"we occasionally have puppies" never fires, but the day they add
"Sadie is due September 14" it does.

Scoring is deliberately transparent rather than clever. When an alert fires you
can read exactly which phrase caused it, which matters when you are deciding
whether to drop everything and send an email.
"""
import re

# (regex, points, why)
STRONG = [
    (r"\b(due|whelp(ed|ing)?|expect(ed|ing))\b.{0,40}\b(20\d\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", 4, "dated litter"),
    (r"\bpupp(y|ies)\s+(are\s+)?(available|ready|here)\b", 4, "puppies available"),
    (r"\bnow\s+accepting\s+(applications|deposits|inquiries)\b", 4, "applications open"),
    (r"\bwait\s*list\s+(is\s+)?(open|now open|accepting)\b", 4, "waitlist open"),
    (r"\bbred\s+to\b", 3, "breeding announced"),
    (r"\bplanned\s+(breeding|litter)\b", 3, "planned litter"),
    (r"\bconfirmed\s+pregnan(t|cy)\b", 4, "confirmed pregnancy"),
    (r"\bultrasound\b", 3, "ultrasound"),
]

MEDIUM = [
    (r"\blitter\b", 2, "litter mentioned"),
    (r"\bpupp(y|ies)\b", 1, "puppies mentioned"),
    (r"\bstud\s+dog\b", 1, "stud"),
    (r"\bin\s+season\b", 2, "in season"),
    (r"\bsire\b.{0,60}\bdam\b", 2, "sire/dam pairing"),
    (r"\bdeposit\b", 2, "deposit"),
    (r"\breservation\b", 2, "reservation"),
    (r"\bgo\s*home\s+date\b", 3, "go-home date"),
]

# Phrases that mean the opposite. Applied to the same line.
NEGATIVE = [
    (r"\bno\s+(current\s+)?(pupp(y|ies)|litters?)\b", -5),
    (r"\bwait\s*list\s+(is\s+)?(closed|full)\b", -5),
    (r"\bnot\s+(currently\s+)?(breeding|expecting|accepting)\b", -5),
    (r"\ball\s+(pupp(y|ies)|spoken\s+for|placed|reserved)\b", -3),
    (r"\bare\s+(all\s+)?in\s+their\s+(new\s+)?homes\b", -4),
    (r"\bsold\s+out\b", -4),
]

# Preference matching. Scored separately so it can bias ranking without
# manufacturing a litter alert out of nothing.
PREFERENCE = [
    (r"\b(female|girl)s?\s+(pupp(y|ies)|available)", 2, "female puppies"),
    (r"\b\d+\s+(female|girl)s?\b", 2, "female count"),
    (r"\b(all\s+)?(male|boy)s?\s+(only|left|remaining)", -2, "males only"),
    (r"\b(GCH|GCHB|GCHS|GCHG|GCHP|BISS)\b", 2, "conformation titles"),
    (r"\bCH\b(?!IC)", 1, "champion sire/dam"),
    (r"\b(FC|AFC|MH)\b", -1, "field titles"),
]

EVENT = [
    (r"\b(fun\s+match|specialty|hunt\s+test|health\s+clinic|wc/wcx|dock\s+diving|fast\s*cat|upland)\b", 3, "club event"),
    (r"\b(meeting|seminar|lecture|puppy\s+kindergarten)\b", 2, "club gathering"),
]


def _apply(rules, line_low):
    hits, points = [], 0
    for pattern, pts, why in rules:
        if re.search(pattern, line_low):
            points += pts
            hits.append(why)
    return points, hits


def score_lines(lines, kind="litter"):
    """Return (total_score, reasons, evidence_lines) for a list of added lines."""
    rules = EVENT if kind == "events" else STRONG + MEDIUM + PREFERENCE
    total = 0
    reasons = set()
    evidence = []

    for line in lines:
        low = line.lower()
        pts, hits = _apply(rules, low)
        if kind != "events":
            for pattern, penalty in NEGATIVE:
                if re.search(pattern, low):
                    pts += penalty
                    hits.append("negated")
        if pts > 0:
            total += pts
            reasons.update(hits)
            evidence.append(line)

    # A single line can only carry so much weight; cap per-page inflation.
    total = min(total, 20)
    return total, sorted(reasons), evidence[:8]


def summarize(evidence, limit=420):
    text = " / ".join(evidence)
    return text[:limit] + ("..." if len(text) > limit else "")
