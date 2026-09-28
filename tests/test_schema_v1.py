"""Schema v1 (migrations/0001_schema_v1.sql, v6 phase 1.3) — above all its
isolation: the security tests the plan calls the most important in the project.

Every check runs as the real role (``SET LOCAL ROLE``) with ``app.user_id``
set the way the app will set it, so row-level security and privileges are the
role's own; the admin connection only seeds data (it bypasses RLS). Each test
gets a fresh copy of the migrated schema, seeded with one of everything for
user 1 ("Acme") and user 2 ("Beta").
"""

from contextlib import contextmanager

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import errors, sql  # noqa: E402

from src.migrator import MigrationError, discover, migrate  # noqa: E402

pytestmark = pytest.mark.postgres

KEYS = {
    "trackers": "key_tracker",
    "customers": "key_customer",
    "customer_wages": "key_customer_wage",
    "projects": "key_project",
    "time_entries": "key_time_entry",
    "bonuses": "key_bonus",
    "work_items": "key_work_item",
    "tasks": "key_task",
    "saved_queries": "key_saved_query",
}
TENANT_TABLES = list(KEYS)


@contextmanager
def as_role(conninfo, role="worktimer_app", user=None):
    """One transaction as `role` for `user` — how the app will run every
    transaction. No `user`: app.user_id is never set."""
    with psycopg.connect(conninfo) as conn:
        with conn.transaction():
            conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
            if user is not None:
                conn.execute(sql.SQL("set local app.user_id = {}").format(sql.Literal(str(user))))
            yield conn


def refused(conn, query, params=None, error=errors.InsufficientPrivilege):
    """Assert the statement fails with `error`; the transaction carries on."""
    with pytest.raises(error):
        with conn.transaction():  # a savepoint
            conn.execute(query, params)


def q(text, **ids):
    return sql.SQL(text).format(**{k: sql.Identifier(v) for k, v in ids.items()})


def _seed(conninfo) -> dict:
    """One of everything for user 1 (Acme) and user 2 (Beta), as the admin."""
    keys = {}
    with psycopg.connect(conninfo) as conn:
        conn.execute("insert into users (bk_user, display_name) values ('second', 'User two')")

        def one(query, params):
            return conn.execute(query, params).fetchone()[0]

        for user, name in ((1, "Acme"), (2, "Beta")):
            k = {}
            k["trackers"] = one(
                "insert into trackers (fk_user, tracker_name, org_url, pat_token) "
                "values (%s, %s, 'org', 'enc:ciphertext') returning key_tracker",
                (user, f"{name} DevOps"))
            k["customers"] = one(
                "insert into customers (fk_user, customer_name, fk_tracker) "
                "values (%s, %s, %s) returning key_customer", (user, name, k["trackers"]))
            k["customer_wages"] = one(
                "insert into customer_wages (fk_user, fk_customer, wage, valid_from) "
                "values (%s, %s, 1000, '2026-01-01') returning key_customer_wage",
                (user, k["customers"]))
            k["projects"] = one(
                "insert into projects (fk_user, fk_customer, project_name) "
                "values (%s, %s, 'Build') returning key_project", (user, k["customers"]))
            k["time_entries"] = one(
                "insert into time_entries (fk_user, fk_project, started_at, ended_at, fk_date, "
                "duration_hours, wage_snapshot, bonus_pct_snapshot, cost, user_bonus) "
                "values (%s, %s, '2026-09-01 07:00Z', '2026-09-01 09:00Z', 20260901, "
                "2, 1000, 0.1, 2000, 200) returning key_time_entry", (user, k["projects"]))
            k["bonuses"] = one(
                "insert into bonuses (fk_user, bonus_pct, valid_from) "
                "values (%s, 0.1, '2026-01-01') returning key_bonus", (user,))
            k["work_items"] = one(
                "insert into work_items (fk_user, fk_customer, bk_work_item, title) "
                "values (%s, %s, 101, 'Item') returning key_work_item", (user, k["customers"]))
            k["tasks"] = one(
                "insert into tasks (fk_user, fk_customer, fk_project, title) "
                "values (%s, %s, %s, 'Task') returning key_task",
                (user, k["customers"], k["projects"]))
            k["saved_queries"] = one(
                "insert into saved_queries (fk_user, query_name, query_sql) "
                "values (%s, 'mine', 'select 1') returning key_saved_query", (user,))
            keys[user] = k
    return keys


