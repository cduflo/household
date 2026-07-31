// The shared board.
//
// Everything renders through textContent. Most of what appears here is text
// scraped from watched breeder sites, so an innerHTML path would be remote XSS
// with a live session attached.
//
// What a household session can do: move a stage, rate, take notes, log a reply,
// tick the checklist, add a date, clear a finding. What it cannot do: read a
// draft (the values live in the owner's browser, so there is nothing to read)
// or trigger a crawl of six volunteer-run websites.
import { sb, el, gate, signOut } from "../shared/auth.js";
import * as drafts from "./drafts.js";

const STAGES = {
  breeder: ["new", "contacted", "talking", "waitlist", "deposit", "placed", "out"],
  club: ["new", "contacted", "replied", "referred", "dormant"],
};
const STAGE_LABEL = {
  new: "Not contacted", contacted: "Contacted", talking: "In conversation",
  waitlist: "On the list", deposit: "Deposit down", placed: "Puppy assigned",
  out: "Closed", replied: "Replied", referred: "Sent names", dormant: "Dormant",
};

let ME = null;
let DATA = {};

const app = () => document.getElementById("app");

async function loadAll() {
  const [state, notes, findings, commitments, events, contacts, templates] =
    await Promise.all([
      sb.from("entity_state").select("*"),
      sb.from("note").select("*").order("pinned", { ascending: false })
        .order("at", { ascending: false }),
      sb.from("finding").select("*").eq("dismissed", 0)
        .order("found_at", { ascending: false }),
      sb.from("commitment").select("*").eq("done", 0).order("on_date"),
      sb.from("event").select("*").order("at", { ascending: false }).limit(80),
      sb.from("contact").select("direction"),
      sb.from("template").select("key,label,subject,body"),
    ]);
  DATA = {
    state: state.data || [], notes: notes.data || [], findings: findings.data || [],
    commitments: commitments.data || [], events: events.data || [],
    contacts: contacts.data || [], templates: templates.data || [],
  };
}

const stateOf = (kind, key) =>
  DATA.state.find((s) => s.kind === kind && s.key === key)
  || { kind, key, stage: "new", rating: 0, ball: "", next_contact_on: "" };
const notesOf = (kind, key) =>
  DATA.notes.filter((n) => n.kind === kind && n.key === key);

async function refresh() {
  await loadAll();
  draw();
}

// ---------------------------------------------------------------- pieces

function scoreboard() {
  const sent = DATA.contacts.filter((c) => c.direction === "out").length;
  const replies = DATA.contacts.filter((c) => c.direction === "in").length;
  const waitlists = DATA.state.filter(
    (s) => s.kind === "breeder" && ["waitlist", "deposit", "placed"].includes(s.stage)
  ).length;
  const box = el("div", "score");
  // Deliberately these four and not "pages checked": they measure the search,
  // not the machine, and zeros are the most useful thing this can tell you.
  for (const [label, n] of [["Emails sent", sent], ["Replies", replies],
                            ["Waitlists", waitlists], ["Dates ahead", DATA.commitments.length]]) {
    const cell = el("div", "score-cell" + (n ? "" : " zero"));
    cell.append(el("span", "score-n", n), el("span", "score-k", label));
    box.append(cell);
  }
  return box;
}

function planStrip() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const soon = DATA.commitments
    .map((c) => ({ ...c, days: Math.round((new Date(c.on_date + "T00:00:00") - today) / 864e5) }))
    .filter((c) => c.days >= 0 && c.days <= 60)
    .sort((a, b) => a.days - b.days);
  if (!soon.length) {
    return el("div", "empty", "No dates in the next 60 days. Club events are the "
      + "back door — referral volunteers rank people they have met.");
  }
  const box = el("div", "plan");
  for (const c of soon) {
    const item = el("div", "plan-item" + (c.days <= 14 ? " soon" : ""));
    item.append(el("div", "plan-d", c.days === 0 ? "today" : `in ${c.days}d`),
                el("div", "plan-w", c.what),
                el("div", "card-meta", c.on_date));
    box.append(item);
  }
  return box;
}

function findingCard(f) {
  const card = el("article", "card " + (f.score >= 4 ? "hot" : "warm"));
  const top = el("div", "card-top");
  top.append(el("h3", "card-name", f.label), el("span", "card-meta", f.kind));
  card.append(top, el("p", "card-body", f.excerpt));
  if (f.url) {
    const note = el("div", "card-note");
    const a = el("a", "", f.url);
    a.href = /^https?:\/\//i.test(f.url) ? f.url : "#";   // no javascript: URLs
    a.rel = "noreferrer noopener";
    note.append(a); card.append(note);
  }
  const row = el("div", "row");
  const done = el("button", "ghost", "Done with this");
  done.onclick = async () => {
    await sb.from("finding").update({ dismissed: 1 }).eq("id", f.id);
    await refresh();
  };
  row.append(done); card.append(row);
  return card;
}

