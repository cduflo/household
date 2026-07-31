// Lease board.
//
// The proof that the shell works with no Python behind it. golden-watch has a
// sweep, a CLI and 134 tests; this has a JSON file. Both get the same sign-in,
// the same allowlist, the same database, and neither needed any new Google or
// Supabase configuration.
//
// It also adds no tables. Starring a car is `entity_state` with app='lease',
// kind='car'; a note on a car is `note` with the same scoping. That was the
// point of putting an `app` column on the shared primitives rather than giving
// every tool its own copy of "things with a rating" and "things people write
// on".
//
// What it replaces: localStorage, which kept your shortlist in one browser and
// meant only one of you ever saw it.
import { sb, el, gate, signOut } from "../shared/auth.js";

const APP = "lease";
let ME = null;
let CARS = [];
let STATE = [];
let NOTES = [];
let SORT = "monthly";

const app = () => document.getElementById("app");
const keyOf = (car) => car.n.toLowerCase().replace(/[^a-z0-9]+/g, "-");
const stateOf = (k) => STATE.find((s) => s.key === k)
  || { app: APP, kind: "car", key: k, stage: "new", rating: 0 };
const notesOf = (k) => NOTES.filter((n) => n.key === k);

async function loadAll() {
  const [data, state, notes] = await Promise.all([
    fetch("data.json").then((r) => r.json()),
    sb.from("entity_state").select("*").eq("app", APP).eq("kind", "car"),
    sb.from("note").select("*").eq("app", APP).order("at", { ascending: false }),
  ]);
  CARS = data.results || [];
  STATE = state.data || [];
  NOTES = notes.data || [];
  document.getElementById("basis").textContent = data.basis || "";
}

async function refresh() { await loadAll(); draw(); }

const STAGES = ["new", "shortlist", "test-drive", "quoted", "out"];
const STAGE_LABEL = {
  new: "—", shortlist: "Shortlist", "test-drive": "Test drive",
  quoted: "Quoted", out: "Ruled out",
};

async function setState(k, patch) {
  const cur = stateOf(k);
  await sb.from("entity_state").upsert(
    { app: APP, kind: "car", key: k, stage: cur.stage, rating: cur.rating,
      ...patch, updated_at: Date.now() / 1000 },
    { onConflict: "app,kind,key" });
  await sb.from("event").insert({
    app: APP, at: Date.now() / 1000, actor: ME.email, kind: "car", key: k,
    verb: Object.keys(patch)[0], summary: `${k}: ${Object.values(patch)[0]}`, meta: "{}",
  });
  await refresh();
}

function row(car) {
  const k = keyOf(car);
  const st = stateOf(k);
  const card = el("article", "card" + (st.stage === "out" ? " dim" : ""));

  const top = el("div", "card-top");
  top.append(el("h3", "card-name", car.n));
  top.append(el("span", "card-meta",
    `$${car.monthly}/mo · $${car.low}–${car.high} · MSRP $${(car.msrp || 0).toLocaleString()}`));
  card.append(top);
  if (car.notes) card.append(el("p", "card-body", car.notes));
  if (car.confidence) {
    card.append(el("div", "card-note", `confidence: ${car.confidence}`
      + (car.found_offer ? ` · offer found: ${car.found_offer}` : "")));
  }

  const controls = el("div", "row");
  const sel = document.createElement("select");
  for (const s of STAGES) {
    const o = document.createElement("option");
    o.value = s; o.textContent = STAGE_LABEL[s];
    if (s === st.stage) o.selected = true;
    sel.append(o);
  }
  sel.onchange = () => setState(k, { stage: sel.value });
  controls.append(sel);

  const stars = el("span", "stars");
  for (let i = 1; i <= 5; i++) {
    const b = el("button", "star" + (i <= (st.rating || 0) ? " on" : ""), "★");
    b.onclick = () => setState(k, { rating: i });
    stars.append(b);
  }
  controls.append(stars);
  card.append(controls);

  const mine = notesOf(k);
  if (mine.length) {
    const ul = el("ul", "notes");
    for (const n of mine) {
      const li = el("li", "", n.body);
      li.append(el("time", "", `${n.author || "?"} · ${new Date(n.at * 1000).toLocaleDateString()}`));
      ul.append(li);
    }
    card.append(ul);
  }
  const nrow = el("div", "row");
  const input = document.createElement("input");
  input.type = "text"; input.placeholder = "Note — what you liked, what put you off";
  input.style.flex = "1"; input.style.minWidth = "180px";
  const add = el("button", "", "Add");
  add.onclick = async () => {
    if (!input.value.trim()) return;
    await sb.from("note").insert({
      app: APP, kind: "car", key: k, author: ME.email,
      body: input.value, pinned: 0, at: Date.now() / 1000,
    });
    input.value = "";
    await refresh();
  };
  nrow.append(input, add);
  card.append(nrow);
  return card;
}

function draw() {
  const root = app();
  root.innerHTML = "";

  const shortlisted = STATE.filter((s) => ["shortlist", "test-drive", "quoted"].includes(s.stage));
  const box = el("div", "score");
  for (const [label, n] of [["Cars", CARS.length], ["Shortlisted", shortlisted.length],
                            ["Notes", NOTES.length]]) {
    const cell = el("div", "score-cell" + (n ? "" : " zero"));
    cell.append(el("span", "score-n", n), el("span", "score-k", label));
    box.append(cell);
  }
  root.append(box);

  const controls = el("div", "row");
  for (const [k, label] of [["monthly", "Cheapest"], ["msrp", "MSRP"], ["rating", "Your rating"]]) {
    const b = el("button", SORT === k ? "" : "ghost", label);
    b.onclick = () => { SORT = k; draw(); };
    controls.append(b);
  }
  root.append(controls);

  const ranked = [...CARS].sort((a, b) => {
    if (SORT === "rating") return (stateOf(keyOf(b)).rating || 0) - (stateOf(keyOf(a)).rating || 0);
    return (a[SORT] || 0) - (b[SORT] || 0);
  });

  const live = ranked.filter((c) => stateOf(keyOf(c)).stage !== "out");
  const out = ranked.filter((c) => stateOf(keyOf(c)).stage === "out");

  root.append(el("h2", "eyebrow", `In play (${live.length})`));
  live.forEach((c) => root.append(row(c)));
  if (out.length) {
    const det = document.createElement("details");
    det.append(el("summary", "", `Ruled out (${out.length})`));
    out.forEach((c) => det.append(row(c)));
    root.append(det);
  }
}

gate({ appName: "Lease Board", onReady: async (user) => {
  ME = user;
  document.getElementById("who").textContent = `${user.email} · ${user.role}`;
  document.getElementById("signout").onclick = signOut;
  document.getElementById("reload").onclick = refresh;
  await refresh();
}});
