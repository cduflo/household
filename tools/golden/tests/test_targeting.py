"""Target dates and the contact windows keyed off them.

`target_home_date` is an intention, not a fact, and it expires. Nothing in the
original code rolled it forward, and `target_fallback_date` -- which exists in
config precisely for that -- was referenced nowhere. The visible symptom was a
near-term template that asks for a puppy "this autumn" firing at the Yankee
referral volunteer every 30 days indefinitely, including the following February.
"""
from datetime import date

from gw import nudge


YGRC = {"key": "ygrc", "name": "Yankee GRC", "url": "http://y",
        "referral_email": "y@b.com", "method": "email", "contact_lead_days": 75}


def cfg(primary="2026-10-15", fallback="2027-04-15"):
    return {"clubs": [YGRC], "breeders": [],
            "preferences": {"target_home_date": primary,
                            "target_fallback_date": fallback}}


# ---------------------------------------------------------------- rollover

def test_primary_target_is_used_while_it_is_still_ahead():
    assert nudge.effective_target(cfg(), today=date(2026, 7, 28)) == date(2026, 10, 15)


def test_target_rolls_to_the_fallback_once_the_primary_passes():
    assert nudge.effective_target(cfg(), today=date(2026, 11, 1)) == date(2027, 4, 15)


def test_target_is_none_once_both_have_passed():
    """Better to aim at nothing and say so than to keep computing windows
    against a date in the past."""
    assert nudge.effective_target(cfg(), today=date(2027, 6, 1)) is None


def test_rollover_happens_on_the_day_itself():
    assert nudge.effective_target(cfg(), today=date(2026, 10, 15)) == date(2026, 10, 15)
    assert nudge.effective_target(cfg(), today=date(2026, 10, 16)) == date(2027, 4, 15)


# ---------------------------------------------------------------- the window

def test_lead_window_is_shut_before_it_opens(con):
    """75 days before 2026-10-15 is 2026-08-01. Writing earlier wastes the ask."""
    assert nudge.due_clubs(con, cfg(), today=date(2026, 7, 28)) == []


def test_lead_window_opens_on_the_computed_day(con):
    due = nudge.due_clubs(con, cfg(), today=date(2026, 8, 1))
    assert [d["club"]["key"] for d in due] == ["ygrc"]


def test_window_does_not_stay_open_forever_after_the_target_passes(con):
    """The live bug: `date.today() < opens` is false for all eternity once the
    target is behind you, so this club nagged every 30 days indefinitely."""
    assert nudge.due_clubs(con, cfg(), today=date(2026, 11, 1)) == []


def test_window_reopens_against_the_rolled_forward_target(con):
    """75 days before the 2027-04-15 fallback is 2027-01-30."""
    assert nudge.due_clubs(con, cfg(), today=date(2027, 1, 29)) == []
    due = nudge.due_clubs(con, cfg(), today=date(2027, 1, 30))
    assert [d["club"]["key"] for d in due] == ["ygrc"]


def test_no_target_at_all_means_no_lead_window(con):
    assert nudge.due_clubs(con, cfg(primary=None, fallback=None),
                           today=date(2026, 8, 1)) == []


# ---------------------------------------------------------------- seasons

def test_season_matches_the_target_month():
    assert nudge.season_of(date(2026, 10, 15)) == "autumn"
    assert nudge.season_of(date(2027, 4, 15)) == "spring"
    assert nudge.season_of(date(2027, 1, 9)) == "winter"
    assert nudge.season_of(date(2026, 7, 1)) == "summer"


def test_near_term_draft_names_the_current_target_season():
    """Hardcoded 'autumn' read like a form letter nobody had updated."""
    text = nudge.draft_near_term_club_email(YGRC, cfg(), today=date(2026, 8, 1))
    assert "autumn" in text
    assert "winter" not in text


def test_near_term_draft_follows_the_target_when_it_rolls():
    text = nudge.draft_near_term_club_email(YGRC, cfg(), today=date(2027, 1, 30))
    assert "spring" in text
    assert "hoping for autumn" not in text
