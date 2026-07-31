"""Draft skeletons: everything rendered except what must stay on this machine."""
from gw import publish

CFG = {
    "owner": {"name": "Chris", "base": "West Hartford, CT",
              "phone": "(860) 555-0100", "household": "two adults home all day",
              "dog_history": "huskies and wheatens", "temperament": "steady",
              "lifestyle": "outdoors constantly", "vet_reference": False},
    "preferences": {"target_home_date": "2026-10-15",
                    "target_fallback_date": "2027-04-15",
                    "sex": "female", "sex_is_flexible": False},
    "clubs": [{"key": "sbgrc", "name": "SBGRC", "url": "http://s",
               "referral_email": "a@b.com", "referral_contact": "Pat Example",
               "method": "email", "recontact_days": 45}],
    "breeders": [{"key": "meirzah", "name": "Meirzah"}],
}


def test_personal_values_never_appear_in_a_skeleton():
    """The whole point. If any of these leak into Postgres the design has failed."""
    blob = " ".join(d["body"] + d["subject"] for d in publish.build(CFG))
    assert "555-0100" not in blob
    assert "two adults home all day" not in blob
    assert "huskies and wheatens" not in blob


def test_placeholders_survive_for_the_browser_to_fill():
    body = next(d["body"] for d in publish.build(CFG) if d["key"].endswith("standard"))
    assert "{phone}" in body and "{household}" in body


def test_derived_logic_is_already_baked_in():
    """Season words, the firm sex sentence and the contact name come from tested
    Python -- the browser must not have to reimplement any of it."""
    d = next(x for x in publish.build(CFG) if x["key"] == "club:sbgrc:near_term")
    assert "autumn" in d["body"]
    assert "set on a female" in d["body"]
    assert "Hi Pat" in d["body"]


def test_subject_is_split_out():
    d = publish.build(CFG)[0]
    assert d["subject"] and not d["subject"].startswith("Subject:")
    assert "Subject:" not in d["body"]


def test_unroutable_clubs_get_no_draft():
    cfg = {**CFG, "clubs": [{"key": "x", "name": "X", "url": "u",
                             "referral_email": "", "method": "unknown"}]}
    assert not [d for d in publish.build(cfg) if d["key"].startswith("club:")]
