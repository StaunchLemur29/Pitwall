-- Pitwall cloud schema (Supabase / Postgres).
--
-- Applied automatically by .github/workflows/schema.yml when this file changes
-- on main (or by hand: SQL Editor -> New query -> paste -> Run).
-- Must stay safe to run again and again: "if not exists" / "or replace" only.
--
-- Every row belongs to a user (user_id = the signed-in account) and row-level
-- security makes sure an account can only ever read or write its own rows.
-- The rig PC signs in as you and uploads; the hub signs in as you and reads.

-- One row per lap driven, mirrored from the rig PC's local database.
create table if not exists public.laps (
  id          bigint generated always as identity primary key,
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  rig_id      text not null,             -- which PC it came from
  local_id    bigint not null,           -- the lap's id on that PC
  game        text not null,
  car         text not null,
  track_key   text not null,
  lap_number  int not null,
  lap_time_ms int not null,
  valid       boolean not null,
  out_lap     boolean not null,
  started_at  timestamptz not null,
  sector_ms   int[] not null default '{}',
  corners     jsonb,                     -- corner-by-corner analysis
  trace       jsonb,                     -- telemetry, reduced to ~20 samples a second
  uploaded_at timestamptz not null default now(),
  unique (user_id, rig_id, local_id)
);
-- Added after the first version: safe to run on an existing project.
alter table public.laps add column if not exists systems jsonb;  -- battery & DRS on the lap
alter table public.laps add column if not exists review jsonb;  -- the lap's good and bad (worked out on the PC)
alter table public.laps add column if not exists rewound boolean not null default false;  -- used a rewind: never a best lap
alter table public.laps add column if not exists time_to_beat jsonb;  -- the targets as they stood after this lap
alter table public.laps add column if not exists unfinished boolean not null default false;  -- didn't get to the line
alter table public.laps add column if not exists sections jsonb;  -- the lap's clean passes through each practice section: [[start, end, ms], ...]
alter table public.laps add column if not exists conditions jsonb;  -- track and air temperature, grip, tyre wear, damage, time of day as the lap ended

create index if not exists laps_combo on public.laps (user_id, game, track_key, car, lap_time_ms);
create index if not exists laps_recent on public.laps (user_id, started_at desc);

-- Each track's layout (centre line, edges, corners, sections), so the hub can
-- draw maps without the game's files.
create table if not exists public.tracks (
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  game        text not null,
  track_key   text not null,
  geometry    jsonb not null,
  updated_at  timestamptz not null default now(),
  primary key (user_id, game, track_key)
);

-- Which systems each car has (DRS, ERS, ABS/TC levels...).
create table if not exists public.car_profiles (
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  game        text not null,
  car         text not null,
  profile     jsonb not null,
  updated_at  timestamptz not null default now(),
  primary key (user_id, game, car)
);

-- AI debriefs (filled in later in phase 2).
create table if not exists public.debriefs (
  id          bigint generated always as identity primary key,
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  game        text not null,
  car         text not null,
  track_key   text not null,
  session_start timestamptz not null,
  body        text not null,
  model       text not null,
  created_at  timestamptz not null default now()
);

-- One debrief per session (the rig uploads it, and may replace it).
create unique index if not exists debriefs_session
  on public.debriefs (user_id, game, car, track_key, session_start);

-- Only your own rows, for every table.
alter table public.laps enable row level security;
alter table public.tracks enable row level security;
alter table public.car_profiles enable row level security;
alter table public.debriefs enable row level security;

do $$
declare t text;
begin
  foreach t in array array['laps', 'tracks', 'car_profiles', 'debriefs'] loop
    execute format('drop policy if exists "own rows" on public.%I', t);
    execute format(
      'create policy "own rows" on public.%I for all to authenticated
         using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
  end loop;
end $$;