@pytest.fixture
def seeded(pg_schema_db):
    return pg_schema_db, _seed(pg_schema_db)


def _count_per_user(conninfo, table) -> dict:
    with psycopg.connect(conninfo) as conn:  # the admin sees everything
        return dict(conn.execute(q("select fk_user, count(*) from {t} group by 1", t=table)))


# ── structure ───────────────────────────────────────────────────────────────


def test_every_user_data_table_is_isolated(pg_schema_db):
    """A table with fk_user but no forced RLS and policy would be readable by
    everyone — this catches one added without them."""
    with psycopg.connect(pg_schema_db) as conn:
        tables = {r[0]: r[1:] for r in conn.execute(
            "select c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "       pg_get_userbyid(c.relowner), "
            "       exists (select from pg_attribute a where a.attrelid = c.oid "
            "               and a.attname = 'fk_user' and not a.attisdropped), "
            "       exists (select from pg_policies p where p.schemaname = 'public' "
            "               and p.tablename = c.relname) "
            "from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'")}

    assert {t for t, row in tables.items() if row[3]} == set(TENANT_TABLES)
    for table, (rls, forced, owner, _, has_policy) in tables.items():
        if table == "schema_migrations":  # the runner's own history
            continue
        assert (rls, forced, has_policy) == (True, True, True), table
        assert owner == "worktimer_owner", table


def test_every_unique_rule_on_user_data_includes_fk_user(pg_schema_db):
    """Unique and exclusion checks see every user's rows. Without fk_user in
    them, one user's insert could collide with — and the error name — another
    user's row. Primary keys are exempt: identity values, never chosen."""
    with psycopg.connect(pg_schema_db) as conn:
        rules = conn.execute(
            "select c.relname, i.indexrelid::regclass::text, "
            "       exists (select from pg_attribute a where a.attrelid = c.oid "
            "               and a.attname = 'fk_user' and a.attnum = any(i.indkey)) "
            "from pg_index i join pg_class c on c.oid = i.indrelid "
            "where c.relnamespace = 'public'::regnamespace and not i.indisprimary "
            "  and (i.indisunique or i.indisexclusion)").fetchall()
    unscoped = [index for table, index, has_user in rules
                if table in TENANT_TABLES and not has_user]
    assert rules and unscoped == []


def test_every_reference_between_user_data_includes_fk_user(pg_schema_db):
    """FK checks bypass RLS: a key alone could point at another user's row."""
    with psycopg.connect(pg_schema_db) as conn:
        refs = conn.execute(
            "select c.conrelid::regclass::text, c.confrelid::regclass::text, c.conname, "
            "       exists (select from pg_attribute a where a.attrelid = c.conrelid "
            "               and a.attname = 'fk_user' and a.attnum = any(c.conkey)) "
            "from pg_constraint c where c.contype = 'f' "
            "  and c.connamespace = 'public'::regnamespace").fetchall()
    between = [(src, dst, name, scoped) for src, dst, name, scoped in refs
               if src in TENANT_TABLES and dst in TENANT_TABLES]
    assert len(between) >= 8
    assert [name for _, _, name, scoped in between if not scoped] == []


def test_the_roles_cannot_bypass_row_level_security(pg_schema_db):
    with psycopg.connect(pg_schema_db) as conn:
        roles = dict(conn.execute(
            "select rolname, rolsuper or rolbypassrls from pg_roles "
            "where rolname like 'worktimer%'"))
    assert roles == {"worktimer_owner": False, "worktimer_app": False, "worktimer_readonly": False,
                     "worktimer_signin": False}


