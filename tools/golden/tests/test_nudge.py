"""Contact cadence.

The bugs under test all shipped: nudges were inserted fresh every sweep (so
Telegram re-alerted twice a day forever), clubs with no email address on file
nagged as "overdue" when there was nothing to send, and nothing ever retired a
nudge once you had actually written.
"""
import time

from gw import db, nudge


CONTACTABLE = {"key": "sbgrc", "name": "SBGRC", "url": "http://s",
               "referral_email": "a@b.com", "method": "email", "recontact_days": 45}
FORM_ONLY = {"key": "hvgrc", "name": "HVGRC", "url": "http://h",
             "referral_email": "", "method": "web_form", "recontact_days": 45}
NO_ROUTE = {"key": "gpgrc", "name": "Greater Pittsburgh", "url": "http://g",
            "referral_email": "", "method": "unknown", "recontact_days": 90}
REFERENCE = {"key": "grca_evaluate", "name": "GRCA doc", "url": "http://d",
             "referral_email": "", "method": "reference"}


def cfg(*clubs, breeders=()):
    return {"clubs": list(clubs), "breeders": list(breeders),
            "preferences": {"target_home_date": "2026-10-15"}}


# ---------------------------------------------------------------- routing

def test_club_with_no_contact_route_is_not_nagged(con):
    """12 of the 16 club entries have no address on file. Nagging about them
    twice a day is noise you cannot act on -- there is nothing to send."""
    due = nudge.due_clubs(con, cfg(NO_ROUTE))
    assert due == []


def test_web_form_club_is_still_due(con):
    """A form is a contact route even with no email address."""
    due = nudge.due_clubs(con, cfg(FORM_ONLY))
    assert [d["club"]["key"] for d in due] == ["hvgrc"]


def test_reference_entry_is_never_due(con):
    assert nudge.due_clubs(con, cfg(REFERENCE)) == []


def test_unroutable_clubs_are_surfaced_not_lost(con):
    """They are research tasks, not nags. Silently dropping them would lose
    ten real clubs."""
    out = nudge.unroutable_clubs(cfg(CONTACTABLE, NO_ROUTE, REFERENCE))
    assert [c["key"] for c in out] == ["gpgrc"]


# ---------------------------------------------------------------- the P0

def test_repeated_sweeps_produce_one_nudge(con):
    c = cfg(CONTACTABLE)
    for _ in range(5):
        nudge.build_findings(con, c)
    rows = con.execute(
        "SELECT COUNT(*) AS n FROM finding WHERE kind='nudge' AND dismissed=0"
    ).fetchone()["n"]
    assert rows == 1


def test_repeated_sweeps_do_not_re_alert(con):
    """The live symptom: 15 nudges re-sent to Telegram every 12 hours."""
    c = cfg(CONTACTABLE)
    nudge.build_findings(con, c)
    db.mark_notified(con, [r["id"] for r in db.unnotified(con)])
    nudge.build_findings(con, c)
    assert db.unnotified(con) == []


def test_a_long_overdue_nudge_re_alerts_after_the_renotify_window(con):
    c = cfg(CONTACTABLE)
    nudge.build_findings(con, c)
    db.mark_notified(con, [r["id"] for r in db.unnotified(con)])
    stale = time.time() - (db.RENOTIFY_DAYS + 1) * 86400
    con.execute("UPDATE finding SET last_notified_at = %s", (stale,))
    nudge.build_findings(con, c)
    assert len(db.unnotified(con)) == 1


def test_logging_contact_retires_the_nudge(con):
    """Without reconciliation the queue can never reach zero."""
    c = cfg(CONTACTABLE)
    nudge.build_findings(con, c)
    assert len(db.recent_findings(con)) == 1
    db.log_contact(con, "sbgrc", "club", "out", "email")
    nudge.build_findings(con, c)
    assert db.recent_findings(con) == []


def test_found_at_survives_an_upsert(con):
    """It means 'first went due' and the excerpt is written against it."""
    c = cfg(CONTACTABLE)
    nudge.build_findings(con, c)
    first = con.execute("SELECT found_at FROM finding").fetchone()["found_at"]
    time.sleep(0.01)
    nudge.build_findings(con, c)
    assert con.execute("SELECT found_at FROM finding").fetchone()["found_at"] == first


# ------------------------------------------------- stage drives the cadence

BREEDER = {"key": "meirzah", "name": "Meirzah", "site": "http://m", "status": "researching"}


def test_a_closed_breeder_stops_nudging(con):
    """Config `status:` is seed-only. A stage set in the dashboard must be
    what the sweep reads, or every UI change is invisible here."""
    from gw import crm
    c = cfg(breeders=[BREEDER])
    assert len(nudge.due_breeders(con, c)) == 1
    crm.set_stage(con, "breeder", "meirzah", "out")
    assert nudge.due_breeders(con, c) == []


def test_a_placed_breeder_stops_nudging(con):
    """You have the puppy. Following up is absurd."""
    from gw import crm
    crm.set_stage(con, "breeder", "meirzah", "placed")
    assert nudge.due_breeders(con, cfg(breeders=[BREEDER])) == []


def test_a_named_check_back_date_suppresses_the_interval(con):
    from datetime import date
    from gw import crm
    crm.set_next_contact(con, "breeder", "meirzah", "2026-10-01")
    c = cfg(breeders=[BREEDER])
    assert nudge.due_breeders(con, c, today=date(2026, 9, 30)) == []


def test_a_named_check_back_date_fires_when_it_arrives(con):
    from datetime import date
    from gw import crm
    crm.set_next_contact(con, "breeder", "meirzah", "2026-10-01")
    due = nudge.due_breeders(con, cfg(breeders=[BREEDER]), today=date(2026, 10, 1))
    assert "2026-10-01" in due[0]["reason"]


def test_a_dormant_club_stops_nudging(con):
    from gw import crm
    crm.set_stage(con, "club", "sbgrc", "dormant")
    assert nudge.due_clubs(con, cfg(CONTACTABLE)) == []


def test_sync_seeds_stage_from_the_legacy_config_status(con):
    from gw import crm
    crm.sync_entities(con, cfg(CONTACTABLE, breeders=[
        {"key": "m", "name": "M", "status": "waitlist"}]))
    assert crm.get_state(con, "breeder", "m")["stage"] == "waitlist"
    assert crm.get_state(con, "club", "sbgrc")["stage"] == "new"


def test_sync_does_not_overwrite_a_stage_set_in_the_ui(con):
    """Seed once, then the database wins -- two writers for one fact is how
    they diverge."""
    from gw import crm
    c = cfg(breeders=[{"key": "m", "name": "M", "status": "researching"}])
    crm.sync_entities(con, c)
    crm.set_stage(con, "breeder", "m", "waitlist")
    crm.sync_entities(con, c)
    assert crm.get_state(con, "breeder", "m")["stage"] == "waitlist"