function entityCard(kind, cfg) {
  const st = stateOf(kind, cfg.key);
  const card = el("article", "card" + (st.ball === "us" ? " warm" : ""));
  const top = el("div", "card-top");
  top.append(el("h3", "card-name", cfg.name));
  const meta = el("span", "card-meta");
  if (st.ball === "us") meta.textContent = "YOUR MOVE";
  else if (st.ball === "them") meta.textContent = "waiting on them";
  top.append(meta);
  card.append(top);
  if (cfg.sub) card.append(el("p", "card-body", cfg.sub));

  const pinned = notesOf(kind, cfg.key).find((n) => n.pinned);
  if (pinned) {
    const p = el("div", "card-note", pinned.body);
    p.style.borderLeft = "2px solid var(--pending)";
    p.style.paddingLeft = "8px";
    card.append(p);
  }

  const row = el("div", "row");
  const sel = document.createElement("select");
  for (const s of STAGES[kind]) {
    const o = document.createElement("option");
    o.value = s; o.textContent = STAGE_LABEL[s] || s;
    if (s === st.stage) o.selected = true;
    sel.append(o);
  }
  sel.onchange = async () => {
    await sb.from("entity_state").upsert(
      { kind, key: cfg.key, stage: sel.value, updated_at: Date.now() / 1000 },
      { onConflict: "kind,key" });
    await logEvent("stage", `${cfg.name}: → ${STAGE_LABEL[sel.value]}`, kind, cfg.key);
    await refresh();
  };
  row.append(sel);

  const stars = el("span", "stars");
  for (let i = 1; i <= 5; i++) {
    const b = el("button", "star" + (i <= (st.rating || 0) ? " on" : ""), "★");
    b.onclick = async () => {
      await sb.from("entity_state").upsert(
        { kind, key: cfg.key, stage: st.stage, rating: i, updated_at: Date.now() / 1000 },
        { onConflict: "kind,key" });
      await logEvent("rating", `${cfg.name}: rated ${i}/5`, kind, cfg.key);
      await refresh();
    };
    stars.append(b);
  }
  row.append(stars);
  card.append(row);

  const acts = el("div", "row");
  if (ME.isOwner) {
    const d = el("button", "", "Draft email");
    d.onclick = () => openDraft(kind, cfg);
    acts.append(d);
  }
  const rep = el("button", "ghost", "Log reply");
  rep.onclick = () => logContact(kind, cfg, "in");
  const sent = el("button", "ghost", "Log sent");
  sent.onclick = () => logContact(kind, cfg, "out");
  acts.append(sent, rep);
  card.append(acts);

  // notes
  const det = document.createElement("details");
  det.append(el("summary", "", `Notes (${notesOf(kind, cfg.key).length})`));
  const list = el("ul", "notes");
  for (const n of notesOf(kind, cfg.key)) {
    const li = el("li", n.pinned ? "pin" : "", n.body);
    li.append(el("time", "", `${n.author || "?"} · ${new Date(n.at * 1000).toLocaleString()}`));
    list.append(li);
  }
  det.append(list);
  const nrow = el("div", "row");
  const input = document.createElement("input");
  input.type = "text"; input.placeholder = "What they said, what you promised";
  input.style.flex = "1"; input.style.minWidth = "180px";
  const add = el("button", "", "Add");
  add.onclick = async () => {
    if (!input.value.trim()) return;
    await sb.from("note").insert({
      kind, key: cfg.key, author: ME.email, body: input.value,
      pinned: 0, at: Date.now() / 1000,
    });
    input.value = "";
    await refresh();
  };
  nrow.append(input, add);
  det.append(nrow);
  card.append(det);
  return card;
}

async function logEvent(verb, summary, kind = "", key = "") {
  await sb.from("event").insert({
    at: Date.now() / 1000, actor: ME.email, kind, key, verb, summary, meta: "{}",
  });
}

async function logContact(kind, cfg, direction) {
  const summary = prompt(direction === "out"
    ? "Anything to remember about what you sent?"
    : "What did they say?") ?? "";
  await sb.from("contact").insert({
    target_key: cfg.key, target_type: kind, direction,
    channel: "email", summary, at: Date.now() / 1000,
  });
  const st = stateOf(kind, cfg.key);
  const stage = direction === "out" && st.stage === "new" ? "contacted"
    : direction === "in" && ["new", "contacted"].includes(st.stage)
      ? (kind === "club" ? "replied" : "talking") : st.stage;
  await sb.from("entity_state").upsert({
    kind, key: cfg.key, stage, ball: direction === "out" ? "them" : "us",
    updated_at: Date.now() / 1000,
  }, { onConflict: "kind,key" });
  await logEvent(`contact_${direction}`,
    `${cfg.name}: ${direction === "out" ? "sent" : "received"}${summary ? " — " + summary : ""}`,
    kind, cfg.key);
  await refresh();
}

// ---------------------------------------------------------------- drafts

