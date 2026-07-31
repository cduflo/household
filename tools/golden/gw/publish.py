"""Publish draft skeletons to Postgres for the browser to finish.

The split that makes localStorage drafts work:

Python owns all the *logic* -- which template variant applies, the season words
derived from the rolled-forward target date, the shortlist ask, the event line,
the firm-or-flexible sex sentence. That logic is tested and it stays here.

What it produces is a **skeleton**: fully rendered except for the four fields
that describe the household, which are left as literal `{phone}`,
`{household}`, `{dog_history}` and `{temperament}`. Those never leave the Mac.
The browser substitutes them from localStorage and nothing sensitive is ever
transmitted, stored in Postgres, or present in the page source.

The trick is that `str.format` is idempotent for a value that reproduces its own
placeholder: `"{phone}".format(phone="{phone}")` is `"{phone}"`. So the same
template code produces either a real draft (CLI, on the Mac) or a skeleton
(here) depending only on what it is handed.
"""
import json
import time

from . import nudge

#: Left as placeholders. Everything the household paragraph and the phone
#: number would reveal, and nothing else.
PERSONAL = ("phone", "household", "dog_history", "temperament")


def _skeleton_cfg(cfg):
    """A config whose personal fields render as their own placeholders."""
    owner = dict(cfg.get("owner", {}))
    owner["phone"] = "{phone}"
    owner["household"] = "{household}"
    owner["dog_history"] = "{dog_history}"
    owner["temperament"] = "{temperament}"
    return {**cfg, "owner": owner}


def build(cfg, today=None):
    """Every draft this search can send, as skeletons."""
    skel = _skeleton_cfg(cfg)
    out = []

    for club in cfg.get("clubs", []):
        if not nudge.has_contact_route(club):
            continue
        out.append({
            "key": f"club:{club['key']}:standard",
            "label": f"{club['name']} — introduction",
            "body": nudge.draft_club_email(club, skel),
        })
        out.append({
            "key": f"club:{club['key']}:near_term",
            "label": f"{club['name']} — is there a puppy now",
            "body": nudge.draft_near_term_club_email(club, skel, today),
        })

    for b in cfg.get("breeders", []):
        out.append({
            "key": f"breeder:{b['key']}:standard",
            "label": f"{b['name']} — introduction",
            "body": nudge.draft_breeder_email(b, skel),
        })

    for d in out:
        subject, _, rest = d["body"].partition("\n")
        d["subject"] = subject.replace("Subject:", "").strip()
        d["body"] = rest.lstrip("\n")
    return out


def publish(con, cfg, today=None):
    """Upsert the skeletons. Safe to run on every sweep."""
    drafts = build(cfg, today)
    for d in drafts:
        con.execute(
            """INSERT INTO template (key, label, subject, body, fields, at)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (key) DO UPDATE SET
                 label=excluded.label, subject=excluded.subject,
                 body=excluded.body, fields=excluded.fields, at=excluded.at""",
            (d["key"], d["label"], d["subject"], d["body"],
             json.dumps(list(PERSONAL)), time.time()),
        )
    return len(drafts)
