# Adversarial review — golden-watch process and messaging

Six personas, each asked to find what's wrong rather than what's good. Ranked fix
list at the bottom.

---

## 1. The show breeder — recipient of the email

*Twenty-year conformation program, two litters a year, forty inquiry emails a
month, deletes thirty-five.*

**The email never says whether you've ever owned a dog.** This is the single
biggest omission and I noticed it in the first fifteen seconds. It is the first
thing I ask everyone. A first-time dog owner is not disqualifying — some of my
best homes were — but not mentioning it reads as either hiding it or not knowing
it matters. Both are bad. Add one honest sentence either way.

**No vet reference.** I ask for one. If you've never had a dog you don't have one,
which is fine, but say so before I ask and offer something else — a landlord, an
employer, the person who'll dog-sit.

**You ask me zero questions.** A buyer who asks nothing has done no homework, or
has done homework and is hiding it to seem easy. The clearances line proves you
read the GRCA page; it doesn't prove you'd know what to do with the answer. Ask
me one real question and you jump the queue.

**"Pet-quality, not a show prospect" — good, and rarer than you'd think.** Most
people asking me for a pet don't say so, and I spend the first call working out
whether they want a companion or a project. Saying it up front saves me that
call. Keep it. One nit: "pet-quality" is my word, and some breeders find it
faintly diminishing. "Companion home" is the warmer phrasing.

**The unfenced-yard paragraph is longer than it needs to be** and its length
signals anxiety. Two sentences reads as a plan; four reads as a defense. Also,
"no underground fence, ever" — the "ever" is a tell. Drop it. Contract-wise, I
personally won't place with an invisible fence, so you're on the right side of
this, but you're overselling.

**"Beach trips down to the CT and RI shore"** — be careful. Salt water, hot sand
and undertow with a puppy under six months is a real conversation, and if you
mention beaches without mentioning you know that, some breeders will read
carelessness. Small, but I noticed.

---

## 2. The club referral volunteer

*Unpaid. Handles this out of a personal Gmail between a job and her own dogs.*

**Too long.** I'm triaging, not evaluating. I need: where you are, what you want,
whether you're serious, and whether you'll embarrass me if I forward you. Your
email has all four buried in prose. Give me a short version and put the detail
below a break so I can skim then read.

**You're asking me to do the work.** "If there are breeders in the region you'd
suggest" makes me generate a list. Easier for me: name the two or three kennels
you've already found and ask whether I'd add or subtract. Now I'm editing, not
composing, and you've shown you did something before writing.

**Nothing tells me you'll show up.** I rank people I've met, and I rank people
who say they're coming to something. The September health clinic and the Big E
weekend are both open to the public. One sentence — "I'm planning to come to X" —
moves you meaningfully, and it costs nothing.

**The 30-day recontact on Yankee is aggressive.** Monthly from a stranger who
hasn't met anyone is a lot. Make it 45 unless you've been to an event, then 30 is
fine because you're a person now.

---

## 3. The veterinary geneticist

*Cares about what the four clearances don't cover.*

**Your audit checks CHIC and stops. CHIC is a floor, not a ceiling.** For goldens
the phenotypic four are hips, elbows, eyes, heart. The DNA panel a serious 2026
program also runs is absent from your tool entirely: **PRA1, PRA2, prcd-PRA,
Ichthyosis, NCL (GR-NCL5), DM, and MD.** These are carrier/clear tests, not
pass/fail — two carriers should not be bred together, one carrier bred to a clear
is acceptable and common. Your tool cannot currently ask the right question,
which is not "are they clear" but "what's the carrier status of both parents and
how were they paired."

**Cancer is the thing and you're not tracking it.** Roughly six in ten goldens
die of cancer — hemangiosarcoma and lymphoma dominate. No clearance predicts it.
The nearest available proxy is longevity in the pedigree, and it is a question you
can just ask: *how long did the grandparents live, and what did they die of?* A
breeder who answers precisely is tracking it. A breeder who deflects is not. This
question belongs in your email and it doubles as the "ask one real question"
fix the breeder persona wanted.

**Your prelim logic is right but incomplete.** You catch hips and elbows issued
under 24 months. You don't catch the more common trick: quoting a *sibling's* or
a *grandparent's* clearances. Verify the OFA record matches the registered name
of the actual sire and dam of the actual litter.

**Eye exams — your 12-month rule is correct** per GRCA Code of Ethics, but the
tool reports age-at-exam in months, not calendar date. Age tells you nothing about
whether it's current. You need the exam date.

**Elbows are pass/fail, not graded like hips.** Your dashboard cell says "On file"
which is fine, but if you ever surface a grade, normal is the only passing result.

---

## 4. The security and privacy engineer

**The GitHub Action commits `state.db` and `config.yaml` to the repo. If that
repo is public, this is the worst thing in the project.** What you'd be
publishing, permanently and indexed:

- Four volunteers' personal email addresses, one with her full name, town and club
  office, harvested and republished in a machine-readable file
