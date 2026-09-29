"""The importer (v6 Phase 4): a WorkTimer 5.x database — built here with the
5.x engine itself — or a v6 export, into the Postgres account. The report's
numbers must match; anything v6 would refuse stops the import.
"""

import logging

import pandas as pd
import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import make_conninfo  # noqa: E402

from src import importer  # noqa: E402
from src.database import Database  # noqa: E402
from src.pg_database import PgDatabase  # noqa: E402

pytestmark = [pytest.mark.backends("postgres"), pytest.mark.postgres]


def _quiet():
    log = logging.getLogger("tests.importer.v5")
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log


def _ids(v5, customer, project):
    df = v5.get_data_input_list()
    row = df[(df.customer_name == customer) & (df.project_name == project) & (df.c_current == 1)]
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


@pytest.fixture
def v5_file(tmp_path):
    """A 5.x database in its own folder (its own .pat_key)."""
    folder = tmp_path / "v5"
    folder.mkdir()
    path = folder / "worktimer.db"
    v5 = Database(str(path), _quiet())
    v5.initialize_db()
    v5.insert_bonus("2026-01-01", 10)
    v5.insert_tracker("Ops DevOps", "devops", org_url="ops", pat_token="the-pat")
    v5.insert_customer("Acme", "2026-01-01", 1000, tracker_name="Ops DevOps",
                       tracker_project="PLAT", expected_work_pct=50, color="#ff0000")
    v5.insert_customer("Beta", "2026-01-01", 800)
    v5.insert_customer("Gamma", "2026-01-01", 500)
    for customer, project, git in [("Acme", "Build", 101), ("Acme", "Support", None),
                                   ("Beta", "Ops", None), ("Gamma", "Misc", None)]:
        v5.insert_project(customer, project, git_id=git)
    manual = [
        ("Acme", "Build", "2026-08-03 09:00", "2026-08-03 10:20", 101),  # 1333.33
        ("Acme", "Support", "2026-08-04 09:00", "2026-08-04 11:00", None),
        ("Beta", "Ops", "2026-08-05 09:00", "2026-08-05 12:00", 0),
        ("Gamma", "Misc", "2026-08-06 09:00", "2026-08-06 10:00", None),
        ("Beta", "Ops", "2026-10-25 02:30", "2026-10-25 03:30", None),  # the repeated hour
        ("Beta", "Ops", "2026-03-29 02:30", "2026-03-29 03:30", None),  # the skipped hour
    ]
    for customer, project, start, end, git in manual:
        v5.insert_manual_time_row(*_ids(v5, customer, project), start, end, git_id=git)
    v5.insert_customer("Acme", "2026-09-01", 1200)  # a raise: a new version
    v5.insert_manual_time_row(*_ids(v5, "Acme", "Build"), "2026-09-02 09:00", "2026-09-02 11:00")
    v5.insert_timer_start_row(*_ids(v5, "Beta", "Ops"), "2026-09-03 08:00")
    v5.disable_customer("Gamma")
    ok, _, parent = v5.insert_task("Release", customer_name="Acme", project_name="Build")
    v5.insert_task("Notes", customer_name="Acme")
    task_id = int(parent["task_id"])
    v5.execute_query("insert into tasks (title, parent_task_id, customer_name) values (?, ?, ?)",
                     ("Changelog", task_id, "Acme"))
    v5.insert_task("Old client work", customer_name="Nobody Ltd")
    v5.insert_saved_query("mine", "select * from time")
    v5.update_devops_data(pd.DataFrame([
        {"customer_name": "Acme", "type": "Epic", "id": 7, "title": "Platform", "state": "Active",
         "changed_date": "2026-09-01T10:00:00Z"}]), mode="append")
    v5.close()
    return path


def _report(db, path, **kw):
    prepared = importer.prepare(str(path), db, **kw)
    assert prepared.problems == [], prepared.problems
    return prepared, importer.load(prepared, db)


