// Google sign-in and identity, shared by every household tool.
//
// Two layers, and both matter:
//
//   Supabase Auth answers "is this a real Google account?" — which is not
//   authorisation. Anyone on earth has a Google account.
//
//   household_member answers "is it one of ours?", and Row Level Security
//   enforces it in the database. A stranger who signs in successfully still
//   reads zero rows from every table.
//
// So the sign-in below is deliberately permissive and the data is not. The page
// asking "who are you" is a convenience for rendering; it is never the control.
import { SUPABASE_URL, SUPABASE_ANON_KEY } from "./config.js";

export const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

export async function signIn() {
  const { error } = await sb.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.href.split("#")[0] },
  });
  if (error) throw error;
}

export async function signOut() {
  await sb.auth.signOut();
  window.location.reload();
}

/** The signed-in person, or null. Adds `role` from the allowlist.
 *
 *  A session with no matching household_member row is a stranger: they are
 *  signed in to Google and entitled to nothing. Treated as null so every caller
 *  falls into the same "not for you" branch. */
export async function whoami() {
  const { data: { session } } = await sb.auth.getSession();
  if (!session?.user?.email) return null;
  const email = session.user.email.toLowerCase();

  const { data, error } = await sb
    .from("household_member").select("role").eq("email", email).maybeSingle();
  if (error || !data) return null;
  return { email, role: data.role, isOwner: data.role === "owner" };
}

/** Render the signed-out state, or hand the user to a callback. */
export async function gate({ onReady, appName }) {
  const user = await whoami();
  if (user) return onReady(user);

  const { data: { session } } = await sb.auth.getSession();
  const stranger = Boolean(session?.user?.email);

  document.body.innerHTML = "";
  const wrap = el("div", "wrap");
  const head = el("header", "masthead");
  head.append(el("h1", "mast-title", appName));
  wrap.append(head);

  if (stranger) {
    // Signed in, not on the list. Say so plainly rather than showing an empty
    // board, which reads as a bug.
    wrap.append(el("p", "muted",
      `Signed in as ${session.user.email}, which is not on the household list. ` +
      `Nothing here is visible to that account.`));
    const out = el("button", "ghost", "Sign out");
    out.onclick = signOut;
    wrap.append(out);
  } else {
    wrap.append(el("p", "muted", "This board is private to the household."));
    const btn = el("button", "", "Sign in with Google");
    btn.onclick = () => signIn().catch((e) => alert(e.message));
    wrap.append(btn);
  }
  document.body.append(wrap);
  return null;
}

/** Element helper. textContent only — never innerHTML.
 *
 *  Most of what this renders is text scraped from watched breeder sites, so an
 *  innerHTML path here would be remote XSS with a session attached. */
export function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
