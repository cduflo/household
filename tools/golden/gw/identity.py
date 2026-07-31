"""Who is looking at the board.

Lifted from ~/share-site. Authentication happens outside this process:
oauth2-proxy talks to Google, checks a two-email allowlist, and forwards
`X-Forwarded-Email`. There is no OAuth code here and there never should be.

**Local runs stay open.** When no allowlist is configured — the laptop case,
where the server is bound to 127.0.0.1 and nothing is proxied — every request is
the owner. Adding emails to `access:` in config.yaml is what switches this on,
so putting the tool behind a proxy is a deliberate act, and forgetting to
configure it cannot silently expose a shared board to an unauthenticated
visitor: no allowlist means no proxy means loopback only.

**Once an allowlist exists, a missing header is a denial.** If the proxy is
bypassed by hitting the port directly on the box, there is no header and the
request is refused.
"""

ROLES = ("owner", "household")


def configured(cfg):
    access = cfg.get("access") or {}
    return bool(access.get("owners") or access.get("household"))


def identify(headers, cfg):
    """Return {"email", "role"} or None. None means 403 — never a guest."""
    access = cfg.get("access") or {}
    if not configured(cfg):
        # Unshared, loopback-only. The owner is whoever is at the keyboard.
        return {"email": "local", "role": "owner"}

    email = (headers.get("X-Forwarded-Email") or "").strip().lower()
    if not email:
        return None
    owners = {e.strip().lower() for e in access.get("owners", []) if e}
    household = {e.strip().lower() for e in access.get("household", []) if e}
    if email in owners:
        return {"email": email, "role": "owner"}
    if email in household:
        return {"email": email, "role": "household"}
    return None


def allows(user, required):
    if not user:
        return False
    if required is None or required == "household":
        return user["role"] in ROLES
    return user["role"] == "owner"
