"""Stopping a timer can re-assign the entry to another of the customer's projects."""

import sqlite3

from src.database import Database


def _one(path, sql, params=()):
    con = sqlite3.connect(path)
    r = con.execute(sql, params).fetchone()
    con.close()
    return r


def _setup(tmp_path, null_logger):
    path = str(tmp_path / "t.db")
    db = Database(path, null_logger)
    db.initialize_db()
    db.insert_customer("Acme", "2026-01-01", 100)
    cid = _one(
        path,
        "select customer_id from customers where customer_name='Acme' and is_current=1",
    )[0]
    db.insert_project("Acme", "generic")
    db.insert_project("Acme", "specific")
    gen = _one(
        path,
        "select project_id from projects where project_name='generic' and customer_id=?",
        (cid,),
    )[0]
    spe = _one(
        path,
        "select project_id from projects where project_name='specific' and customer_id=?",
        (cid,),
    )[0]
    return path, db, cid, gen, spe


def test_stop_timer_reassigns_project(tmp_path, null_logger):
    path, db, cid, gen, spe = _setup(tmp_path, null_logger)
    db.insert_time_row(cid, gen)  # start on generic
    db.insert_time_row(cid, gen, comment="done", new_project_id=spe)  # stop + move

    pid, pname, comment, end_time = _one(
        path, "select project_id, project_name, comment, end_time from time"
    )
    assert pid == spe          # row moved to the specific project
    assert pname == "specific"  # denormalized name moved too (reports group by it)
    assert comment == "done"
    assert end_time is not None  # timer is stopped


def test_stop_timer_without_move_keeps_project(tmp_path, null_logger):
    path, db, cid, gen, spe = _setup(tmp_path, null_logger)
    db.insert_time_row(cid, gen)  # start
    db.insert_time_row(cid, gen, comment="x")  # stop, no re-assignment

    pid, pname = _one(path, "select project_id, project_name from time")
    assert pid == gen
    assert pname == "generic"