- Your household: both adults home during the day, a school-age daughter, the
  daily walking route, and an unfenced yard

That second list is a profile of when a house is occupied and how a child moves
through a neighborhood. It should not exist in a public git history. **Private
repo minimum. Better: keep `owner.household` out of the committed config
entirely** and load it from an untracked file or an env var, so drafts render
locally and the repo stays impersonal.

**`.gitignore.sample` requires a manual `cp` that you will forget once.** Ship a
real `.gitignore` and have the Action force-add only what it needs.

**No `robots.txt` check.** You're crawling volunteer sites. Check it. Cheap
insurance and it's the correct thing regardless.

**Committing a binary SQLite file to git** bloats history and will conflict the
first time a manual run and a scheduled run overlap. Export findings to JSON for
the commit and leave the db local, or use an Actions cache.

**`ofa.lookup()` takes `rows[0]`, the first OFA number found anywhere on the
page.** On a multi-result search page that's an arbitrary dog. It's currently
presented with the same confidence as a real match. Either bind results to a
registered name or mark them unverified.

---

## 5. The fraud investigator

**Goldens are among the most-scammed breeds and your tool has no scam layer at
all.** It filters for quality signals and never checks for fraud signals. The
patterns are stable enough to encode:

- Will ship a puppy sight-unseen; won't do a live video call with dam and litter
- Payment by Zelle, CashApp, Venmo, wire, gift card, or crypto — reversibility is
  the whole game
- Photos that reverse-image-search to other sites (this is scriptable)
- Price well below regional norm, or a sudden "shipping crate insurance" fee after
  deposit
- Pressure and scarcity language; a "breeder" reachable only by text
- No physical address, or an address that doesn't match the claimed state
- Site registered in the last 90 days — WHOIS age is a one-line check and
  catches a lot

Add a `scam_flags` scorer that runs on the same page text you're already
fetching. It's the cheapest capability you're missing.

**Also: you will get scam replies to these emails.** Publishing an inquiry into
referral channels raises your profile. Any unsolicited "I have a litter" reply
you didn't initiate should be treated as hostile until proven otherwise.

---

## 6. The pragmatist at the kitchen table

**You built a monitoring system for six pages that change a few times a year.**
Twice-daily polling is theater. Weekly would lose you nothing. The engineering is
not the bottleneck and there's a risk the tool *becomes* the project — it
generates the feeling of progress without producing the thing. Building it took a
day; sending four emails takes twenty minutes and is worth more.

**Ninety percent of this is relationships and you've automated the ten percent.**
The highest-value item in the whole system is a line in a config comment: the
September health clinic. Go to it. Go to the Big E weekend. Referral volunteers
rank people they've met, and you cannot cron that.

**Your timeline is wrong.** Six to eighteen months on a good waitlist, and you
haven't sent the first email. A puppy in 2026 is unlikely; 2027 is the honest
target. Say that out loud to the household now rather than discovering it in
November.

**Two scheduling conflicts nobody has raised.** You're in Portugal for two weeks
in August — never take a puppy home within a couple of months either side of a
trip like that, so anything whelped this summer is out regardless of what a
breeder offers. And you're shopping an EV lease for fall: whatever you sign will
carry a dog for the next three years, so crate dimensions and a cargo floor you
can hose out belong in that decision now, not after.

**Cost reality.** $3,500–5,000 for a well-bred show-line puppy in New England, and
that's before the first year of vet, training, crate, gear and boarding. Worth
having the number stated rather than absorbed.

---

# Ranked fixes

**Do before sending any email**

1. Add one sentence on prior dog experience — honest either way.
2. Add the longevity question: *how long did the grandparents live, and of what?*
   It fixes the "asks no questions" problem and is the best cancer proxy available.
3. Cut the unfenced-yard paragraph to two sentences. Drop "ever."
4. Swap "pet-quality" for "companion home."
5. Add "I'm planning to be at the September health clinic" to the club emails.
6. Offer a vet reference, or say plainly that you don't have one yet.

**Do before pushing to GitHub**

7. Private repo. Non-negotiable given what's in the config.
8. Move `owner.household` out of the committed config into an untracked file.
9. Ship a real `.gitignore`; stop committing `state.db`.

**Do to the tool, in order of value**

10. Scam-flag scorer — WHOIS age, payment methods, shipping language, reverse
    image check.
11. DNA panel tracking: PRA1, PRA2, prcd, ICH, NCL, DM, MD with carrier status,
    not just the CHIC four.
12. Capture eye-exam *dates*, not age-at-exam.
13. Bind OFA results to registered names; stop trusting `rows[0]`.
14. Drop polling to weekly. Add `robots.txt` checking.
15. Add sources that matter more than the ones you have: AKC event calendar for
    local conformation shows, GRCA National Specialty, k9data.com, golden rescue.

**Do this week, and it outranks all of the above**

16. Send the four emails.
17. Put the September 13 health clinic in the calendar.
