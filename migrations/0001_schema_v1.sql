-- v6 schema v1 — docs/v6_plan.md §4–§7.
--
-- Run by a role that can create roles (the server's admin): the three roles
-- are server-wide, so they are created only if missing and shared by every
-- database on the server. They are NOLOGIN here; logins and passwords are
-- deployment configuration, never part of a checked-in file. Every object
-- below is created as, and owned by, worktimer_owner.
--
-- Isolation (§6): every user-data table carries fk_user, defaulted from the
-- transaction's app.user_id, with row-level security enabled and FORCED (the
-- owner included). An unset app.user_id matches no row: it fails closed.
-- Foreign keys between user-data tables include fk_user, because FK checks
-- bypass row-level security — a row can only ever reference its own user's rows.

create extension if not exists btree_gist;

do $$
declare
    r text;
begin
    foreach r in array array['worktimer_owner', 'worktimer_app', 'worktimer_readonly'] loop
        if not exists (select from pg_roles where rolname = r) then
            execute format('create role %I nologin', r);
        end if;
    end loop;
    -- Refuse rather than build on a role that would bypass row-level security.
    if exists (select from pg_roles
               where rolname in ('worktimer_app', 'worktimer_readonly')
                 and (rolsuper or rolbypassrls)) then
        raise exception 'worktimer_app and worktimer_readonly must not be superusers or bypass row-level security';
    end if;
end
$$;

grant usage, create on schema public to worktimer_owner;
grant usage on schema public to worktimer_app, worktimer_readonly;

set local role worktimer_owner;

-- The current transaction's user; NULL when unset (then no row matches).
create function app_user() returns integer
    language sql stable parallel safe
    as $$ select nullif(current_setting('app.user_id', true), '')::integer $$;

-- ── users ───────────────────────────────────────────────────────────────────

