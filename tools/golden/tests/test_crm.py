"""CRM writes: state, notes, checklist, commitments, dogs, litters.

The invariant under test throughout: every mutation writes an event, because a
timeline that silently drops writes is worse than no timeline.
"""
import pytest

from gw import crm, model


def test_club_and_breeder_keys_do_not_collide(con):
    """`gw add-breeder "Yankee Goldens" --key ygrc` succeeds today. With a bare
    key that would merge a club and a breeder into one stage, one note stream
    and one checklist, unrecoverably."""
    crm.set_stage(con, "club", "ygrc", "contacted")
    crm.set_stage(con, "breeder", "ygrc", "talking")
    assert crm.get_state(con, "club", "ygrc")["stage"] == "contacted"
    assert crm.get_state(con, "breeder", "ygrc")["stage"] == "talking"


def test_stage_must_be_valid_for_the_kind(con):
    with pytest.raises(ValueError):
        crm.set_stage(con, "club", "sbgrc", "waitlist")   # a breeder stage


def test_stage_change_is_logged_with_both_ends(con):
    crm.set_stage(con, "breeder", "meirzah", "contacted")
    e = crm.events(con, kind="breeder", key="meirzah")[0]
    assert e["verb"] == "stage"
    assert "Not contacted" in e["summary"] and "Contacted" in e["summary"]


def test_ensure_state_is_idempotent(con):
    crm.ensure_state(con, "breeder", "x")
    crm.ensure_state(con, "breeder", "x")
    n = con.execute("SELECT COUNT(*) AS n FROM entity_state").fetchone()["n"]
    assert n == 1


# ---------------------------------------------------------------- ball / dates

def test_ball_in_court_is_tracked(con):
    crm.set_ball(con, "breeder", "meirzah", "us")
    assert crm.get_state(con, "breeder", "meirzah")["ball"] == "us"


def test_ball_rejects_nonsense(con):
    with pytest.raises(ValueError):
        crm.set_ball(con, "breeder", "meirzah", "maybe")


def test_explicit_next_contact_date_is_stored(con):
    """A breeder who says 'check back in October' has told you the cadence."""
    crm.set_next_contact(con, "breeder", "meirzah", "2026-10-01")
    assert crm.get_state(con, "breeder", "meirzah")["next_contact_on"] == "2026-10-01"


# ---------------------------------------------------------------- notes

def test_notes_are_ordered_pinned_first(con):
    crm.add_note(con, "breeder", "m", "second")
    crm.add_note(con, "breeder", "m", "pinned one", pinned=1)
    assert crm.notes(con, "breeder", "m")[0]["body"] == "pinned one"


def test_empty_note_is_rejected(con):
    with pytest.raises(ValueError):
        crm.add_note(con, "breeder", "m", "   ")


def test_editing_a_note_preserves_the_old_text_in_the_log(con):
    nid = crm.add_note(con, "breeder", "m", "Sept litter out of Tessa")
    crm.edit_note(con, nid, "August litter out of Bessie")
    edit = crm.events(con, verb="note_edit")[0]
    assert "Tessa" in edit["meta"]


# ---------------------------------------------------------------- checklist

def test_checklist_item_upserts_rather_than_duplicating(con):
    crm.set_item(con, "breeder", "m", "line_classified", "waiting")
    crm.set_item(con, "breeder", "m", "line_classified", "pass")
    assert crm.checklist(con, "breeder", "m") == {"line_classified": "pass"}


def test_checklist_rejects_an_unknown_state(con):
    with pytest.raises(ValueError):
        crm.set_item(con, "breeder", "m", "line_classified", "done")


def test_a_failed_item_shows_in_progress_as_a_failure(con):
    crm.set_item(con, "breeder", "m", "scam_screen", "fail")
    rows = crm.checklist(con, "breeder", "m")
    _, _, failed = model.checklist_progress(rows, "breeder", "new")
    assert failed


# ---------------------------------------------------------------- commitments

