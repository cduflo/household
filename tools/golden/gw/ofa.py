"""OFA clearance lookup and, more importantly, interpretation.

The lookup half is best-effort: OFA publishes no API, the advanced search is a
plain HTML form, and its query parameters are not contractual. If parsing fails
we degrade to handing you a search URL rather than pretending we know something.

The interpretation half is the part that carries real weight, and it is exact.
For Golden Retrievers the GRCA Code of Ethics requires four clearances on both
parents -- hips, elbows, eyes, heart -- and each has a rule that catches the
most common misrepresentation:

  hips/elbows  OFA will not issue a final number before 24 months of age.
               A "clearance" from a younger dog is a preliminary, which is an
               opinion, not a certification. Prelims carry no OFA number at all,
               so a breeder quoting one is either confused or hoping you are.

  eyes         ACVO/CAER exams expire. GRCA expects an exam within 12 months of
               the breeding. A 2019 eye clearance on a 2026 litter is not a
               clearance, it is a historical document.

  heart        An exam by a board-certified cardiologist (ACA / advanced) is the
               standard. A practitioner or auscultation-only exam is weaker.

  CHIC number  Issued only when all four breed-required screenings are on file.
               Its presence is a fast proxy; its absence is worth a question.
"""
import re
from datetime import datetime, timezone

SEARCH_BASE = "https://ofa.org/advanced-search/"

# Golden Retriever OFA number shapes. Deliberately loose -- OFA has decades of
# format drift and we would rather parse imperfectly than reject a valid number.
RE_HIP = re.compile(r"\bGR-(\d+)([EGF])(\d+)([MF])(?:-(V?PI|NOPI))?", re.I)
RE_ELBOW = re.compile(r"\bGR-EL(\d+)(?:F)?(\d+)([MF])?(?:-(V?PI|NOPI))?", re.I)
RE_EYE = re.compile(r"\bGR-(?:EYE|CAER)(\d+)/(\d+)([MF])?(?:-(V?PI|NOPI))?", re.I)
RE_HEART = re.compile(r"\bGR-([AB]?CA)(\d+)/(\d+)([MF])?(?:-(V?PI|NOPI))?", re.I)
RE_CHIC = re.compile(r"\bCHIC\s*#?\s*(\d+)", re.I)

HIP_RATING = {"E": "Excellent", "G": "Good", "F": "Fair"}
MIN_FINAL_AGE_MONTHS = 24     # hips and elbows
MIN_CARDIAC_AGE_MONTHS = 12   # ACVIM cardiologist exam
EYE_VALID_MONTHS = 12

# PennHIP is an accepted alternative to OFA for hips and reports a distraction
# index rather than a rating. Lower is tighter. Breed median for goldens sits
# near 0.5; below ~0.3 is genuinely good. It has no OFA-style number, so a
# breeder offering PennHIP is not dodging -- they're using the other registry.
RE_PENNHIP = re.compile(r"\bpennhip\b.{0,60}?(0?\.\d{1,2})", re.I)
PENNHIP_BREED_MEDIAN = 0.50


def search_url(term, any_part=True):
    """A URL a human can click. Kennel prefix works better than a full dog name."""
    from urllib.parse import urlencode
    params = {"search": term, "breed": "GR"}
    if any_part:
        params["anypart"] = "1"
    return f"{SEARCH_BASE}?{urlencode(params)}"


def appnum_url(appnum):
    return f"{SEARCH_BASE}?appnum={appnum}"


def parse_clearances(text):
    """Pull structured clearances out of any blob of text.

    Works on an OFA results page, a breeder's own website, or an email a breeder
    sent you. That last case is the useful one: paste their claim in and check
    the arithmetic before you reply.
    """
    found = {"hips": None, "elbows": None, "eyes": None, "heart": None, "chic": None}

    m = RE_HIP.search(text)
    if m:
        found["hips"] = {
            "number": m.group(0),
            "rating": HIP_RATING.get(m.group(2).upper(), m.group(2)),
            "age_months": int(m.group(3)),
            "sex": m.group(4).upper(),
            "permanent_id": (m.group(5) or "").upper(),
        }

    m = RE_ELBOW.search(text)
    if m:
        found["elbows"] = {
            "number": m.group(0),
            "age_months": int(m.group(2)),
            "permanent_id": (m.group(4) or "").upper(),
        }

    m = RE_EYE.search(text)
    if m:
        found["eyes"] = {
            "number": m.group(0),
            "age_months": int(m.group(2)),
            "permanent_id": (m.group(4) or "").upper(),
        }

    m = RE_HEART.search(text)
    if m:
        registry = m.group(1).upper()
        found["heart"] = {
            "number": m.group(0),
            "exam_type": {"ACA": "advanced (cardiologist)",
                          "BCA": "basic (auscultation)",
                          "CA": "cardiac"}.get(registry, registry),
            "age_months": int(m.group(3)),
            "permanent_id": (m.group(5) or "").upper(),
        }

    if not found["hips"]:
        m = RE_PENNHIP.search(text)
        if m:
            di = float(m.group(1))
            found["hips"] = {
                "number": f"PennHIP DI {di}",
                "rating": f"DI {di}",
                "registry": "PennHIP",
                "distraction_index": di,
                "age_months": None,
                "sex": "",
                "permanent_id": "",
            }

    m = RE_CHIC.search(text)
    if m:
        found["chic"] = m.group(1)

    return found


