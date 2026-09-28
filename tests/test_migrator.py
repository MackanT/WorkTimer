"""The v6 migration runner (src/migrator.py, phase 1.2).

Discovery rules run offline; everything that touches the database runs on a
throwaway Postgres database (skipped when the dev server isn't running)."""

import threading
import uuid

import pytest

from src.migrator import Migration, MigrationError, discover, main, migrate, provision_logins

psycopg = pytest.importorskip("psycopg")


def _write(directory, name, sql):
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def _history(conninfo):
    with psycopg.connect(conninfo) as conn:
        return [r[0] for r in conn.execute("select version from schema_migrations order by 1")]


def _tables(conninfo):
    with psycopg.connect(conninfo) as conn:
        return sorted(r[0] for r in conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' and table_name != 'schema_migrations'"))


# ── discovery (no database) ─────────────────────────────────────────────────


def test_migrations_are_found_in_version_order(tmp_path):
    _write(tmp_path, "0002_second.sql", "")
    _write(tmp_path, "0010_tenth.sql", "")
    _write(tmp_path, "0001_first.sql", "")
    _write(tmp_path, "README.md", "not a migration")

    assert [m.version for m in discover(tmp_path)] == [1, 2, 10]


@pytest.mark.parametrize("bad", ["1_short.sql", "0001-dash.sql", "0001_Upper.sql", "0001_.sql"])
def test_a_misnamed_sql_file_is_an_error(tmp_path, bad):
    _write(tmp_path, bad, "")

    with pytest.raises(MigrationError, match="NNNN_name.sql"):
        discover(tmp_path)


def test_two_files_sharing_a_number_are_an_error(tmp_path):
    _write(tmp_path, "0003_one.sql", "")
    _write(tmp_path, "0003_other.sql", "")

    with pytest.raises(MigrationError, match="share version 0003"):
        discover(tmp_path)


def test_checksum_ignores_line_endings(tmp_path):
    """A Windows checkout (CRLF) and a Linux image (LF) of one file agree."""
    lf = tmp_path / "0001_a.sql"
    lf.write_bytes(b"create table a (x int);\nselect 1;\n")
    crlf = tmp_path / "0002_a.sql"
    crlf.write_bytes(b"create table a (x int);\r\nselect 1;\r\n")

    assert Migration(1, "a", lf).checksum == Migration(2, "a", crlf).checksum


# ── applying (Postgres) ─────────────────────────────────────────────────────


@pytest.mark.postgres
def test_pending_migrations_apply_in_order_and_are_recorded(pg_db, tmp_path):
    _write(tmp_path, "0001_create_a.sql", "create table a (x int);")
    _write(tmp_path, "0002_fill_a.sql",  # several statements; % in a literal is fine
           "insert into a values (1); insert into a values (2); "
           "create table b as select x from a where 'x' like '%';")

    assert migrate(pg_db, tmp_path) == ["0001_create_a.sql", "0002_fill_a.sql"]
    assert _history(pg_db) == [1, 2]
    assert _tables(pg_db) == ["a", "b"]


@pytest.mark.postgres
def test_running_again_applies_only_new_migrations(pg_db, tmp_path):
    _write(tmp_path, "0001_create_a.sql", "create table a (x int);")
    migrate(pg_db, tmp_path)

    assert migrate(pg_db, tmp_path) == []
    _write(tmp_path, "0002_create_b.sql", "create table b (x int);")
    assert migrate(pg_db, tmp_path) == ["0002_create_b.sql"]


@pytest.mark.postgres
def test_a_failing_migration_rolls_back_whole_and_stops(pg_db, tmp_path):
    _write(tmp_path, "0001_create_a.sql", "create table a (x int);")
    _write(tmp_path, "0002_broken.sql", "create table b (x int); select * from missing_table;")
    _write(tmp_path, "0003_create_c.sql", "create table c (x int);")

    with pytest.raises(MigrationError, match="0002_broken.sql failed"):
        migrate(pg_db, tmp_path)

    assert _history(pg_db) == [1]
    assert _tables(pg_db) == ["a"]  # b rolled back with its migration; c never ran


@pytest.mark.postgres
def test_editing_an_applied_migration_is_refused(pg_db, tmp_path):
    path = _write(tmp_path, "0001_create_a.sql", "create table a (x int);")
    migrate(pg_db, tmp_path)
    path.write_text("create table a (x int, y int);", encoding="utf-8")
    _write(tmp_path, "0002_create_b.sql", "create table b (x int);")

    with pytest.raises(MigrationError, match="0001_create_a.sql was edited"):
        migrate(pg_db, tmp_path)
    assert _history(pg_db) == [1]  # nothing further applied


@pytest.mark.postgres
def test_deleting_an_applied_migration_is_refused(pg_db, tmp_path):
    path = _write(tmp_path, "0001_create_a.sql", "create table a (x int);")
    migrate(pg_db, tmp_path)
    path.unlink()

    with pytest.raises(MigrationError, match="0001 was applied but its file is missing"):
        migrate(pg_db, tmp_path)


@pytest.mark.postgres
def test_a_new_migration_numbered_below_the_newest_applied_is_refused(pg_db, tmp_path):
    _write(tmp_path, "0001_create_a.sql", "create table a (x int);")
    _write(tmp_path, "0003_create_c.sql", "create table c (x int);")
    migrate(pg_db, tmp_path)
    _write(tmp_path, "0002_create_b.sql", "create table b (x int);")  # e.g. from a merge

    with pytest.raises(MigrationError, match="0002_create_b.sql is numbered below"):
        migrate(pg_db, tmp_path)


@pytest.mark.postgres
def test_concurrent_runs_apply_each_migration_once(pg_db, tmp_path):
    for n in range(1, 6):
        _write(tmp_path, f"{n:04d}_t{n}.sql", f"create table t{n} (x int); select pg_sleep(0.05);")
    results, errors = [], []

    def run():
        try:
            results.append(migrate(pg_db, tmp_path))
        except Exception as e:  # surfaced below
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sorted(name for r in results for name in r) == [f"{n:04d}_t{n}.sql" for n in range(1, 6)]
    assert _history(pg_db) == [1, 2, 3, 4, 5]


# ── setting a database up from nothing (compose's "migrate" service) ───────


def test_setup_needs_the_admin_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL_ADMIN", raising=False)

    assert main() == 2
    assert "DATABASE_URL_ADMIN" in capsys.readouterr().err


def test_only_the_app_roles_get_logins():
    with pytest.raises(MigrationError, match="not an app role"):
        provision_logins("dbname=never-connected", {"postgres": "x"})


@pytest.fixture
def new_database(pg_server):
    """Conninfo naming a database that doesn't exist yet; dropped afterwards."""
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = f"wt_test_setup_{uuid.uuid4().hex[:8]}"
    yield make_conninfo(pg_server, dbname=name)
    with psycopg.connect(pg_server, autocommit=True) as admin:
        admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))


@pytest.mark.postgres
def test_setup_creates_migrates_and_gives_the_app_its_login(new_database, pg_logins,
                                                           monkeypatch, capsys):
    from psycopg.conninfo import make_conninfo

    monkeypatch.setenv("DATABASE_URL_ADMIN", new_database)
    monkeypatch.setenv("WORKTIMER_APP_PASSWORD", pg_logins["worktimer_app"])
    monkeypatch.setenv("WORKTIMER_READONLY_PASSWORD", pg_logins["worktimer_readonly"])

    assert main() == 0
    out = capsys.readouterr().out
    assert "created database" in out and "applied 0001_schema_v1.sql" in out
    assert "logins set for worktimer_app, worktimer_readonly" in out

    app = make_conninfo(new_database, user="worktimer_app", password=pg_logins["worktimer_app"])
    with psycopg.connect(app) as conn:
        assert conn.execute("select current_user, count(*) from customers").fetchone() == (
            "worktimer_app", 0)

    assert main() == 0  # rerunnable: nothing to create or apply
    assert "database is up to date" in capsys.readouterr().out