def test_a_5x_database_arrives_with_the_same_numbers(db, v5_file):
    prepared, result = _report(db, v5_file)

    assert prepared.kind == "5.x database"
    assert result["match"].all(), result.to_string()
    assert result["customer"].tolist() == ["Acme", "Beta", "Gamma"]
    acme = result[result.customer == "Acme"].iloc[0]
    assert (acme.entries_after, acme.cost_after) == (3, 1333.33 + 2000 + 2400)


def test_a_customers_versions_become_one_customer_with_wage_periods(db, v5_file):
    _report(db, v5_file)

    customers = db.fetch_query("select customer_name, color, tracker_project, is_enabled "
                               "from customers order by customer_name").to_dict("records")
    assert [(c["customer_name"], c["is_enabled"]) for c in customers] == [
        ("Acme", True), ("Beta", True), ("Gamma", False)]
    assert (customers[0]["color"], customers[0]["tracker_project"]) == ("#ff0000", "PLAT")
    wages = db.fetch_query(
        "select w.wage, w.valid_from::text, w.valid_to::text from customer_wages w "
        "join customers c on c.key_customer = w.fk_customer where c.customer_name = 'Acme' "
        "order by w.valid_from").values.tolist()
    assert wages == [[1000, "2026-01-01", "2026-08-31"], [1200, "2026-09-01", None]]
    # Every entry reaches Acme through its project — no second Acme.
    assert db.fetch_query("select count(*) as n from customers where customer_name = 'Acme'").n[0] == 1


def test_snapshots_are_copied_and_times_become_utc(db, v5_file):
    _report(db, v5_file)
    entries = db.fetch_query(
        """
        select te.started_at, te.ended_at, te.fk_date, te.duration_hours, te.wage_snapshot,
               te.bonus_pct_snapshot, te.cost, te.user_bonus, te.bk_work_item, p.project_name
        from time_entries te join projects p on p.key_project = te.fk_project
        order by te.key_time_entry
        """).to_dict("records")

    first = entries[0]  # 1 h 20 min at 1000/h, logged before the raise
    assert (first["duration_hours"], first["wage_snapshot"], first["cost"], first["user_bonus"]) == (
        1.3333, 1000, 1333.33, 133.33)
    assert first["started_at"].isoformat() == "2026-08-03T07:00:00+00:00"
    assert (first["bk_work_item"], first["fk_date"]) == (101, 20260803)
    assert pd.isna(entries[2]["bk_work_item"])  # git_id 0: no work item
    after_raise = next(e for e in entries if e["fk_date"] == 20260902)
    assert (after_raise["wage_snapshot"], after_raise["cost"]) == (1200, 2400)
    running = next(e for e in entries if pd.isna(e["ended_at"]))
    assert pd.isna(running["duration_hours"]) and pd.isna(running["cost"])


@pytest.mark.parametrize("day, started_utc, hours", [
    ("20261025", "2026-10-25T00:30:00+00:00", 1.0),  # 02:30 twice: the first one (CEST)
    ("20260329", "2026-03-29T01:30:00+00:00", 1.0),  # 02:30 never happened: read as CET
])
def test_dst_entries_keep_their_billed_duration(db, v5_file, day, started_utc, hours):
    """5.x billed naive clock time; the duration is copied as billed."""
    _report(db, v5_file)
    [e] = db.fetch_query("select started_at, duration_hours from time_entries "
                         "where fk_date = %s", (int(day),)).to_dict("records")

    assert (e["started_at"].isoformat(), e["duration_hours"]) == (started_utc, hours)


