// Supabase project coordinates.
//
// The anon key belongs in public source. It identifies the project; it is not a
// credential. Row Level Security decides what any signed-in person may read,
// and an anonymous caller holding this key gets zero rows from every table —
// which is asserted by 24 tests in golden-watch/tests/test_rls.py.
//
// A service_role key must NEVER appear here. It bypasses RLS entirely.
export const SUPABASE_URL = "https://xnabonskbvcfmjinxmlp.supabase.co";
export const SUPABASE_ANON_KEY = "sb_publishable_KVaNpCmUFflxi5WTvxppEw_jVVxd05C";