def audit(clearances, dog_birth_year=None, today=None):
    """Turn parsed clearances into a pass/flag verdict with plain reasons."""
    today = today or datetime.now(timezone.utc)
    flags, verdict = [], {}

    for joint in ("hips", "elbows"):
        rec = clearances.get(joint)
        if not rec:
            verdict[joint] = "missing"
            flags.append(f"No {joint} clearance found.")
            continue
        if rec.get("registry") == "PennHIP":
            di = rec["distraction_index"]
            verdict[joint] = "ok"
            if di <= 0.30:
                flags.append(f"PennHIP DI {di} — tight, well under the {PENNHIP_BREED_MEDIAN} breed median.")
            elif di <= PENNHIP_BREED_MEDIAN:
                flags.append(f"PennHIP DI {di} — at or better than the {PENNHIP_BREED_MEDIAN} breed median.")
            else:
                verdict[joint] = "invalid"
                flags.append(f"PennHIP DI {di} — looser than the {PENNHIP_BREED_MEDIAN} breed median. Ask about it.")
            continue
        if rec["age_months"] is None:
            verdict[joint] = "unknown"
            flags.append(f"{joint.capitalize()} found but no age at evaluation. Confirm it was 24 months or older.")
            continue
        if rec["age_months"] < MIN_FINAL_AGE_MONTHS:
            verdict[joint] = "invalid"
            flags.append(
                f"{joint.capitalize()} evaluated at {rec['age_months']} months. "
                f"OFA issues finals at {MIN_FINAL_AGE_MONTHS} months and up, so this reads as a preliminary."
            )
        else:
            verdict[joint] = "ok"

    eyes = clearances.get("eyes")
    if not eyes:
        verdict["eyes"] = "missing"
        flags.append("No eye clearance found. Golden eye exams are annual, so ask for the most recent one.")
    else:
        verdict["eyes"] = "ok"
        flags.append(
            f"Eye exam on file at {eyes['age_months']} months of age. "
            f"Confirm the exam date is within {EYE_VALID_MONTHS} months of the breeding."
        )

    heart = clearances.get("heart")
    if not heart:
        verdict["heart"] = "missing"
        flags.append("No cardiac clearance found.")
    else:
        verdict["heart"] = "ok"
        if heart.get("age_months") and heart["age_months"] < MIN_CARDIAC_AGE_MONTHS:
            verdict["heart"] = "invalid"
            flags.append(
                f"Cardiac exam at {heart['age_months']} months. The standard is a "
                f"cardiologist exam at {MIN_CARDIAC_AGE_MONTHS} months or older."
            )
        if "basic" in heart["exam_type"]:
            flags.append("Cardiac exam is basic auscultation. Advanced (cardiologist) is the stronger standard.")

    if clearances.get("chic"):
        verdict["chic"] = clearances["chic"]
    else:
        verdict["chic"] = None
        flags.append("No CHIC number. CHIC is issued once all four breed screenings are on file.")

    passing = [k for k in ("hips", "elbows", "eyes", "heart") if verdict.get(k) == "ok"]
    verdict["score"] = len(passing)
    verdict["complete"] = len(passing) == 4
    verdict["flags"] = flags
    return verdict


def lookup(prefix, fetcher, user_agent):
    """Best-effort OFA lookup by kennel prefix. Never raises.

    Returns a dict that always contains a clickable url, so a parsing failure
    still leaves you one click from the answer.
    """
    url = search_url(prefix)
    result = {"prefix": prefix, "url": url, "rows": [], "parsed": False, "note": ""}

    text, status, error = fetcher(url, user_agent)
    if error or not text:
        result["note"] = f"Automated lookup unavailable ({error or 'empty response'}). Open the URL to check by hand."
        return result

    clearances = parse_clearances(text)
    if any(clearances.values()):
        result["parsed"] = True
        result["rows"] = [clearances]
        result["note"] = "Parsed from the OFA results page. Confirm the dog names match the litter you were offered."
    else:
        result["note"] = "No OFA numbers matched on the results page. Search by exact registered name instead."
    return result