def test_the_single_user_install_has_user_1(pg_schema_db):
    with psycopg.connect(pg_schema_db) as conn:
        row = conn.execute("select key_user, bk_user, timezone, is_enabled from users").fetchall()
    assert row == [(1, "local", "Europe/Stockholm", True)]


# ── fails closed ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["worktimer_app", "worktimer_readonly", "worktimer_owner"])
def test_without_a_user_every_table_is_empty(seeded, role):
    conninfo, _ = seeded
    with as_role(conninfo, role) as conn:
        for table in TENANT_TABLES + ["users", "v_time_entries"]:
            assert conn.execute(q("select count(*) from {t}", t=table)).fetchone()[0] == 0, table


def test_without_a_user_nothing_can_be_written(seeded):
    conninfo, _ = seeded
    with as_role(conninfo) as conn:
        refused(conn, "insert into customers (customer_name) values ('Nobody')")
        assert conn.execute("update customers set color = 'red'").rowcount == 0
        assert conn.execute("delete from saved_queries").rowcount == 0


# ── one user cannot reach another's rows ───────────────────────────────────


def test_a_user_sees_only_their_own_rows(seeded):
    conninfo, _ = seeded
    for user in (1, 2):
        with as_role(conninfo, user=user) as conn:
            for table in TENANT_TABLES:
                owners = conn.execute(q("select distinct fk_user from {t}", t=table)).fetchall()
                assert owners == [(user,)], table
            assert conn.execute("select key_user from users").fetchall() == [(user,)]


