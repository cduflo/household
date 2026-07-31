// Email drafts, assembled in the browser.
//
// The templates come from Postgres — they are the carefully-worded copy from
// the repo and are not sensitive. The values they interpolate are: a phone
// number, a description of when the house is occupied, and a child's age.
//
// Those live in localStorage on this device and nowhere else. They are never
// sent to Supabase, never in the page source, never in a URL. A different
// device simply has nothing to assemble from, which is also why a household
// session cannot produce a draft even though it can read the templates.
//
// The trade is that you re-enter four fields per browser. Worth it: the
// alternative puts a six-year-old's routine on someone else's disk to save a
// one-minute form.
import { el } from "../shared/auth.js";

const KEY = "golden.owner.v1";

export const FIELDS = [
  { k: "phone", label: "Phone", hint: "(860) 555-0100" },
  { k: "dog_history", label: "Dogs you've had", multiline: true,
    hint: "we've had dogs all our lives — huskies, pit bulls, wheatens, and most recently a maltipoo who lived to 13" },
  { k: "household", label: "Your household", multiline: true,
    hint: "who's home during the day, kids and ages, the yard situation, how the dog would be exercised" },
  { k: "temperament", label: "What you want in the dog", multiline: true,
    hint: "a steady family companion, temperament first — sound, biddable, easy with kids" },
];

export function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
  catch { return {}; }
}

export function save(values) {
  localStorage.setItem(KEY, JSON.stringify(values));
}

export function haveAll(values = load()) {
  return FIELDS.every((f) => (values[f.k] || "").trim());
}

/** Substitute {field} placeholders. Anything unfilled stays visibly bracketed
 *  so it cannot be missed in the textarea. */
export function render(template, values) {
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    (values[name] || "").trim() || whole);
}

export function blanksIn(text) {
  return (text.match(/\[[^\]]+\]/g) || []);
}

/** The capture modal, shown when a draft is wanted and the values are absent. */
export function promptForValues(onSaved) {
  const values = load();
  const back = el("div", "modal-back");
  const box = el("div", "modal");
  box.append(el("h2", "card-name", "Your details"));
  box.append(el("p", "muted",
    "Stored in this browser only — never uploaded, never in the database. " +
    "You'll re-enter these once per device."));

  const inputs = {};
  for (const f of FIELDS) {
    const row = el("div", "field");
    row.append(el("label", "", f.label));
    const input = f.multiline
      ? document.createElement("textarea")
      : document.createElement("input");
    if (!f.multiline) input.type = "text";
    input.placeholder = f.hint;
    input.value = values[f.k] || "";
    inputs[f.k] = input;
    row.append(input);
    box.append(row);
  }

  const row = el("div", "row");
  const ok = el("button", "", "Save on this device");
  ok.onclick = () => {
    const out = {};
    for (const f of FIELDS) out[f.k] = inputs[f.k].value;
    save(out);
    back.remove();
    onSaved(out);
  };
  const cancel = el("button", "ghost", "Cancel");
  cancel.onclick = () => back.remove();
  const forget = el("button", "ghost", "Forget these");
  forget.onclick = () => { localStorage.removeItem(KEY); back.remove(); };
  row.append(ok, cancel, forget);
  box.append(row);
  back.append(box);
  document.body.append(back);
}