create table users (
    key_user      integer generated always as identity primary key,
    bk_user       text not null unique,          -- IdP subject; 'local' in single-user mode
    email         text,
    display_name  text,
    timezone      text not null default 'Europe/Stockholm',
    is_enabled    boolean not null default true,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

-- User 1: the single-user install's only user. Seeded before RLS is switched on.
insert into users (bk_user, display_name) values ('local', 'Local user');

-- ── trackers — credentials, hard delete ────────────────────────────────────

create table trackers (
    key_tracker       integer generated always as identity primary key,
    fk_user           integer not null default app_user() references users (key_user),
    tracker_name      text not null,
    integration_type  text not null default 'devops' check (integration_type in ('devops', 'jira')),
    org_url           text,
    pat_token         text check (pat_token is null or pat_token = '' or pat_token like 'enc:%'),
    token_expires     date,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    created_by        integer default app_user() references users (key_user),
    updated_by        integer default app_user() references users (key_user),
    unique (fk_user, tracker_name),
    unique (fk_user, key_tracker)
);

-- ── customers — entity (Type 1); wages are Type 2 in customer_wages ────────

create table customers (
    key_customer       integer generated always as identity primary key,
    fk_user            integer not null default app_user() references users (key_user),
    customer_name      text not null,
    currency           char(3) not null default 'SEK' check (currency ~ '^[A-Z]{3}$'),
    color              text,
    fk_tracker         integer,
    tracker_project    text,
    expected_work_pct  numeric(5,2) check (expected_work_pct >= 0),
    sort_order         integer not null default 999,
    is_enabled         boolean not null default true,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    created_by         integer default app_user() references users (key_user),
    updated_by         integer default app_user() references users (key_user),
    unique (fk_user, customer_name),
    unique (fk_user, key_customer),
    foreign key (fk_user, fk_tracker) references trackers (fk_user, key_tracker)
        on delete set null (fk_tracker)
);

-- valid_to is the LAST day a wage applies (inclusive, as in 5.x); NULL = current.
create table customer_wages (
    key_customer_wage  integer generated always as identity primary key,
    fk_user            integer not null default app_user() references users (key_user),
    fk_customer        integer not null,
    wage               integer not null check (wage >= 0),
    valid_from         date not null,
    valid_to           date check (valid_to >= valid_from),
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    created_by         integer default app_user() references users (key_user),
    updated_by         integer default app_user() references users (key_user),
    foreign key (fk_user, fk_customer) references customers (fk_user, key_customer)
        on delete cascade,
    -- fk_user too, like every unique constraint: checked across all users'
    -- rows, a constraint without it would answer for (and name) another
    -- user's periods before the foreign key refuses the row.
    exclude using gist (fk_user with =, fk_customer with =,
                        daterange(valid_from, valid_to, '[]') with &&)
);

-- ── projects ────────────────────────────────────────────────────────────────

create table projects (
    key_project   integer generated always as identity primary key,
    fk_user       integer not null default app_user() references users (key_user),
    fk_customer   integer not null,
    project_name  text not null,
    bk_work_item  bigint,                       -- default work item; NULL = none
    is_enabled    boolean not null default true,
    sort_order    integer not null default 999,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    created_by    integer default app_user() references users (key_user),
    updated_by    integer default app_user() references users (key_user),
    unique (fk_user, fk_customer, project_name),
    unique (fk_user, key_project),
    -- A customer's projects go with it — but only when none has time entries
    -- (time_entries restricts), which is what refuses deleting a customer in use.
    foreign key (fk_user, fk_customer) references customers (fk_user, key_customer)
        on delete cascade
);

-- ── time_entries (was time) ─────────────────────────────────────────────────

create table time_entries (
    key_time_entry      bigint generated always as identity primary key,
    fk_user             integer not null default app_user() references users (key_user),
    fk_project          integer not null,
    started_at          timestamptz not null,
    ended_at            timestamptz check (ended_at >= started_at),
    fk_date             integer not null check (fk_date between 19000101 and 99991231),  -- local date, YYYYMMDD
    duration_hours      numeric(10,4) check (duration_hours >= 0),                        -- exact, never rounded
    wage_snapshot       integer,
    bonus_pct_snapshot  numeric(5,4),
    cost                numeric(12,2),
    user_bonus          numeric(12,2),
    bk_work_item        bigint,
    comment             text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    created_by          integer default app_user() references users (key_user),
    updated_by          integer default app_user() references users (key_user),
    deleted_at          timestamptz,
    check (ended_at is null or duration_hours is not null),
    foreign key (fk_user, fk_project) references projects (fk_user, key_project)
        on delete restrict
);

create index time_entries_by_project on time_entries (fk_user, fk_project);
create index time_entries_by_date on time_entries (fk_user, fk_date) where deleted_at is null;
create index time_entries_running on time_entries (fk_user) where ended_at is null and deleted_at is null;

-- ── bonuses (was bonus) ─────────────────────────────────────────────────────

create table bonuses (
    key_bonus   integer generated always as identity primary key,
    fk_user     integer not null default app_user() references users (key_user),
    bonus_pct   numeric(5,4) not null check (bonus_pct between 0 and 1),
    valid_from  date not null,
    valid_to    date check (valid_to >= valid_from),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    created_by  integer default app_user() references users (key_user),
    updated_by  integer default app_user() references users (key_user),
    deleted_at  timestamptz,
    exclude using gist (fk_user with =, daterange(valid_from, valid_to, '[]') with &&)
        where (deleted_at is null)
);

-- ── work_items (was devops) — tracker cache, hard delete ───────────────────

create table work_items (
    key_work_item        bigint generated always as identity primary key,
    fk_user              integer not null default app_user() references users (key_user),
    fk_customer          integer not null,
    bk_work_item         bigint not null,        -- the tracker's id
    bk_parent_work_item  bigint,
    display_ref          text,                   -- e.g. PROJ-123
    item_type            text,
    title                text,
    state                text,
    board_column         text,
    is_done              boolean not null default false,
    assigned_to          text,
    changed_at           timestamptz,
    priority             integer,
    description_text     text,
    synced_at            timestamptz not null default now(),
    unique (fk_user, fk_customer, bk_work_item),
    foreign key (fk_user, fk_customer) references customers (fk_user, key_customer)
        on delete cascade
);

-- ── tasks ───────────────────────────────────────────────────────────────────

create table tasks (
    key_task         integer generated always as identity primary key,
    fk_user          integer not null default app_user() references users (key_user),
    fk_customer      integer,
    fk_project       integer,
    fk_parent_task   integer,
    title            text not null,
    description      text,
    status           text not null default 'To Do',
    priority         text not null default 'Medium',
    is_completed     boolean not null default false,
    assigned_to      text,
    due_date         date,
    estimated_hours  numeric(8,2) not null default 0 check (estimated_hours >= 0),
    actual_hours     numeric(8,2) not null default 0 check (actual_hours >= 0),
    progress_pct     integer not null default 0 check (progress_pct between 0 and 100),
    tags             text,
    completed_at     timestamptz,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    created_by       integer default app_user() references users (key_user),
    updated_by       integer default app_user() references users (key_user),
    deleted_at       timestamptz,
    unique (fk_user, key_task),
    foreign key (fk_user, fk_customer) references customers (fk_user, key_customer)
        on delete set null (fk_customer),
    foreign key (fk_user, fk_project) references projects (fk_user, key_project)
        on delete set null (fk_project),
    foreign key (fk_user, fk_parent_task) references tasks (fk_user, key_task)
        on delete set null (fk_parent_task)
);

-- ── saved_queries (was queries) ─────────────────────────────────────────────

create table saved_queries (
    key_saved_query  integer generated always as identity primary key,
    fk_user          integer not null default app_user() references users (key_user),
    query_name       text not null,
    query_sql        text not null,
    is_default       boolean not null default false,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    created_by       integer default app_user() references users (key_user),
    updated_by       integer default app_user() references users (key_user),
    deleted_at       timestamptz
);

create unique index saved_queries_name on saved_queries (fk_user, query_name) where deleted_at is null;

-- ── views ───────────────────────────────────────────────────────────────────

-- Replaces the dates table: nothing to populate, no horizon to extend.
-- Pure date arithmetic, so the session time zone can't shift a day.
create view dates as
select (extract(year from d) * 10000 + extract(month from d) * 100 + extract(day from d))::integer as key_date,
       d                                  as date,
       extract(year from d)::integer      as year,
       extract(isoyear from d)::integer   as iso_year,
       extract(month from d)::integer     as month,
       extract(week from d)::integer      as week,
       extract(day from d)::integer       as day
from (select date '2000-01-01' + n as d
      from generate_series(0, date '2100-12-31' - date '2000-01-01') as g(n)) as days;

-- Time entries with their customer, project and currency; soft-deleted rows
-- excluded. security_invoker: row-level security is evaluated as the querying
-- role, not as the view's owner.
create view v_time_entries with (security_invoker = true) as
select te.key_time_entry,
       te.fk_user,
       p.fk_customer,
       c.customer_name,
       te.fk_project,
       p.project_name,
       c.currency,
       te.started_at,
       te.ended_at,
       te.fk_date,
       te.duration_hours,
       te.wage_snapshot,
       te.bonus_pct_snapshot,
       te.cost,
       te.user_bonus,
       te.bk_work_item,
       te.comment,
       te.created_at,
       te.updated_at
from time_entries te
join projects p on p.key_project = te.fk_project
join customers c on c.key_customer = p.fk_customer
where te.deleted_at is null;

-- ── triggers ────────────────────────────────────────────────────────────────

create function set_updated() returns trigger
    language plpgsql
    as $$
begin
    new.updated_at := now();
    new.updated_by := app_user();
    return new;
end
$$;

create function set_updated_at() returns trigger
    language plpgsql
    as $$
begin
    new.updated_at := now();
    return new;
end
$$;

create trigger set_updated_at before update on users
    for each row execute function set_updated_at();

do $$
declare
    t text;
begin
    foreach t in array array['trackers', 'customers', 'customer_wages', 'projects',
                             'time_entries', 'bonuses', 'tasks', 'saved_queries'] loop
        execute format('create trigger set_updated before update on %I
                        for each row execute function set_updated()', t);
    end loop;
end
$$;

-- A customer's currency is fixed once it has time entries (§4): changing it
-- would re-denominate history. Soft-deleted entries count — they are history too.
create function customers_currency_fixed() returns trigger
    language plpgsql
    as $$
begin
    if new.currency is distinct from old.currency and exists (
        select 1
        from time_entries te
        join projects p on p.key_project = te.fk_project
        where p.fk_customer = old.key_customer
    ) then
        raise exception 'the currency of customer "%" is fixed once it has time entries', old.customer_name
            using errcode = 'check_violation';
    end if;
    return new;
end
$$;

create trigger currency_fixed before update of currency on customers
    for each row execute function customers_currency_fixed();

-- ── row-level security ──────────────────────────────────────────────────────

alter table users enable row level security;
alter table users force row level security;
create policy self on users using (key_user = app_user());

do $$
declare
    t text;
begin
    foreach t in array array['trackers', 'customers', 'customer_wages', 'projects',
                             'time_entries', 'bonuses', 'work_items', 'tasks',
                             'saved_queries'] loop
        execute format('alter table %I enable row level security', t);
        execute format('alter table %I force row level security', t);
        execute format('create policy tenant on %I using (fk_user = app_user())', t);
    end loop;
end
$$;

-- ── privileges ──────────────────────────────────────────────────────────────
-- Granted table by table: a new table is visible to no one until its
-- migration says so.

grant select, insert, update, delete
    on trackers, customers, customer_wages, projects, time_entries, bonuses,
       work_items, tasks, saved_queries
    to worktimer_app;
grant select, update (email, display_name, timezone) on users to worktimer_app;
grant select on dates, v_time_entries to worktimer_app;

-- The query editor's role: reads everything of its own user's except the
-- tracker credentials.
grant select
    on users, customers, customer_wages, projects, time_entries, bonuses,
       work_items, tasks, saved_queries, dates, v_time_entries
    to worktimer_readonly;
grant select (key_tracker, fk_user, tracker_name, integration_type, org_url,
              token_expires, created_at, updated_at, created_by, updated_by)
    on trackers to worktimer_readonly;

reset role;
