"""Regression (5.1.2): a raise must not reset the customer's settings.

A raise goes through the add-customer form, which creates the customer's new
version (SCD2) from its own fields and leaves the rest blank. Before 5.1.2
only the tracker link was carried over, so colour, expected work % and the
tracker project were cleared — and with no project configured the tracker
silently fell back to the organisation's first project.
"""


def _current(db, name="Acme") -> dict:
    return db.fetch_query(
        "select customer_id, wage, color, expected_work_pct, tracker_project, "
        "integration_type, tracker_id from customers "
        "where customer_name = ? and is_current = 1",
        (name,),
    ).to_dict("records")[0]


def _acme_on_jira(db):
    db.insert_tracker("Alpha Jira", "jira", jira_site="https://a.atlassian.net",
                      jira_email="a@b.c", jira_api_token="t")
    db.insert_customer("Acme", "2026-01-01", 1000, tracker_name="Alpha Jira",
                       tracker_project="PLAT", expected_work_pct=40,
                       color="#ff0000", integration_type="jira")


def _raise_via_add_form(db, wage=1200, **fields):
    """What the add form sends for a raise: name, start date and wage, with
    the optional fields blank unless given."""
    kwargs = {"tracker_name": None, "expected_work_pct": None, "color": ""}
    kwargs.update(fields)
    db.insert_customer("Acme", "2026-09-01", wage, **kwargs)


def test_raise_keeps_the_settings_the_form_leaves_blank(db):
    _acme_on_jira(db)
    before = _current(db)

    _raise_via_add_form(db)

    after = _current(db)
    assert after["customer_id"] != before["customer_id"]  # a new version...
    assert after["wage"] == 1200
    for setting in ("color", "expected_work_pct", "tracker_project",
                    "integration_type", "tracker_id"):
        assert after[setting] == before[setting], setting  # ...same settings


def test_tracker_keeps_its_project_after_a_raise(db):
    """The consequence that mattered: the tracker connection's project."""
    _acme_on_jira(db)

    _raise_via_add_form(db)

    [conn] = db.get_tracker_connections().to_dict("records")
    assert conn["tracker_project"] == "PLAT"


def test_raise_can_still_change_settings_explicitly(db):
    _acme_on_jira(db)

    _raise_via_add_form(db, color="#00ff00", expected_work_pct=0)

    after = _current(db)
    assert after["color"] == "#00ff00"
    assert after["expected_work_pct"] == 0  # an explicit 0 is kept, not carried
    assert after["tracker_project"] == "PLAT"


# ── startup repair ──────────────────────────────────────────────────────────


def _wipe_like_before_the_fix(db):
    """Recreate the pre-5.1.2 state: the latest version's settings cleared."""
    db.execute_query(
        "update customers set color = null, expected_work_pct = null, "
        "tracker_project = null where valid_to is null"
    )


def test_startup_restores_settings_cleared_by_an_earlier_raise(db):
    _acme_on_jira(db)
    _raise_via_add_form(db)
    _wipe_like_before_the_fix(db)

    db.initialize_db()  # runs at every startup

    after = _current(db)
    assert (after["color"], after["expected_work_pct"], after["tracker_project"]) == (
        "#ff0000", 40, "PLAT")
    assert after["wage"] == 1200  # only the settings are restored
    db.initialize_db()  # idempotent
    assert _current(db)["color"] == "#ff0000"


def test_startup_restores_through_several_raises(db):
    _acme_on_jira(db)
    _raise_via_add_form(db)
    _wipe_like_before_the_fix(db)
    db.insert_customer("Acme", "2026-10-01", 1400, color="")  # another raise, carries the blanks
    _wipe_like_before_the_fix(db)

    db.initialize_db()

    assert _current(db)["tracker_project"] == "PLAT"  # from the first version


def test_startup_repair_leaves_settings_cleared_on_purpose(db):
    """Editing a customer writes its settings to every version, so a deliberate
    clear leaves no older value behind to restore."""
    _acme_on_jira(db)
    _raise_via_add_form(db)
    db.update_customer("Acme", "Acme", color="", tracker_project="")

    db.initialize_db()

    after = _current(db)
    assert not after["color"]
    assert after["tracker_project"] is None
    assert after["expected_work_pct"] == 40
