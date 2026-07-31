-- golden-watch schema, Postgres dialect.
--
-- Timestamps stay epoch doubles rather than timestamptz on purpose: the Python
-- side uses time.time() throughout and the JS side uses Date.now()/1000. One
-- representation, no timezone conversion at three boundaries, and the port
-- surface stays small.

-- ---------------------------------------------------------------- access
--
-- The allowlist. This table IS the security boundary: every policy below
-- reduces to "is the requester in here". Two rows, one shape of policy.
create table if not exists household_member (
    email    text primary key,
    role     text not null check (role in ('owner', 'household')),
    added_at double precision not null default extract(epoch from now())
);

-- ---------------------------------------------------------------- watcher
create table if not exists snapshot (
    key         text primary key,
    url         text not null,
    text        text not null,
    digest      text not null,
    fetched_at  double precision not null,
    http_status integer,
    error       text
);

create table if not exists finding (
    id               bigint generated always as identity primary key,
    key              text not null,
    label            text not null,
    url              text not null,
    kind             text not null,
    score            integer not null,
    excerpt          text not null,
    found_at         double precision not null,
    notified         integer not null default 0,
    dismissed        integer not null default 0,
    last_notified_at double precision
);

-- One open nudge per key. A plain insert per sweep is what re-alerted the same
-- overdue clubs twice a day forever. Partial on dismissed too, so a club that
-- goes due again months later gets a genuinely new row.
create unique index if not exists finding_open_nudge
    on finding (key) where kind = 'nudge' and dismissed = 0;

create table if not exists contact (
    id          bigint generated always as identity primary key,
    target_key  text not null,
    target_type text not null,
    direction   text not null,
    channel     text not null,
    summary     text not null default '',
    at          double precision not null
);

create table if not exists ofa_check (
    kennel_prefix text primary key,
    checked_at    double precision not null,
    payload       text not null
);

create table if not exists run_log (
    id      bigint generated always as identity primary key,
    at      double precision not null,
    checked integer not null,
    changed integer not null,
    alerted integer not null,
    errors  integer not null
);

-- ---------------------------------------------------------------- crm
--
-- Composite (kind, key) everywhere: club keys and breeder keys share one
-- namespace and a bare key would silently merge two entities.
create table if not exists entity_state (
    kind            text not null,
    key             text not null,
    stage           text not null,
    rating          integer not null default 0,
    ball            text not null default '',
    next_contact_on text not null default '',
    updated_at      double precision not null,
    primary key (kind, key)
);

create table if not exists note (
    id     bigint generated always as identity primary key,
    kind   text not null,
    key    text not null,
    author text not null default '',
    body   text not null,
    pinned integer not null default 0,
    at     double precision not null
);
create index if not exists note_entity on note (kind, key, at desc);

create table if not exists checklist (
    kind  text not null,
    key   text not null,
    item  text not null,
    state text not null,
    note  text not null default '',
    at    double precision not null,
    primary key (kind, key, item)
);

create table if not exists event (
    id      bigint generated always as identity primary key,
    at      double precision not null,
    actor   text not null default '',
    kind    text not null default '',
    key     text not null default '',
    verb    text not null,
    summary text not null,
    meta    text not null default '{}'
);
create index if not exists event_at on event (at desc);
create index if not exists event_entity on event (kind, key, at desc);

create table if not exists commitment (
    id      bigint generated always as identity primary key,
    on_date text not null,
    what    text not null,
    kind    text not null default '',
    key     text not null default '',
    done    integer not null default 0,
    note    text not null default '',
    at      double precision not null
);

-- Clearances belong to individual dogs. breeder_key is nullable because the
-- sire is frequently another kennel's stud.
create table if not exists dog (
    id              bigint generated always as identity primary key,
    registered_name text not null,
    call_name       text not null default '',
    sex             text not null default '',
    dob             text not null default '',
    breeder_key     text not null default '',
    chic            text not null default '',
    hips            text not null default '',
    hips_date       text not null default '',
    elbows          text not null default '',
    elbows_date     text not null default '',
    eyes_date       text not null default '',
    heart           text not null default '',
    heart_date      text not null default '',
    dna             text not null default '{}',
    note            text not null default '',
    updated_at      double precision not null
);

create table if not exists litter (
    id          bigint generated always as identity primary key,
    breeder_key text not null,
    sire_id     bigint references dog (id) on delete set null,
    dam_id      bigint references dog (id) on delete set null,
    status      text not null default 'planned',
    bred_on     text not null default '',
    due_on      text not null default '',
    whelped_on  text not null default '',
    pups_total  integer,
    pups_female integer,
    pick_number integer,
    note        text not null default '',
    updated_at  double precision not null
);

-- A published projection of config.yaml, so the browser can show "Southern
-- Berkshire GRC · Hartford → Springfield · 10 min" instead of "sbgrc".
--
-- Config stays the source of truth for identity; this is a copy, rewritten on
-- every sweep. Nothing here is editable from the board -- if a name is wrong,
-- config.yaml is wrong.
create table if not exists entity (
    kind     text not null,
    key      text not null,
    name     text not null,
    subtitle text not null default '',
    detail   text not null default '',
    url      text not null default '',
    email    text not null default '',
    sort     integer not null default 0,
    at       double precision not null,
    primary key (kind, key)
);

-- ---------------------------------------------------------------- templates
--
-- The email copy lives here so the Python CLI and the browser render the same
-- words. The templates are NOT sensitive -- they are already in the git repo.
-- The values they interpolate (phone, household, a child's age) are, and those
-- never come here: they live in owner.local.yaml on the Mac and in the
-- browser's localStorage, and are substituted client-side.
create table if not exists template (
    key     text primary key,
    label   text not null,
    subject text not null,
    body    text not null,
    fields  text not null default '[]',
    at      double precision not null default extract(epoch from now())
);
