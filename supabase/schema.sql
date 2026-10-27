-- GreenLoop pilot schema. Run once in the Supabase SQL Editor.
-- Keep the service role key on the FastAPI server; never ship it to the browser.

create extension if not exists pgcrypto;

create table if not exists public.blocks (
  id text primary key,
  name text not null,
  kind text not null check (kind in ('hostel', 'apartment', 'academic')),
  people integer not null check (people > 0),
  peak_kw numeric not null check (peak_kw >= 0),
  solar_kwp numeric not null default 0 check (solar_kwp >= 0),
  water_l_person_day numeric not null check (water_l_person_day >= 0),
  waste_kg_person_day numeric not null check (waste_kg_person_day >= 0),
  segregation numeric not null default 0 check (segregation >= 0 and segregation <= 1),
  ranked boolean not null default true,
  green_points integer not null default 0 check (green_points >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.emission_factors (
  id text primary key,
  label text not null,
  unit text not null,
  mixed_value numeric not null,
  segregated_value numeric,
  source text not null,
  version text not null default 'demo-v1',
  active boolean not null default true,
  updated_at timestamptz not null default now()
);

create table if not exists public.adopted_actions (
  block_id text not null references public.blocks(id) on delete cascade,
  action_id text not null,
  adopted_at timestamptz not null default now(),
  points_awarded integer not null default 0 check (points_awarded >= 0),
  primary key (block_id, action_id)
);

create table if not exists public.waste_logs (
  id uuid primary key default gen_random_uuid(),
  item_label text not null,
  category text not null check (category in ('organic', 'paper', 'plastic', 'glass', 'metal')),
  weight_kg numeric not null check (weight_kg > 0 and weight_kg <= 50),
  block_id text not null references public.blocks(id),
  block_name text not null,
  co2e_saved_kg numeric not null,
  points integer not null check (points >= 0),
  created_at timestamptz not null default now()
);

create index if not exists waste_logs_created_at_idx on public.waste_logs (created_at desc);
create index if not exists waste_logs_block_created_at_idx on public.waste_logs (block_id, created_at desc);

-- Readings are virtual/generated today, but this table is ready for persisted simulator snapshots.
create table if not exists public.readings (
  id bigint generated always as identity primary key,
  block_id text not null references public.blocks(id) on delete cascade,
  observed_at timestamptz not null,
  source text not null default 'software-simulated' check (source in ('software-simulated', 'manual', 'sensor')),
  electricity_kwh numeric not null default 0 check (electricity_kwh >= 0),
  solar_kwh numeric not null default 0 check (solar_kwh >= 0),
  water_kl numeric not null default 0 check (water_kl >= 0),
  waste_kg numeric not null default 0 check (waste_kg >= 0),
  unique (block_id, observed_at, source)
);

create index if not exists readings_block_time_idx on public.readings (block_id, observed_at desc);

insert into public.blocks (id, name, kind, people, peak_kw, solar_kwp, water_l_person_day, waste_kg_person_day, segregation, ranked, green_points)
values
  ('ha', 'Hostel A', 'hostel', 380, 95, 50, 135, .42, .35, true, 1240),
  ('hb', 'Hostel B', 'hostel', 360, 88, 30, 135, .40, .50, true, 1385),
  ('hc', 'Hostel C', 'hostel', 300, 80, 0, 135, .41, .25, true, 910),
  ('ap', 'Apartments D', 'apartment', 210, 58, 20, 150, .50, .40, true, 1090),
  ('sq', 'Staff Quarters', 'apartment', 120, 30, 10, 150, .45, .30, true, 760),
  ('ac', 'Academic Block', 'academic', 900, 260, 150, 25, .20, .45, false, 0)
on conflict (id) do nothing;

insert into public.emission_factors (id, label, unit, mixed_value, segregated_value, source, version)
values
  ('grid', 'Electricity grid factor', 'kg CO2e/kWh', .71, null, 'CEA baseline value; verify the applicable reporting year before publication', 'demo-v1'),
  ('pump', 'Water pumping energy', 'kWh/kL', .45, null, 'GreenLoop project assumption; calibrate against campus pumping data', 'demo-v1'),
  ('organic', 'Organic waste', 'kg CO2e/kg', .58, .10, 'IPCC 2006 Vol. 5 / US EPA WARM; demo approximation', 'demo-v1'),
  ('paper', 'Paper waste', 'kg CO2e/kg', .45, -.70, 'US EPA WARM; demo approximation', 'demo-v1'),
  ('plastic', 'Plastic waste', 'kg CO2e/kg', 1.00, -.60, 'US EPA WARM / IPCC 2006 Vol. 5; demo approximation', 'demo-v1'),
  ('glass', 'Glass waste', 'kg CO2e/kg', .02, -.30, 'US EPA WARM; demo approximation', 'demo-v1'),
  ('metal', 'Metal waste', 'kg CO2e/kg', .02, -2.00, 'US EPA WARM; demo approximation', 'demo-v1')
on conflict (id) do nothing;

alter table public.blocks enable row level security;
alter table public.emission_factors enable row level security;
alter table public.adopted_actions enable row level security;
alter table public.waste_logs enable row level security;
alter table public.readings enable row level security;

revoke all on public.blocks, public.emission_factors, public.adopted_actions, public.waste_logs, public.readings from anon, authenticated;
-- Current Supabase projects may not expose newly created public tables automatically.
-- The FastAPI server uses the service role and is the only intended Data API client.
grant usage on schema public to service_role;
grant select, insert, update, delete on public.blocks, public.emission_factors, public.adopted_actions, public.waste_logs, public.readings to service_role;
grant usage, select on sequence public.readings_id_seq to service_role;

create or replace function public.greenloop_adopt_action(p_block_id text, p_action_id text, p_points integer)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  did_add boolean := false;
  current_points integer;
begin
  insert into public.adopted_actions (block_id, action_id, points_awarded)
  values (p_block_id, p_action_id, greatest(0, p_points))
  on conflict (block_id, action_id) do nothing;
  did_add := found;
  if did_add then
    update public.blocks set green_points = green_points + greatest(0, p_points), updated_at = now()
    where id = p_block_id returning green_points into current_points;
  else
    select green_points into current_points from public.blocks where id = p_block_id;
  end if;
  if current_points is null then raise exception 'Unknown GreenLoop block: %', p_block_id; end if;
  return jsonb_build_object('added', did_add, 'points', current_points);
end;
$$;

create or replace function public.greenloop_remove_action(p_block_id text, p_action_id text, p_points integer)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  did_remove boolean := false;
  current_points integer;
begin
  delete from public.adopted_actions where block_id = p_block_id and action_id = p_action_id;
  did_remove := found;
  if did_remove then
    update public.blocks set green_points = greatest(0, green_points - greatest(0, p_points)), updated_at = now()
    where id = p_block_id returning green_points into current_points;
  else
    select green_points into current_points from public.blocks where id = p_block_id;
  end if;
  if current_points is null then raise exception 'Unknown GreenLoop block: %', p_block_id; end if;
  return jsonb_build_object('removed', did_remove, 'points', current_points);
end;
$$;

create or replace function public.greenloop_log_waste(
  p_item_label text, p_category text, p_weight_kg numeric, p_block_id text,
  p_block_name text, p_co2e_saved_kg numeric, p_points integer
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  new_log public.waste_logs;
begin
  insert into public.waste_logs (item_label, category, weight_kg, block_id, block_name, co2e_saved_kg, points)
  values (p_item_label, p_category, p_weight_kg, p_block_id, p_block_name, p_co2e_saved_kg, greatest(0, p_points))
  returning * into new_log;
  update public.blocks set green_points = green_points + greatest(0, p_points), updated_at = now() where id = p_block_id;
  if not found then raise exception 'Unknown GreenLoop block: %', p_block_id; end if;
  return to_jsonb(new_log);
end;
$$;

revoke all on function public.greenloop_adopt_action(text, text, integer) from public, anon, authenticated;
revoke all on function public.greenloop_remove_action(text, text, integer) from public, anon, authenticated;
revoke all on function public.greenloop_log_waste(text, text, numeric, text, text, numeric, integer) from public, anon, authenticated;
grant execute on function public.greenloop_adopt_action(text, text, integer) to service_role;
grant execute on function public.greenloop_remove_action(text, text, integer) to service_role;
grant execute on function public.greenloop_log_waste(text, text, numeric, text, text, numeric, integer) to service_role;