def test_commitment_needs_a_real_date(con):
    with pytest.raises(ValueError):
        crm.add_commitment(con, "sometime in September", "health clinic")


def test_upcoming_commitments_drive_the_plan_strip(con):
    from datetime import date
    crm.add_commitment(con, "2026-09-13", "HVGRC health clinic")
    crm.add_commitment(con, "2026-12-05", "Big E specialty")
    soon = model.upcoming(crm.commitments(con), within_days=60, today=date(2026, 7, 28))
    assert [c["what"] for c in soon] == ["HVGRC health clinic"]


# ---------------------------------------------------------------- dogs/litters

def test_a_dog_needs_a_registered_name(con):
    with pytest.raises(ValueError):
        crm.add_dog(con, call_name="Tessa")


def test_a_sire_can_exist_without_a_breeder(con):
    """Show breeders use outside studs constantly, so the sire is usually not
    the breeder's dog and must be reachable without one."""
    did = crm.add_dog(con, registered_name="Outside Stud")
    assert crm.get_dog(con, did)["breeder_key"] == ""


def test_litter_audit_uses_the_actual_parents(con):
    dam = crm.add_dog(con, registered_name="Dam", dob="2021-03-01",
                      hips="Good", hips_date="2023-06-01",
                      elbows="Normal", elbows_date="2023-06-01",
                      eyes_date="2026-05-01", heart="Normal", chic="1")
    sire = crm.add_dog(con, registered_name="Sire", dob="2020-01-01",
                       hips="Excellent", hips_date="2022-06-01",
                       elbows="Normal", elbows_date="2022-06-01",
                       eyes_date="2026-06-01", heart="Normal", chic="2")
    lid = crm.add_litter(con, "meirzah", sire_id=sire, dam_id=dam, due_on="2026-09-01")
    lit = [x for x in crm.litters(con, "meirzah") if x["id"] == lid][0]
    from datetime import date
    audit = crm.litter_audit(con, lit, asof=date(2026, 7, 28))
    assert audit["score"] == 4 and audit["complete"]


def test_a_stale_eye_exam_sinks_the_litter_not_the_kennel(con):
    """The point of the whole model: this is a fact about one breeding."""
    from datetime import date
    dam = crm.add_dog(con, registered_name="Dam", dob="2021-03-01",
                      hips="Good", hips_date="2023-06-01",
                      elbows="Normal", elbows_date="2023-06-01",
                      eyes_date="2024-01-01", heart="Normal", chic="1")
    lid = crm.add_litter(con, "meirzah", dam_id=dam)
    lit = [x for x in crm.litters(con, "meirzah") if x["id"] == lid][0]
    audit = crm.litter_audit(con, lit, asof=date(2026, 7, 28))
    assert not audit["complete"]
    assert any("No sire" in f for f in audit["flags"])


def test_best_litter_is_the_strongest_pairing_not_the_average(con):
    """You choose one puppy from one breeding, so a good pairing existing is
    the question -- not whether the kennel's mean is respectable."""
    from datetime import date
    good = crm.add_dog(con, registered_name="Good", dob="2020-01-01",
                       hips="Good", hips_date="2022-06-01",
                       elbows="Normal", elbows_date="2022-06-01",
                       eyes_date="2026-06-01", heart="Normal", chic="1")
    crm.add_litter(con, "k", dam_id=good, sire_id=good)
    crm.add_litter(con, "k")            # an empty planned litter
    best = crm.best_litter_audit(con, "k", asof=date(2026, 7, 28))
    assert best[1]["score"] == 4


def test_every_mutation_writes_an_event(con):
    crm.set_stage(con, "breeder", "m", "contacted")
    crm.set_rating(con, "breeder", "m", 4)
    crm.add_note(con, "breeder", "m", "called them")
    crm.set_item(con, "breeder", "m", "site_reviewed", "pass")
    verbs = {e["verb"] for e in crm.events(con, kind="breeder", key="m")}
    assert verbs == {"stage", "rating", "note", "checklist"}