def test_tasks_queries_and_work_items_come_along(db, v5_file):
    prepared, _ = _report(db, v5_file)

    tasks = db.get_tasks("Created (Oldest First)", show_completed=True)
    assert set(tasks["title"]) == {"Release", "Notes", "Changelog", "Old client work"}
    child = tasks[tasks.title == "Changelog"].iloc[0]
    parent = tasks[tasks.title == "Release"].iloc[0]
    assert child["parent_task_id"] == parent["task_id"]
    assert tasks[tasks.title == "Old client work"].iloc[0]["customer_name"] is None
    assert "mine" in db.get_query_list()["query_name"].tolist()
    assert db.get_visible_devops_items()["title"].tolist() == ["Platform"]
    assert any("Nobody Ltd" in n for n in prepared.notes)
    assert any("rewrite them" in n for n in prepared.notes)


def test_tracker_tokens_come_along_with_the_5x_key(db, v5_file):
    _report(db, v5_file, pat_key_file=str(v5_file.parent / ".pat_key"))

    assert db.get_tracker_credentials("Ops DevOps") == ("devops", "ops", "the-pat")
    assert db.get_trackers().iloc[0]["pat_token"].startswith("enc:")  # this server's key


def test_without_the_5x_key_tokens_are_left_out(db, v5_file):
    prepared, _ = _report(db, v5_file)

    assert any("re-enter" in n and "Ops DevOps" in n for n in prepared.notes)
    assert db.get_tracker_credentials("Ops DevOps") == ("devops", "ops", "")


def _break_bonus(path, sql):
    v5 = Database(str(path), _quiet())
    v5.execute_query(sql)
    v5.close()


@pytest.mark.parametrize("sql, message", [
    ("update bonus set end_date = '2025-05-31' where bonus_id = 1", "ends (2025-05-31) before it starts"),
    ("insert into bonus (bonus_percent, start_date, end_date) values (0.2, '2026-03-01', null)",
     "overlap"),
])
def test_bonus_periods_v6_would_refuse_stop_the_import(db, v5_file, sql, message):
    _break_bonus(v5_file, sql)

    prepared = importer.prepare(str(v5_file), db)

    assert any(message in p for p in prepared.problems), prepared.problems
    with pytest.raises(ValueError, match="Fix these first"):
        importer.load(prepared, db)
    assert db.account_is_empty()


def test_only_an_empty_account_unless_replacing(db, v5_file):
    _report(db, v5_file)
    prepared = importer.prepare(str(v5_file), db)

    with pytest.raises(ValueError, match="already has data"):
        importer.load(prepared, db)
    result = importer.load(prepared, db, replace=True)
    assert result["match"].all()
    assert db.fetch_query("select count(*) as n from customers").n[0] == 3  # not six


def test_a_v6_export_round_trips(db, v5_file, pg_schema_db, tmp_path):
    _report(db, v5_file)
    export = db.backup_to(str(tmp_path / "export.json.gz"))
    with psycopg.connect(pg_schema_db) as admin:
        user2 = admin.execute("insert into users (bk_user) values ('two') returning key_user").fetchone()[0]
    other = PgDatabase(db.pools, db.log_engine, user_key=user2, secrets_dir=str(tmp_path))

    prepared, result = _report(other, export)

    assert prepared.kind == "v6 export"
    assert result["match"].all(), result.to_string()
    mine = db.import_totals()
    theirs = other.import_totals()
    assert mine.equals(theirs)


def test_entries_that_lost_their_project_are_kept(db, v5_file):
    v5 = Database(str(v5_file), _quiet())
    v5.execute_query("update time set project_id = 0, project_name = null "
                     "where customer_name = 'Gamma'")
    v5.close()

    prepared, result = _report(db, v5_file)

    assert result["match"].all()
    assert any("(no project)" in n for n in prepared.notes)


def test_work_item_ids_stored_as_blobs_are_read(db, v5_file):
    """Found in a real 5.x file: some git_ids are 8-byte little-endian BLOBs."""
    v5 = Database(str(v5_file), _quiet())
    v5.execute_query("update time set git_id = ? where git_id = 101",
                     ((2433).to_bytes(8, "little"),))
    v5.close()

    _report(db, v5_file)

    assert db.fetch_query("select bk_work_item from time_entries "
                          "where bk_work_item is not null").bk_work_item.tolist() == [2433]


