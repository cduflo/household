# Council: is Vercel + Neon + Next.js the right base for a household-tool starter?

Five independent advisors, anonymized peer review, chairman synthesis. Run
2026-07-29. Verdict: **no-go on the proposed stack, go on the starter template.**

---

## The question

Is `Next.js + Auth.js(Google) + Neon Postgres on Vercel Hobby` the easiest, most
lightweight, genuinely-free stack for a recurring class of household tool — and
how cheap is app #7?

Constraints: free only; no domain purchase; Tailscale rejected (wife would need
an app install); Google login wanted; 2 users; megabytes; sensitive data
includes a child's school-walk route, household occupancy, a phone number,
financial account data, and third parties' harvested emails.

## Verdict: 4 no-go, 1 go

| Advisor | Call | Alternative offered |
|---|---|---|
| Contrarian | NO-GO | VPS + DuckDNS + Caddy + oauth2-proxy |
| First Principles | NO-GO | Buy the domain; Cloudflare Tunnel + Access |
| Expansionist | GO | Build bigger — one Neon DB, cross-app joins |
| Outsider | NO-GO | Telegram digests; ask the wife what she wants |
| Executor | NO-GO | VPS path, priced: 90 min once, 15 min per app |

Peer review named the **Executor** strongest (4 of 5 reviewers) and the
**Expansionist** the biggest blind spot (5 of 5).

## The disqualifying facts

1. **The 60s function cap forces a hybrid on day one.** golden-watch's polite
   crawl is ~30s best case, ~174s worst. So Vercel never replaces the machine —
   it adds a platform on top of one. Two deploy targets, two languages, two
   secret stores, before app #7 exists.
2. **Vercel Hobby is non-commercial and Betsy is an Etsy/Printify business.**
   One ToS action takes the whole account and every app on it.
3. **The rewrite costs 20–40 hours to avoid $12/year** — porting six Python view
   layers to TypeScript, SQLite to Postgres, and splitting tested domain logic
   across two languages permanently.
4. **Neon's free tier is not a backup**, and it is a publicly-routable endpoint
   holding the most sensitive data in the portfolio.

## Blind spots the review caught

- **Auth.js signs in *any* Google account** until you hand-write the allowlist.
  oauth2-proxy requires the allowlist as an argument — you cannot forget it at
  11pm on app #7. That is the reason to prefer it.
- **Google OAuth in "Testing" mode expires refresh tokens every 7 days**, which
  would silently end the wife's use of the tool. Publishing the consent screen
  to Production fixes it, and for `email`/`profile`/`openid` scopes it needs no
  Google verification. *(Verified.)*
- **The VPS is the micromo box** — `WALLET_PRIVATE_KEY` lives in that codebase.
  Public OAuth ingress next to a hot wallet is worse than anything Vercel does.
  Two advisors walked into this. *(Verified: 204.168.164.24.)*
- **"Data stays local" is false for a rented VPS** — that is Neon's trust model
  with extra steps.
- **Telegram cloud chats are not E2E**, so "just send her a digest" also puts the
  child's route on someone else's servers.
- **Data minimization is already 80% built.** `phone`, `daughter_age`,
  `dog_history` and `household` exist only in untracked `owner.local.yaml` and
  reach only the *drafts* path. `dashboard.py` renders just `owner.name` and
  `owner.base`, and no sent email body is ever persisted. Gating drafts by role
  is nearly the whole privacy job. *(Verified in repo.)*
- **golden-watch is not a read-only dashboard** — it exposes 18 mutating POST
  routes. Any plan treating it as a static page is planning for a different app.
- **`/api/sweep` spawns a crawl of six volunteer-run sites.** A publicly
  reachable trigger for that is an abuse vector pointed at third parties.

## The resolution the council missed and the chair found

The Tailscale rejection was *"my wife would need an app installed."*

**Tailscale Funnel inverts that.** Tailscale runs only on the serving Mac and
publishes a real public HTTPS URL on `*.ts.net`. Visitors need nothing — any
browser, no install, no account. Free on all plans, no domain. *(Verified
against Tailscale docs.)*

So the original objection does not apply to the configuration that actually
solves the problem. Funnel gives the public URL; oauth2-proxy gives the Google
login and the two-email allowlist; the data never leaves the house.

## Recommended stack

```
Tailscale Funnel   public HTTPS on *.ts.net, no domain, no client install
oauth2-proxy       one Google OAuth client, allowlist as a required argument
Python + SQLite    what already runs six times over, with 97 tests
LaunchAgent        per-app supervision, port as the only variable
restic -> B2       nightly sqlite3 .backup; a real restore path
```

App #7 = new port, one proxy upstream, one plist, one backup line. ~15 minutes,
one language, one machine.

## Apply to golden-watch — four changes, not a rewrite

1. Keep the bind on `127.0.0.1`. oauth2-proxy is same-host; the tunnel is the
   only public surface.
2. Widen the hardcoded `allowed_hosts` (`serve.py:343`) to include the proxy
   hostname, from config — never a wildcard, keep it a membership test.
3. Gate `/api/draft` and `/api/sweep` to `role == owner`. The wife's session sees
   findings, litters and events; the phone number, the child's routine and the
   harvested breeder emails never render for her and never leave the laptop.
4. Add `test_identity.py`: no header → 403; wrong email → 403; household role →
   no drafts, no sweep; owner → full.

## Keep

The Telegram alerts. She probably wants to *know there's a puppy* more than she
wants a dashboard. Don't build household-platform surface area for an audience
of two.

## The one thing to do first

Create one Google OAuth client, **publish the consent screen to Production**
(this is what prevents the 7-day token expiry), and run oauth2-proxy in front of
golden-watch on localhost with exactly two emails allowlisted.

Checkable in one sitting: your account loads the dashboard through the proxy,
hers does too, a third account gets 403, and drafts 403 for her but not for you.
That proves the whole security model with nothing exposed to the internet. Only
then open the tunnel.
