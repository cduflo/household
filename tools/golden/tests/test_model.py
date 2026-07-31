"""Domain rules: dated clearances, pairing audits, checklist scoring.

The bug class these exist to prevent: a checkbox that says "eyes: done" and is
silently wrong twelve months later, and a kennel-level clearance strip that
makes a spectacular 2019 dam and a sloppy 2026 breeding look identical.
"""
from datetime import date

from gw import model


DAM = {"registered_name": "Meirzah Tessa", "dob": "2021-03-01",
       "hips": "Good", "hips_date": "2023-06-01",
       "elbows": "Normal", "elbows_date": "2023-06-01",
       "eyes_date": "2026-05-01", "heart": "Normal", "heart_date": "2023-07-01",
       "chic": "123456"}
SIRE = {"registered_name": "Someone Else's Stud", "dob": "2020-01-15",
        "hips": "Excellent", "hips_date": "2022-04-01",
        "elbows": "Normal", "elbows_date": "2022-04-01",
        "eyes_date": "2026-06-01", "heart": "Normal", "heart_date": "2022-05-01",
        "chic": "99999"}

TODAY = date(2026, 7, 28)


# ---------------------------------------------------------------- expiry

def test_eye_clearance_is_current_inside_twelve_months():
    state, _ = model.eye_state("2026-05-01", asof=TODAY)
    assert state == "pass"


def test_eye_clearance_expires():
    """A 2019 eye clearance on a 2026 litter is a historical document."""
    state, detail = model.eye_state("2024-05-01", asof=TODAY)
    assert state == "fail"
    assert "Expired" in detail


def test_eye_clearance_expires_on_the_twelve_month_boundary():
    assert model.eye_state("2025-07-28", asof=TODAY)[0] == "fail"
    assert model.eye_state("2025-07-29", asof=TODAY)[0] == "pass"


def test_the_same_dog_expires_without_anything_being_edited():
    """The whole reason clearance state is derived and never stored."""
    assert model.eye_state("2026-05-01", asof=date(2026, 7, 28))[0] == "pass"
    assert model.eye_state("2026-05-01", asof=date(2027, 7, 28))[0] == "fail"


# ---------------------------------------------------------------- prelims

def test_hips_before_24_months_are_preliminary_not_a_clearance():
    state, detail = model.hip_elbow_state("Good", "2022-06-01", "2021-03-01")
    assert state == "fail"
    assert "Preliminary" in detail


def test_hips_at_24_months_are_final():
    assert model.hip_elbow_state("Good", "2023-03-01", "2021-03-01")[0] == "pass"


def test_hips_with_no_exam_date_are_unverified_not_passing():
    state, _ = model.hip_elbow_state("Good", "", "2021-03-01")
    assert state == "waiting"


# ---------------------------------------------------------------- pairing

def test_a_clean_pairing_scores_four():
    r = model.audit_pairing(SIRE, DAM, asof=TODAY)
    assert r["score"] == 4 and r["complete"]


def test_a_missing_sire_is_flagged_not_ignored():
    """The sire is usually another kennel's dog and is the half most often
    left unstated."""
    r = model.audit_pairing(None, DAM, asof=TODAY)
    assert not r["complete"]
    assert any("No sire" in f for f in r["flags"])


def test_one_bad_parent_sinks_the_pairing():
    stale = {**SIRE, "eyes_date": "2024-01-01"}
    r = model.audit_pairing(stale, DAM, asof=TODAY)
    assert r["score"] == 3
    assert any("Sire eyes" in f for f in r["flags"])


def test_missing_chic_is_flagged():
    r = model.audit_pairing({**SIRE, "chic": ""}, DAM, asof=TODAY)
    assert any("CHIC" in f for f in r["flags"])


# ---------------------------------------------------------------- checklist

def test_diligence_items_are_hidden_until_there_is_a_conversation():
    early = {k for k, _ in model.checklist_for("breeder", "new")}
    later = {k for k, _ in model.checklist_for("breeder", "talking")}
    assert "take_back" not in early
    assert "take_back" in later
    assert early < later


def test_na_leaves_the_denominator():
    rows = {"line_classified": "pass", "site_reviewed": "na",
            "coe_member": "na", "scam_screen": "na"}
    done, applicable, _ = model.checklist_progress(rows, "breeder", "new")
    assert (done, applicable) == (1, 1)


def test_all_na_does_not_divide_by_zero():
    rows = {k: "na" for k, _ in model.checklist_for("breeder", "new")}
    done, applicable, _ = model.checklist_progress(rows, "breeder", "new")
    assert applicable == 0


def test_a_failure_is_visible_and_is_not_progress():
    """'I checked and the answer is bad' must not read as 'done'."""
    rows = {"line_classified": "fail"}
    done, _, failed = model.checklist_progress(rows, "breeder", "new")
    assert failed and done == 0


def test_unknown_items_from_an_older_version_are_ignored():
    """A renamed or retired item must not corrupt the score."""
    rows = {"line_classified": "pass", "retired_item_v1": "pass"}
    done, applicable, _ = model.checklist_progress(rows, "breeder", "new")
    assert done == 1 and applicable == 4


# ---------------------------------------------------------------- planning

def test_upcoming_sorts_by_proximity_and_drops_the_past():
    items = [{"on_date": "2026-09-13", "what": "clinic"},
             {"on_date": "2026-07-01", "what": "gone"},
             {"on_date": "2026-08-05", "what": "sooner"},
             {"on_date": "2027-06-01", "what": "far"}]
    out = model.upcoming(items, within_days=60, today=TODAY)
    assert [c["what"] for c in out] == ["sooner", "clinic"]


def test_upcoming_includes_today():
    out = model.upcoming([{"on_date": "2026-07-28", "what": "now"}], today=TODAY)
    assert out[0]["days"] == 0


def test_rating_is_clamped():
    assert model.clamp_rating(9) == 5
    assert model.clamp_rating(-3) == 0
    assert model.clamp_rating("nonsense") == 0