def test_a_user_cannot_change_or_delete_another_users_rows(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        for table, key in KEYS.items():
            target = keys[2][table]
            assert conn.execute(q("update {t} set fk_user = fk_user where {k} = %s",
                                  t=table, k=key), (target,)).rowcount == 0, table
            assert conn.execute(q("delete from {t} where {k} = %s", t=table, k=key),
                                (target,)).rowcount == 0, table
        assert conn.execute("update users set timezone = 'UTC' where key_user = 2").rowcount == 0

    for table in TENANT_TABLES:
        assert _count_per_user(conninfo, table)[2] == 1, table


def test_a_user_cannot_write_rows_for_another_user(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        refused(conn, "insert into customers (fk_user, customer_name) values (2, 'Planted')")
        refused(conn, "insert into bonuses (fk_user, bonus_pct, valid_from) values (2, 0.2, '2030-01-01')")
        refused(conn, "update saved_queries set fk_user = 2 where key_saved_query = %s",
                (keys[1]["saved_queries"],))


def test_rows_cannot_reference_another_users_rows(seeded):
    """FK checks bypass RLS; the composite keys (fk_user, key_…) are what stop
    user 1 attaching to a row of user 2's whose key they know or guess."""
    conninfo, keys = seeded
    other = keys[2]
    fk = errors.ForeignKeyViolation
    with as_role(conninfo, user=1) as conn:
        refused(conn, "insert into projects (fk_customer, project_name) values (%s, 'Sneaky')",
                (other["customers"],), error=fk)
        refused(conn, "insert into customer_wages (fk_customer, wage, valid_from) "
                      "values (%s, 1, '2030-01-01')", (other["customers"],), error=fk)
        refused(conn, "insert into time_entries (fk_project, started_at, fk_date) "
                      "values (%s, now(), 20300101)", (other["projects"],), error=fk)
        refused(conn, "insert into work_items (fk_customer, bk_work_item) values (%s, 1)",
                (other["customers"],), error=fk)
        refused(conn, "insert into tasks (title, fk_parent_task) values ('Child', %s)",
                (other["tasks"],), error=fk)
        refused(conn, "update customers set fk_tracker = %s where key_customer = %s",
                (other["trackers"], keys[1]["customers"]), error=fk)


def test_the_same_names_are_free_for_every_user(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, user=2) as conn:
        conn.execute("insert into customers (customer_name) values ('Acme')")  # user 1 has one
        refused(conn, "insert into customers (customer_name) values ('Acme')",
                error=errors.UniqueViolation)
        conn.execute("insert into trackers (tracker_name) values ('Acme DevOps')")


# ── the roles ───────────────────────────────────────────────────────────────


def test_the_readonly_role_reads_its_user_and_writes_nothing(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, "worktimer_readonly", user=1) as conn:
        assert conn.execute("select customer_name from v_time_entries").fetchall() == [("Acme",)]
        for table, key in KEYS.items():
            refused(conn, q("delete from {t}", t=table))
            refused(conn, q("update {t} set fk_user = fk_user", t=table))
        refused(conn, "insert into saved_queries (query_name, query_sql) values ('x', 'select 1')")
        refused(conn, "update users set timezone = 'UTC'")


def test_the_readonly_role_cannot_read_tracker_credentials(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, "worktimer_readonly", user=1) as conn:
        assert conn.execute("select tracker_name, org_url from trackers").fetchall() == [
            ("Acme DevOps", "org")]
        refused(conn, "select pat_token from trackers")
        refused(conn, "select * from trackers")


def test_the_app_role_cannot_switch_row_level_security_off(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, user=1) as conn:
        conn.execute("set local row_security = off")
        refused(conn, "select count(*) from customers")  # errors instead of showing all rows
    with as_role(conninfo, user=1) as conn:
        refused(conn, "alter table customers disable row level security")
        refused(conn, "alter table customers no force row level security")
        refused(conn, "drop policy tenant on customers")
        refused(conn, "create table planted (x int)")
    # SET ROLE is checked against the session user (the test's admin), so ask
    # the catalog: the app's roles hold no membership that grants more.
    with psycopg.connect(conninfo) as conn:
        assert conn.execute(
            "select count(*) from pg_auth_members m join pg_roles r on r.oid = m.member "
            "where r.rolname in ('worktimer_app', 'worktimer_readonly')").fetchone()[0] == 0


@pytest.mark.parametrize("role", ["worktimer_app", "worktimer_readonly", "worktimer_owner"])
def test_no_role_can_move_the_user_from_inside_a_query(seeded, role):
    """Migration 0002: set_config() could change app.user_id mid-query (the
    query editor runs users' own SELECTs). No role may call it."""
    conninfo, _ = seeded
    with as_role(conninfo, role, user=1) as conn:
        refused(conn, "select set_config('app.user_id', '2', true)")
        # pg_settings' update rule calls set_config too.
        refused(conn, "update pg_settings set setting = '5s' where name = 'statement_timeout'")
        assert conn.execute("select current_setting('app.user_id')").fetchone()[0] == "1"
    with psycopg.connect(conninfo) as conn:  # and that route is closed outright
        assert not conn.execute("select has_table_privilege(%s, 'pg_catalog.pg_settings', 'update')",
                                (role,)).fetchone()[0]


def test_users_may_edit_their_own_profile_only(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, user=1) as conn:
        assert conn.execute("update users set timezone = 'UTC'").rowcount == 1
        refused(conn, "update users set bk_user = 'someone-else'")
        refused(conn, "insert into users (bk_user) values ('self-made')")


# ── billing and delete rules ────────────────────────────────────────────────


def test_overlapping_wage_periods_are_rejected(seeded):
    conninfo, keys = seeded
    acme = keys[1]["customers"]
    insert = ("insert into customer_wages (fk_customer, wage, valid_from, valid_to) "
              "values (%s, %s, %s, %s)")
    with as_role(conninfo, user=1) as conn:
        refused(conn, insert, (acme, 1200, "2026-06-01", None), error=errors.ExclusionViolation)

        # a raise: close the current period, open the next the day after
        conn.execute("update customer_wages set valid_to = '2026-05-31' where fk_customer = %s",
                     (acme,))
        conn.execute(insert, (acme, 1200, "2026-06-01", None))
        # valid_to is inclusive, so starting on the closing day overlaps
        refused(conn, insert, (acme, 1300, "2026-05-31", "2026-05-31"),
                error=errors.ExclusionViolation)
        refused(conn, insert, (acme, 1300, "2025-06-01", "2025-05-01"),
                error=errors.CheckViolation)
        # another customer's periods are independent
        other = conn.execute("insert into customers (customer_name) values ('Other') "
                             "returning key_customer").fetchone()[0]
        conn.execute(insert, (other, 900, "2026-01-01", None))


def test_overlapping_bonus_periods_are_rejected_per_user(seeded):
    """Both seeded users already hold open bonuses from 2026-01-01."""
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        refused(conn, "insert into bonuses (bonus_pct, valid_from) values (0.12, '2027-01-01')",
                error=errors.ExclusionViolation)
        conn.execute("update bonuses set deleted_at = now() where key_bonus = %s",
                     (keys[1]["bonuses"],))
        conn.execute("insert into bonuses (bonus_pct, valid_from) values (0.12, '2027-01-01')")
        refused(conn, "insert into bonuses (bonus_pct, valid_from) values (1.5, '2040-01-01')",
                error=errors.CheckViolation)


def test_a_customer_or_project_with_time_entries_cannot_be_deleted(seeded):
    conninfo, keys = seeded
    mine = keys[1]
    fk = errors.RestrictViolation
    with as_role(conninfo, user=1) as conn:
        refused(conn, "delete from projects where key_project = %s", (mine["projects"],), error=fk)
        refused(conn, "delete from customers where key_customer = %s", (mine["customers"],), error=fk)
        # soft-deleted entries are still history
        conn.execute("update time_entries set deleted_at = now()")
        refused(conn, "delete from customers where key_customer = %s", (mine["customers"],), error=fk)


def test_an_unused_customer_can_be_deleted_with_its_projects_and_wages(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, user=1) as conn:
        key = conn.execute("insert into customers (customer_name) values ('Mistake') "
                           "returning key_customer").fetchone()[0]
        conn.execute("insert into customer_wages (fk_customer, wage, valid_from) "
                     "values (%s, 1, '2026-01-01')", (key,))
        conn.execute("insert into projects (fk_customer, project_name) values (%s, 'P')", (key,))
        conn.execute("insert into work_items (fk_customer, bk_work_item) values (%s, 7)", (key,))

        assert conn.execute("delete from customers where key_customer = %s", (key,)).rowcount == 1
        for table in ("customer_wages", "projects", "work_items"):
            assert conn.execute(q("select count(*) from {t} where fk_customer = %s", t=table),
                                (key,)).fetchone()[0] == 0, table


def test_deleting_a_tracker_detaches_its_customers(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        conn.execute("delete from trackers where key_tracker = %s", (keys[1]["trackers"],))
        assert conn.execute("select fk_tracker from customers").fetchall() == [(None,)]


def test_a_customers_currency_is_fixed_once_it_has_time_entries(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        refused(conn, "update customers set currency = 'EUR' where key_customer = %s",
                (keys[1]["customers"],), error=errors.CheckViolation)
        conn.execute("update customers set color = '#fff' where key_customer = %s",
                     (keys[1]["customers"],))  # other edits are fine
        new = conn.execute("insert into customers (customer_name) values ('Euro') "
                           "returning key_customer").fetchone()[0]
        conn.execute("update customers set currency = 'EUR' where key_customer = %s", (new,))
        refused(conn, "update customers set currency = 'eur' where key_customer = %s", (new,),
                error=errors.CheckViolation)


def test_tracker_tokens_are_stored_encrypted_only(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, user=1) as conn:
        refused(conn, "insert into trackers (tracker_name, pat_token) values ('Plain', 'abc123')",
                error=errors.CheckViolation)
        conn.execute("insert into trackers (tracker_name, pat_token) values ('Cipher', 'enc:x')")


# ── defaults, metadata and views ───────────────────────────────────────────


def test_rows_default_to_the_sessions_user_and_track_who_changed_them(seeded):
    conninfo, _ = seeded
    with as_role(conninfo, user=1) as conn:
        key = conn.execute("insert into saved_queries (query_name, query_sql) "
                           "values ('new', 'select 2') returning key_saved_query").fetchone()[0]
    with as_role(conninfo, user=1) as conn:
        conn.execute("update saved_queries set query_sql = 'select 3' where key_saved_query = %s",
                     (key,))
        row = conn.execute("select fk_user, created_by, updated_by, updated_at > created_at "
                           "from saved_queries where key_saved_query = %s", (key,)).fetchone()
    assert row == (1, 1, 1, True)


def test_a_deleted_saved_querys_name_can_be_reused(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        refused(conn, "insert into saved_queries (query_name, query_sql) values ('mine', 'x')",
                error=errors.UniqueViolation)
        conn.execute("update saved_queries set deleted_at = now() where key_saved_query = %s",
                     (keys[1]["saved_queries"],))
        conn.execute("insert into saved_queries (query_name, query_sql) values ('mine', 'x')")


def test_v_time_entries_joins_names_and_hides_deleted_entries(seeded):
    conninfo, keys = seeded
    with as_role(conninfo, user=1) as conn:
        rows = conn.execute("select customer_name, project_name, currency, cost "
                            "from v_time_entries").fetchall()
        assert [(c, p, cur.strip(), float(cost)) for c, p, cur, cost in rows] == [
            ("Acme", "Build", "SEK", 2000.0)]
        conn.execute("update time_entries set deleted_at = now()")
        assert conn.execute("select count(*) from v_time_entries").fetchone()[0] == 0


@pytest.mark.parametrize("day, expected", [
    ("2024-02-29", (20240229, 2024, 2024, 2, 9, 29)),
    ("2024-12-30", (20241230, 2024, 2025, 12, 1, 30)),   # ISO week 1 of the next year
    ("2027-01-01", (20270101, 2027, 2026, 1, 53, 1)),    # ISO week 53 of the previous year
])
def test_the_dates_view_numbers_weeks_the_iso_way(pg_schema_db, day, expected):
    with as_role(pg_schema_db) as conn:
        row = conn.execute("select key_date, year, iso_year, month, week, day "
                           "from dates where date = %s", (day,)).fetchone()
    assert row == expected


def test_the_dates_view_spans_the_centuries_the_data_needs(pg_schema_db):
    with as_role(pg_schema_db, "worktimer_readonly") as conn:
        first, last = conn.execute("select min(key_date), max(key_date) from dates").fetchone()
    assert (first, last) == (20000101, 21001231)


# ── the migration itself ────────────────────────────────────────────────────


def test_it_applies_to_a_second_database_on_the_same_server(pg_db, pg_schema_template):
    """The roles are server-wide and already exist (the template made them)."""
    assert migrate(pg_db) == [m.path.name for m in discover()]
    assert migrate(pg_db) == []


def test_it_refuses_a_role_that_would_bypass_row_level_security(pg_db, pg_server,
                                                                pg_schema_template):
    with psycopg.connect(pg_server, autocommit=True) as admin:
        admin.execute("alter role worktimer_app bypassrls")
        try:
            with pytest.raises(MigrationError, match="must not be superusers or bypass"):
                migrate(pg_db)
        finally:
            admin.execute("alter role worktimer_app nobypassrls")
    with psycopg.connect(pg_db) as conn:  # rolled back whole
        assert conn.execute("select to_regclass('customers')").fetchone()[0] is None