function openDraft(kind, cfg) {
  if (!drafts.haveAll()) {
    drafts.promptForValues(() => openDraft(kind, cfg));
    return;
  }
  const options = DATA.templates.filter((t) => t.key.startsWith(`${kind}:${cfg.key}:`));
  if (!options.length) { alert("No draft for this one yet — run a sweep."); return; }

  const values = drafts.load();
  const back = el("div", "modal-back");
  const box = el("div", "modal");
  box.append(el("h2", "card-name", cfg.name));

  const pick = document.createElement("select");
  for (const t of options) {
    const o = document.createElement("option");
    o.value = t.key; o.textContent = t.label;
    pick.append(o);
  }
  box.append(pick);

  const subject = el("p", "muted");
  const ta = document.createElement("textarea");
  ta.style.minHeight = "320px";
  const warn = el("div", "warn");

  const paint = () => {
    const t = options.find((x) => x.key === pick.value) || options[0];
    subject.textContent = "Subject: " + drafts.render(t.subject, values);
    ta.value = drafts.render(t.body, values);
    const blanks = drafts.blanksIn(ta.value);
    warn.textContent = blanks.length
      ? `${blanks.length} line(s) still have a blank — including the one specific `
        + `true sentence about their dogs. Fill it before you send; it is the `
        + `difference between a reply and the bin.`
      : "";
    warn.style.display = blanks.length ? "block" : "none";
  };
  pick.onchange = paint;
  box.append(subject, ta, warn);

  const row = el("div", "row");
  const copy = el("button", "", "Copy");
  copy.onclick = async () => {
    await navigator.clipboard.writeText(ta.value);
    copy.textContent = "Copied";
    setTimeout(() => (copy.textContent = "Copy"), 1500);
  };
  const marksent = el("button", "ghost", "Copied — log it as sent");
  marksent.onclick = async () => { back.remove(); await logContact(kind, cfg, "out"); };
  const edit = el("button", "ghost", "Edit my details");
  edit.onclick = () => { back.remove(); drafts.promptForValues(() => openDraft(kind, cfg)); };
  const close = el("button", "ghost", "Close");
  close.onclick = () => back.remove();
  row.append(copy, marksent, edit, close);
  box.append(row);
  paint();
  back.append(box);
  document.body.append(back);
}

// ---------------------------------------------------------------- draw

function draw() {
  const root = app();
  root.innerHTML = "";
  root.append(scoreboard());

  root.append(heading("Next 60 days"), planStrip());
  const addRow = el("div", "row");
  const d = document.createElement("input"); d.type = "date";
  const w = document.createElement("input");
  w.type = "text"; w.placeholder = "What is it — a clinic, a specialty, a call";
  w.style.flex = "1"; w.style.minWidth = "200px";
  const b = el("button", "", "Add a date");
  b.onclick = async () => {
    if (!d.value || !w.value.trim()) return;
    await sb.from("commitment").insert({
      on_date: d.value, what: w.value, done: 0, at: Date.now() / 1000,
    });
    d.value = ""; w.value = "";
    await refresh();
  };
  addRow.append(d, w, b);
  root.append(addRow);

  const urgent = DATA.findings.filter((f) => ["litter", "nudge"].includes(f.kind));
  root.append(heading("Needs you", urgent.length));
  if (urgent.length) urgent.forEach((f) => root.append(findingCard(f)));
  else root.append(el("div", "empty", "Nothing needs you right now."));

  const breeders = DATA.state.filter((s) => s.kind === "breeder");
  root.append(heading("Breeders", breeders.length));
  const bg = el("div", "grid");
  breeders.forEach((s) => bg.append(entityCard("breeder", { key: s.key, name: s.key })));
  root.append(bg);

  const clubs = DATA.state.filter((s) => s.kind === "club");
  root.append(heading("Club referrals", clubs.length));
  const cg = el("div", "grid");
  clubs.forEach((s) => cg.append(entityCard("club", { key: s.key, name: s.key })));
  root.append(cg);

  root.append(heading("Activity"));
  const log = el("div", "log");
  for (const e of DATA.events) {
    const r = el("div", "log-row");
    r.append(el("span", "log-when", new Date(e.at * 1000).toLocaleDateString()),
             el("span", "log-verb", e.verb),
             el("span", "", e.summary));
    log.append(r);
  }
  root.append(DATA.events.length ? log : el("div", "empty", "Nothing logged yet."));
}

function heading(text, count) {
  const h = el("h2", "eyebrow", text);
  if (count !== undefined) h.append(el("span", "count", " " + count));
  return h;
}

// ---------------------------------------------------------------- boot

gate({ appName: "Golden Watch", onReady: async (user) => {
  ME = user;
  const who = document.getElementById("who");
  who.textContent = `${user.email} · ${user.role}`;
  document.getElementById("signout").onclick = signOut;
  document.getElementById("reload").onclick = refresh;
  await refresh();
}});