def test_an_entry_is_dated_by_its_start_even_if_5x_cached_another_day(db, v5_file):
    """Found in a real 5.x file: a start edited later left date_key a day off."""
    v5 = Database(str(v5_file), _quiet())
    v5.execute_query("update time set date_key = 20260804 where start_time like '2026-08-03%'")
    v5.close()

    prepared, _ = _report(db, v5_file)

    assert db.fetch_query("select count(*) as n from time_entries where fk_date = 20260803").n[0] == 1
    assert any("dated by their start time" in n for n in prepared.notes)


def test_the_file_is_never_changed(db, v5_file):
    before = v5_file.read_bytes()
    _report(db, v5_file)
    assert v5_file.read_bytes() == before


def test_other_files_are_refused(db, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    with pytest.raises(ValueError, match="Not a WorkTimer"):
        importer.prepare(str(other), db)


def test_the_command_line(db, v5_file, pg_schema_db, pg_logins, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DATABASE_URL", make_conninfo(
        pg_schema_db, user="worktimer_app", password=pg_logins["worktimer_app"]))
    monkeypatch.chdir(tmp_path)  # the CLI's PAT key lives in ./data

    assert importer.main([str(v5_file), "--dry-run"]) == 0
    assert "5.x database: trackers: 1, customers: 3" in capsys.readouterr().out
    assert db.account_is_empty()

    assert importer.main([str(v5_file)]) == 0
    out = capsys.readouterr().out
    assert "Acme" in out and "False" not in out
    assert importer.main([str(v5_file)]) == 2  # not empty now
    assert importer.main([str(v5_file), "--replace"]) == 0


def test_the_reports_check_compares_every_month(db, v5_file):
    from datetime import date

    _report(db, v5_file)
    months = importer.compare_reports(str(v5_file), db, today=date(2026, 10, 31))

    assert months["month"].tolist()[0] == "2026-03" and months["month"].tolist()[-1] == "2026-10"
    assert months["match"].all(), months.to_string()
    august = months[months.month == "2026-08"].iloc[0]
    assert (august.entries_5x, august.cost_5x, august.cost_v6) == (4, 6233.33, 6233.33)


def test_the_reports_check_notices_a_difference(db, v5_file):
    from datetime import date

    _report(db, v5_file)
    db.execute_query("update time_entries set cost = cost + 1 where fk_date = 20260803")

    months = importer.compare_reports(str(v5_file), db, today=date(2026, 10, 31))

    assert months.set_index("month").loc["2026-08", "match"] == False  # noqa: E712
    assert months["match"].sum() == len(months) - 1


def test_a_zipped_data_folder_brings_its_notes_tokens_and_settings(db, v5_file, tmp_path):
    """Onboarding (v6 Phase 6): one zip of the 5.x data folder, its config
    folder beside it."""
    import zipfile

    bundle_zip = tmp_path / "worktimer-data.zip"
    with zipfile.ZipFile(bundle_zip, "w") as zf:
        zf.write(v5_file, "data/worktimer.db")
        zf.write(v5_file.parent / ".pat_key", "data/.pat_key")
        zf.writestr("data/notes/plan.md", "# Plan")
        zf.writestr("data/notes/plan_assets/img_1.png", b"png")
        zf.writestr("config/time_settings.yml", "rounding_minutes: 15\n")

    prepared, result = _report(db, bundle_zip)

    assert prepared.kind == "5.x data folder (zip)"
    assert result["match"].all(), result.to_string()
    assert not any("re-enter" in n for n in prepared.notes)  # the zip's key read the token
    assert db.get_tracker_credentials("Ops DevOps") == ("devops", "ops", "the-pat")
    assert (prepared.counts["notes"], prepared.counts["note_images"],
            prepared.counts["settings_files"]) == (1, 1, 1)
    assert prepared.note_files["plan.md"] == b"# Plan"
