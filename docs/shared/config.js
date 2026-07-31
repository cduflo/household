// Supabase project coordinates. One source of truth for every tool.
//
// A classic script, not an ES module, on purpose: `type="module"` is deferred,
// so a module that sets these would run *after* any plain inline script on the
// page and the value would be undefined when needed. That is a real bug this
// file already caused once.
//
// The anon key belongs in public source. It identifies the project; it is not a
// credential. Row Level Security decides what a signed-in person may read, and
// an anonymous caller holding it gets zero rows from every table.
//
// A service_role key must NEVER appear here. It bypasses RLS entirely.
window.GW = {
  url: "https://xnabonskbvcfmjinxmlp.supabase.co",
  key: "sb_publishable_KVaNpCmUFflxi5WTvxppEw_jVVxd05C",
};
