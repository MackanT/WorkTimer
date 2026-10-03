"""The v6 data layer on Postgres (docs/v6_implementation.md, Phase 2).

The same public API as the SQLite ``Database`` in src/database.py, on the
schema in migrations/. Return shapes keep today's column names (aliased in
SQL) and types — floats for money and hours, local ``YYYY-MM-DD HH:MM:SS``
strings for times — so no page changes during the port. The Phase 0
characterisation tests are the oracle: they run against both classes.

Every call is one transaction for this instance's user (``Pools.transaction``);
row-level security scopes every statement to that user.

Time entries (plan step 1) are written through one path: a start snapshots the
wage and bonus in force on the entry's local date; a stop or an edit computes
the exact duration and rounds cost and user bonus once, to öre. Editing keeps
the snapshots unless the entry moves to another day — an unrelated edit must
never re-price history. Times arrive and leave as the user's local wall-clock
time (``users.timezone``) and are stored in UTC.
"""

import gzip
import json
import os
import re
from datetime import date, datetime, timedelta
from textwrap import dedent
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from psycopg.pq import TransactionStatus
from psycopg.types.numeric import FloatLoader

from . import clock
from .pat_crypto import decrypt_pat, encrypt_pat
from .pg_connection import LOCAL_USER, Pools

_CENT = Decimal("0.01")
_MICROS_PER_HOUR = Decimal(3_600_000_000)
# SQL for the user's local time: pages get today's "YYYY-MM-DD HH:MM:SS" strings.
_USER_TZ = "(select timezone from users where key_user = app_user())"
_LOCAL_TODAY = f"(now() at time zone {_USER_TZ})::date"


def _local(column: str) -> str:
    return f"to_char({column} at time zone {_USER_TZ}, 'YYYY-MM-DD HH24:MI:SS')"


def _parse_local(value: str) -> datetime:
    """A local wall-clock time in any format the UI sends."""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized datetime format: {value!r}")


def _date_key(local: datetime) -> int:
    return int(local.strftime("%Y%m%d"))


def _work_item(git_id) -> int | None:
    """"No work item" is NULL — 5.x also stored it as 0."""
    return int(git_id) if git_id else None


def _clean_expiry(token_expires) -> date | None:
    """A token-expiry form value: empty → None; anything but YYYY-MM-DD is an
    error at save time, not a warning that silently never comes."""
    value = str(token_expires or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise ValueError(f"Token expiry '{value}' is not a date (use YYYY-MM-DD)")


def _currency(value) -> str | None:
    """A currency form value: empty → None; otherwise an ISO 4217 code."""
    code = str(value or "").strip().upper()
    if not code:
        return None
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError(f"Currency '{value}' is not a three-letter code (like SEK or EUR)")
    return code


_CUSTOMER_ORDER = 'c.sort_order, c.customer_name collate "C"'  # the Time Tracker's order


def _code_only(query: str) -> str:
    """`query` with string literals, quoted identifiers, comments and
    dollar-quoted bodies blanked out — the SQL structure that is left."""
    out, i, n = [], 0, len(query)
    while i < n:
        if query.startswith("--", i):
            end = query.find("\n", i)
            i = n if end < 0 else end
        elif query.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if query.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif query.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
        elif query[i] in "'\"":
            quote, i = query[i], i + 1
            while i < n and not (query[i] == quote and query[i + 1:i + 2] != quote):
                i += 2 if query[i] == quote else 1
            i += 1
        elif m := re.match(r"\$([A-Za-z_]\w*)?\$", query[i:]):
            end = query.find(m.group(0), i + len(m.group(0)))
            i = n if end < 0 else end + len(m.group(0))
        else:
            out.append(query[i])
            i += 1
            continue
        out.append(" ")
    return "".join(out)


_USER_QUERY_START = re.compile(r"\s*\(*\s*(select|with|values|table)\b", re.IGNORECASE)


def _user_select(query: str) -> str:
    """`query`, trailing semicolons dropped, if it is one SELECT (or WITH,
    VALUES, TABLE); otherwise a ValueError worded for the user. This only
    words the refusal: the read-only role, the READ ONLY transaction and the
    one-statement protocol are what enforce it."""
    code = _code_only(query).strip()
    while code.endswith(";"):
        code = code[:-1].rstrip()
    if not code:
        raise ValueError("Write a query first")
    if ";" in code:
        raise ValueError("Run one statement at a time")
    if not _USER_QUERY_START.match(code):
        raise ValueError("Only SELECT queries run here — the query editor reads, it doesn't write")
    text = query.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def _shown(value):
    """A result value as the grid shows it: times as the user's local wall
    clock (the query ran in the user's zone)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def _money(started: datetime, ended: datetime, wage: int, bonus: Decimal):
    """(duration_hours, cost, user_bonus): the exact duration, and money
    computed from it and rounded once."""
    hours = Decimal((ended - started) // timedelta(microseconds=1)) / _MICROS_PER_HOUR
    cost = (Decimal(wage) * hours).quantize(_CENT, ROUND_HALF_UP)
    user_bonus = (Decimal(bonus) * Decimal(wage) * hours).quantize(_CENT, ROUND_HALF_UP)
    return hours, cost, user_bonus


def _public(plan: dict) -> dict:
    """A rate plan without the internals only the write needs."""
    return {k: v for k, v in plan.items() if k not in ("key", "changes")}


def _repriced(plan: dict) -> str:
    return f"; {plan['entries']} time entries re-priced" if plan["entries"] else ""


def _day(date_key: int) -> date:
    return date(date_key // 10000, date_key // 100 % 100, date_key % 100)


def _period_of(periods: list[tuple], day: date) -> int:
    """The index of the period whose rate applies on `day`, as _snapshots
    looks it up: the period holding the day, else the first."""
    for i, (start, end, _) in enumerate(periods):
        if start <= day and (end is None or day <= end):
            return i
    return 0


def _rate_on(periods: list[tuple], day: date) -> int:
    """The rate in force on `day` (0 without any period)."""
    return periods[_period_of(periods, day)][2] if periods else 0


def _with_rate(periods: list[tuple], start: date, wage: int) -> list[tuple]:
    """`periods` — (valid_from, valid_to or None, wage), oldest first — with
    `wage` in force from `start` until the next change after it: a period it
    cuts into ends the day before, one starting that day is replaced, and
    neighbours with the same rate merge."""
    later = [p for p in periods if p[0] > start]
    end = later[0][0] - timedelta(days=1) if later else None
    earlier = [(f, t if t is not None and t < start else start - timedelta(days=1), w)
               for f, t, w in periods if f < start]
    merged = []
    for f, t, w in sorted([*earlier, (start, end, wage), *later]):
        if merged and merged[-1][2] == w and merged[-1][1] == f - timedelta(days=1):
            merged[-1] = (merged[-1][0], t, w)
        else:
            merged.append((f, t, w))
    return merged


class PgDatabase:
    backend = "postgres"

    def __init__(self, pools: Pools, log_engine, user_key: int = LOCAL_USER,
                 secrets_dir: str = "data"):
        self.pools = pools
        self.log_engine = log_engine
        self.user_key = user_key
        # pat_crypto keeps the Fernet key (.pat_key) beside "the database
        # file"; for Postgres that is secrets_dir — data/, as in 5.x.
        self.db_file = os.path.join(secrets_dir, "postgres")

    # ── plumbing ────────────────────────────────────────────────────────────

    def _tx(self):
        return self.pools.transaction(self.user_key)

    @staticmethod
    def _df(conn, query: str, params=None) -> pd.DataFrame:
        cur = conn.cursor()
        cur.adapters.register_loader("numeric", FloatLoader)  # today's floats
        cur.execute(query, params)
        columns = [c.name for c in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=columns)

    @staticmethod
    def _one(conn, query: str, params=None):
        row = conn.execute(query, params).fetchone()
        return row[0] if row else None

    @staticmethod
    def _timezone(conn) -> ZoneInfo:
        return ZoneInfo(conn.execute(
            "select timezone from users where key_user = app_user()").fetchone()[0])

    def initialize_db(self) -> None:
        """The schema comes from migrations (src/migrator.py). At startup:
        this user's default saved queries — the query editor's presets —
        are added or brought up to date (the editor can't change them)."""
        with self._tx() as conn:
            self._seed_default_queries(conn)

    def _seed_default_queries(self, conn) -> None:
        for name, text in self.DEFAULT_QUERIES.items():
            row = conn.execute(
                "select key_saved_query, is_default from saved_queries "
                "where query_name = %s and deleted_at is null", (name,)).fetchone()
            if row is None:
                conn.execute("insert into saved_queries (query_name, query_sql, is_default) "
                             "values (%s, %s, true)", (name, text))
            elif row[1]:
                conn.execute("update saved_queries set query_sql = %s "
                             "where key_saved_query = %s and query_sql is distinct from %s",
                             (text, row[0], text))

    def close(self) -> None:
        self.pools.close()

    def fetch_query(self, query: str, params=None) -> pd.DataFrame:
        with self._tx() as conn:
            return self._df(conn, query, params)

    def execute_query(self, query: str, params=None) -> None:
        with self._tx() as conn:
            conn.execute(query, params)

    # ── time entries: the one write path ────────────────────────────────────

    @staticmethod
    def _snapshots(conn, key_project: int, day: date) -> tuple[int, Decimal]:
        """(wage, bonus) in force on `day`. Before a customer's first wage
        period the first wage applies; with no bonus period, no bonus."""
        wage = conn.execute(
            """
            select w.wage
            from customer_wages w
            join projects p on p.fk_customer = w.fk_customer
            where p.key_project = %(project)s
            order by (%(day)s between w.valid_from and coalesce(w.valid_to, 'infinity')) desc,
                     w.valid_from
            limit 1
            """,
            {"project": key_project, "day": day},
        ).fetchone()
        bonus = conn.execute(
            """
            select bonus_pct from bonuses
            where deleted_at is null
              and %s between valid_from and coalesce(valid_to, 'infinity')
            """,
            (day,),
        ).fetchone()
        return (wage[0] if wage else 0), (bonus[0] if bonus else Decimal(0))

    def _start(self, conn, key_project: int, start: datetime, tz: ZoneInfo,
               git_id=None, comment=None) -> int:
        wage, bonus = self._snapshots(conn, key_project, start.date())
        return self._one(
            conn,
            """
            insert into time_entries (fk_project, started_at, fk_date, wage_snapshot,
                                      bonus_pct_snapshot, bk_work_item, comment)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning key_time_entry
            """,
            (key_project, start.replace(tzinfo=tz), _date_key(start), wage, bonus,
             _work_item(git_id), comment),
        )

    @staticmethod
    def _stop(conn, key_time_entry: int, ended: datetime, **changes) -> None:
        """End (or re-price) an entry from its stored start and snapshots;
        `changes` are further columns to set in the same update."""
        started, wage, bonus = conn.execute(
            "select started_at, wage_snapshot, bonus_pct_snapshot from time_entries "
            "where key_time_entry = %s", (key_time_entry,)).fetchone()
        hours, cost, user_bonus = _money(started, ended, wage or 0, bonus or 0)
        columns = {"ended_at": ended, "duration_hours": hours, "cost": cost,
                   "user_bonus": user_bonus, **changes}
        assignments = ", ".join(f"{c} = %({c})s" for c in columns)
        conn.execute(
            f"update time_entries set {assignments} where key_time_entry = %(key)s",
            {**columns, "key": key_time_entry},
        )

    def insert_time_row(
        self, customer_id: int, project_id: int, git_id: int = None,
        comment: str = None, new_project_id: int = None, end_time: str = None,
    ):
        """Toggle the project's timer: start one at now, or stop the running
        one — optionally at `end_time`, and re-assigned to `new_project_id`."""
        with self._tx() as conn:
            tz = self._timezone(conn)
            now = clock.now_in(tz).replace(microsecond=0)
            running = self._one(
                conn,
                "select key_time_entry from time_entries "
                "where fk_project = %s and ended_at is null and deleted_at is null "
                "order by key_time_entry desc limit 1",
                (project_id,),
            )
            if running is None:
                self._start(conn, project_id, now, tz)
                self.log_engine.info(f"Starting timer for project {project_id}")
                return
            ended = (_parse_local(end_time) if end_time else now).replace(tzinfo=tz)
            moving = new_project_id is not None and int(new_project_id) != int(project_id)
            changes = {"comment": comment, "bk_work_item": _work_item(git_id)}
            if moving:
                changes["fk_project"] = int(new_project_id)
            self._stop(conn, running, ended, **changes)
            self.log_engine.info(
                f"Ending timer for project {project_id}"
                + (f" (re-assigned to {new_project_id})" if moving else ""))

    def insert_timer_start_row(self, customer_id: int, project_id: int, start_time: str):
        """Start a timer at an explicit (local) time instead of now."""
        with self._tx() as conn:
            self._start(conn, project_id, _parse_local(start_time), self._timezone(conn))

    def insert_manual_time_row(
        self, customer_id: int, project_id: int, start_time: str, end_time: str,
        git_id: int = None, comment: str = None,
    ):
        """A complete entry with explicit (local) start and end."""
        with self._tx() as conn:
            tz = self._timezone(conn)
            key = self._start(conn, project_id, _parse_local(start_time), tz, git_id, comment)
            self._stop(conn, key, _parse_local(end_time).replace(tzinfo=tz))

    def delete_time_row(self, customer_id: int, project_id: int) -> None:
        """Discard the project's running timer."""
        with self._tx() as conn:
            conn.execute(
                """
                update time_entries set deleted_at = now()
                where key_time_entry = (
                    select key_time_entry from time_entries
                    where fk_project = %s and ended_at is null and deleted_at is null
                    order by key_time_entry desc limit 1
                )
                """,
                (project_id,),
            )

    def update_time_entry(
        self, time_id: int, start_time: str = None, end_time: str = None,
        comment: str = None, git_id: int = None,
    ) -> None:
        """Edit only the given fields; the cost follows the new times."""
        with self._tx() as conn:
            self._edit_time_entry(conn, int(time_id), start_time, end_time, comment, git_id)

    def _edit_time_entry(self, conn, key: int, start_time=None, end_time=None,
                         comment=None, git_id=None, project: int = None) -> None:
        """The edit half of the write path ("Manage entries" and the query
        editor's row edit). Snapshots stay unless the entry moves to another
        day; a completed entry is re-priced from its (new) times."""
        row = conn.execute(
            "select fk_project, started_at, ended_at, fk_date, wage_snapshot, bonus_pct_snapshot "
            "from time_entries where key_time_entry = %s and deleted_at is null", (key,)).fetchone()
        if row is None:
            return
        key_project, started, ended, fk_date, wage, bonus = row
        tz = self._timezone(conn)
        changes = {}
        if comment is not None:
            changes["comment"] = comment or None
        if git_id is not None:
            changes["bk_work_item"] = _work_item(git_id)
        if project is not None and project != key_project:
            changes["fk_project"] = key_project = project
        if start_time is not None:
            start = _parse_local(start_time)
            started = start.replace(tzinfo=tz)
            changes.update(started_at=started, fk_date=_date_key(start))
            if _date_key(start) != fk_date:  # another day: that day's wage and bonus
                wage, bonus = self._snapshots(conn, key_project, start.date())
                changes.update(wage_snapshot=wage, bonus_pct_snapshot=bonus)
        if end_time is not None:
            ended = _parse_local(end_time).replace(tzinfo=tz)
            changes["ended_at"] = ended
        if not changes:
            return
        if ended is not None:  # re-priced in the same statement: no half-edited row
            hours, cost, user_bonus = _money(started, ended, wage or 0, bonus or 0)
            changes.update(duration_hours=hours, cost=cost, user_bonus=user_bonus)
        assignments = ", ".join(f"{c} = %({c})s" for c in changes)
        conn.execute(f"update time_entries set {assignments} where key_time_entry = %(key)s",
                     {**changes, "key": key})

    def delete_time_entry(self, time_id: int) -> None:
        with self._tx() as conn:
            conn.execute("update time_entries set deleted_at = now() "
                         "where key_time_entry = %s", (int(time_id),))

    # ── customers ───────────────────────────────────────────────────────────

    @staticmethod
    def _tracker_key(conn, tracker_name: str):
        key = PgDatabase._one(conn, "select key_tracker from trackers where tracker_name = %s",
                              (tracker_name,))
        if key is None:
            raise ValueError(f"No tracker named '{tracker_name}'")
        return key

    def insert_customer(
        self, customer_name: str, start_date: str, wage: int, org_url: str = None,
        pat_token: str = None, valid_from: str = None, tracker_project: str = None,
        expected_work_pct: float = None, color: str = None, integration_type: str = None,
        tracker_name: str = None, currency: str = None,
    ):
        """A new customer (in `currency`, SEK when blank) — or, for an existing
        name, a wage change from `start_date`: the current period closes the
        day before. Settings passed blank keep their values; a wage change
        never changes the currency."""
        start = date.fromisoformat(str(start_date)[:10])
        wage = int(round(float(wage)))
        currency = _currency(currency) or "SEK"
        with self._tx() as conn:
            tracker = self._tracker_key(conn, tracker_name) if tracker_name else None
            key = self._one(conn, "select key_customer from customers where customer_name = %s",
                            (customer_name,))
            if key is None:
                key = self._one(
                    conn,
                    "insert into customers (customer_name, color, fk_tracker, tracker_project, "
                    "expected_work_pct, currency) values (%s, %s, %s, %s, %s, %s) "
                    "returning key_customer",
                    (customer_name, color or None, tracker, tracker_project or None,
                     expected_work_pct, currency),
                )
                self.log_engine.info(f"Inserted new customer '{customer_name}'")
            else:
                changes = {"is_enabled": True}
                if tracker is not None:
                    changes["fk_tracker"] = tracker
                if tracker_project:
                    changes["tracker_project"] = tracker_project
                if expected_work_pct is not None:
                    changes["expected_work_pct"] = expected_work_pct
                if color:
                    changes["color"] = color
                assignments = ", ".join(f"{c} = %({c})s" for c in changes)
                conn.execute(f"update customers set {assignments} where key_customer = %(key)s",
                             {**changes, "key": key})
                current = self._one(conn, "select valid_from from customer_wages "
                                          "where fk_customer = %s and valid_to is null", (key,))
                if current is not None and start <= current:
                    raise ValueError(
                        f"A wage change for '{customer_name}' must start after "
                        f"{current:%Y-%m-%d}, when the current wage began")
                plan = self._rate_plan(conn, customer_name, wage, start)
                self._apply_rate_plan(conn, plan)
                self.log_engine.info(f"New wage {wage} for '{customer_name}' from {start}"
                                     f"{_repriced(plan)}")
                return
            conn.execute("insert into customer_wages (fk_customer, wage, valid_from) "
                         "values (%s, %s, %s)", (key, wage, start))

    def update_customer(
        self, customer_name: str, new_customer_name: str, org_url: str = None,
        pat_token: str = None, tracker_project: str = None, expected_work_pct: float = None,
        color: str = None, integration_type: str = None, tracker_name: str = None,
        currency: str = None, wage=None, rate_from=None,
    ):
        """Rename and edit settings. None leaves a setting unchanged; "" clears
        it. The tracker type comes from the linked tracker. The currency can
        change only while the customer has no time entries (v6_plan §4).
        `wage` from `rate_from` is set as set_customer_rate does — a no-op when
        that is already the rate from then until the next change."""
        currency = _currency(currency)
        with self._tx() as conn:
            if wage not in (None, "") and rate_from:
                plan = self._rate_plan(conn, customer_name, wage, rate_from)
                self._apply_rate_plan(conn, plan)
                if plan["after"] != plan["before"] or plan["entries"]:
                    self.log_engine.info(
                        f"Rate {plan['wage']} {plan['currency']} for '{customer_name}' "
                        f"from {plan['valid_from']}{_repriced(plan)}")
            changes = {"customer_name": new_customer_name}
            if currency is not None:
                current = conn.execute(
                    "select c.currency, exists (select from time_entries te join projects p "
                    "on p.key_project = te.fk_project where p.fk_customer = c.key_customer) "
                    "from customers c where c.customer_name = %s", (customer_name,)).fetchone()
                if current and current[0] != currency:
                    if current[1]:
                        raise ValueError(
                            f"The currency of '{customer_name}' is fixed once it has time "
                            f"entries (it is {current[0]})")
                    changes["currency"] = currency
            if tracker_name is not None:
                changes["fk_tracker"] = self._tracker_key(conn, tracker_name) if tracker_name else None
            if tracker_project is not None:
                changes["tracker_project"] = tracker_project or None
            if expected_work_pct is not None:
                changes["expected_work_pct"] = expected_work_pct
            if color is not None:
                changes["color"] = color or None
            assignments = ", ".join(f"{c} = %({c})s" for c in changes)
            conn.execute(f"update customers set {assignments} where customer_name = %(name)s",
                         {**changes, "name": customer_name})

    # ── hourly rates ────────────────────────────────────────────────────────

    def preview_customer_rate(self, customer_name: str, wage, valid_from) -> dict:
        """What set_customer_rate would change, without changing it: the rate
        periods before and after, and the time entries it re-prices."""
        with self._tx() as conn:
            return _public(self._rate_plan(conn, customer_name, wage, valid_from))

    def set_customer_rate(self, customer_name: str, wage, valid_from) -> dict:
        """`wage` becomes the customer's hourly rate from `valid_from` until the
        next change after it — back-dated or not. Entries dated in that span
        are re-priced at it: the one exception to entries keeping the rate
        they were logged at (v6_plan §3) is changing the rate for their dates."""
        with self._tx() as conn:
            plan = self._rate_plan(conn, customer_name, wage, valid_from)
            self._apply_rate_plan(conn, plan)
        self.log_engine.info(f"Rate {plan['wage']} {plan['currency']} for '{customer_name}' "
                             f"from {plan['valid_from']}{_repriced(plan)}")
        return _public(plan)

    def _rate_plan(self, conn, customer_name: str, wage, valid_from) -> dict:
        wage = int(round(float(wage)))
        if wage < 0:
            raise ValueError("An hourly rate can't be negative")
        start = date.fromisoformat(str(valid_from)[:10])
        row = conn.execute("select key_customer, currency from customers where customer_name = %s",
                           (customer_name,)).fetchone()
        if row is None:
            raise ValueError(f"No customer named '{customer_name}'")
        key, currency = row
        before = [tuple(p) for p in conn.execute(
            "select valid_from, valid_to, wage from customer_wages where fk_customer = %s "
            "order by valid_from", (key,))]
        after = _with_rate(before, start, wage)
        changes, days = [], []
        cost_before = cost_after = Decimal(0)
        # Per period after the change: (entries re-priced, their cost before, after).
        effects = [[0, Decimal(0), Decimal(0)] for _ in after]
        for entry, date_key, started, ended, old_wage, bonus, cost in conn.execute(
                "select te.key_time_entry, te.fk_date, te.started_at, te.ended_at, "
                "te.wage_snapshot, te.bonus_pct_snapshot, te.cost "
                "from time_entries te join projects p on p.key_project = te.fk_project "
                "where p.fk_customer = %s and te.deleted_at is null", (key,)):
            day = _day(date_key)
            new_wage = _rate_on(after, day)
            if new_wage == _rate_on(before, day) or new_wage == old_wage:
                continue  # the rate for its day is unchanged, or already its own
            effect = effects[_period_of(after, day)]
            effect[0] += 1
            new_cost = new_bonus = None
            if ended is not None:  # a running timer is priced when it stops
                _, new_cost, new_bonus = _money(started, ended, new_wage, bonus or 0)
                cost_before += cost or 0
                cost_after += new_cost
                effect[1] += cost or 0
                effect[2] += new_cost
            changes.append((new_wage, new_cost, new_bonus, entry))
            days.append(day)
        return {
            "key": key, "customer_name": customer_name, "currency": currency,
            "wage": wage, "valid_from": start, "before": before, "after": after,
            "changes": changes, "entries": len(changes),
            "effects": [tuple(e) for e in effects],
            "first_day": min(days, default=None), "last_day": max(days, default=None),
            "cost_before": cost_before, "cost_after": cost_after,
        }

    @staticmethod
    def _apply_rate_plan(conn, plan: dict) -> None:
        # Periods that stay keep their rows; valid_from is unique per customer.
        for valid_from, _, _ in (p for p in plan["before"] if p not in plan["after"]):
            conn.execute("delete from customer_wages where fk_customer = %s and valid_from = %s",
                         (plan["key"], valid_from))
        new = [(plan["key"], *p) for p in plan["after"] if p not in plan["before"]]
        with conn.cursor() as cur:
            if new:
                cur.executemany(
                    "insert into customer_wages (fk_customer, valid_from, valid_to, wage) "
                    "values (%s, %s, %s, %s)", new)
            if plan["changes"]:
                cur.executemany(
                    "update time_entries set wage_snapshot = %s, cost = %s, user_bonus = %s "
                    "where key_time_entry = %s", plan["changes"])

    def disable_customer(self, customer_name: str):
        self.execute_query("update customers set is_enabled = false where customer_name = %s",
                           (customer_name,))

    def enable_customer(self, customer_name: str):
        self.execute_query("update customers set is_enabled = true where customer_name = %s",
                           (customer_name,))

    # ── projects ────────────────────────────────────────────────────────────

    def insert_project(self, customer_name: str, project_name: str, git_id: int = None):
        with self._tx() as conn:
            customer = self._one(conn, "select key_customer from customers "
                                       "where customer_name = %s and is_enabled", (customer_name,))
            if customer is None:
                raise ValueError(f"No active customer named '{customer_name}'")
            existing = conn.execute(
                "select key_project, is_enabled from projects "
                "where fk_customer = %s and project_name = %s", (customer, project_name)).fetchone()
            if existing is None:
                conn.execute("insert into projects (fk_customer, project_name, bk_work_item) "
                             "values (%s, %s, %s)", (customer, project_name, _work_item(git_id)))
            elif existing[1]:
                self.log_engine.warning(
                    f"Project '{project_name}' for customer '{customer_name}' already exists")
            else:
                conn.execute("update projects set is_enabled = true where key_project = %s",
                             (existing[0],))

    def update_project(self, customer_name: str, project_name: str, new_project_name: str,
                       new_git_id: int = None):
        """None leaves the default work item unchanged; 0 clears it."""
        changes = {"project_name": new_project_name}
        if new_git_id is not None:
            changes["bk_work_item"] = _work_item(new_git_id)
        assignments = ", ".join(f"{c} = %({c})s" for c in changes)
        self.execute_query(
            f"""
            update projects set {assignments}
            where project_name = %(project)s and fk_customer = (
                select key_customer from customers
                where customer_name = %(customer)s and is_enabled
            )
            """,
            {**changes, "project": project_name, "customer": customer_name},
        )

    def _set_project_enabled(self, customer_name: str, project_name: str, enabled: bool):
        self.execute_query(
            """
            update projects set is_enabled = %(enabled)s
            where project_name = %(project)s and fk_customer = (
                select key_customer from customers
                where customer_name = %(customer)s and is_enabled
            )
            """,
            {"enabled": enabled, "project": project_name, "customer": customer_name},
        )

    def disable_project(self, customer_name: str, project_name: str):
        self._set_project_enabled(customer_name, project_name, False)

    def enable_project(self, customer_name: str, project_name: str):
        self._set_project_enabled(customer_name, project_name, True)

    # ── bonuses ─────────────────────────────────────────────────────────────

    def insert_bonus(self, start_date: str, bonus_percent: int) -> None:
        """A new bonus rate from `start_date`; the open period closes the day before."""
        start = date.fromisoformat(str(start_date)[:10])
        with self._tx() as conn:
            conn.execute("update bonuses set valid_to = %s "
                         "where valid_to is null and deleted_at is null",
                         (start - timedelta(days=1),))
            conn.execute("insert into bonuses (bonus_pct, valid_from) values (%s, %s)",
                         (round(min(bonus_percent / 100, 1), 3), start))

    # ── reads ───────────────────────────────────────────────────────────────

    def get_customer_name(self, customer_id: int) -> str:
        with self._tx() as conn:
            return self._one(conn, "select customer_name from customers where key_customer = %s",
                             (customer_id,)) or ""

    def get_project_name(self, project_id: int) -> str:
        with self._tx() as conn:
            return self._one(conn, "select project_name from projects where key_project = %s",
                             (project_id,)) or ""

    def get_data_input_list(self) -> pd.DataFrame:
        """Every customer (with its latest wage) and its projects."""
        return self.fetch_query(
            """
            select c.customer_name,
                   c.key_customer               as customer_id,
                   p.project_name,
                   p.key_project                as project_id,
                   coalesce(p.bk_work_item, 0)  as git_id,
                   w.wage,
                   p.is_enabled::integer        as p_current,
                   c.is_enabled::integer        as c_current
            from customers c
            left join lateral (
                select wage from customer_wages
                where fk_customer = c.key_customer
                order by valid_from desc limit 1
            ) w on true
            left join projects p on p.fk_customer = c.key_customer
            order by c.key_customer, p.key_project
            """
        )

    def get_customer_ui_list(self, start_date: str, end_date: str) -> pd.DataFrame:
        """The Time Tracker: every enabled project of every enabled customer
        with its hours and bonus (in the customer's currency) between two
        YYYYMMDD dates — running timers counted up to now — in the user's order."""
        return self.fetch_query(
            """
            with totals as (
                select te.fk_project,
                       sum(coalesce(te.duration_hours,
                                    extract(epoch from now() - te.started_at) / 3600)) as total_time,
                       sum(coalesce(te.user_bonus,
                                    extract(epoch from now() - te.started_at) / 3600
                                    * te.wage_snapshot * te.bonus_pct_snapshot)) as user_bonus
                from time_entries te
                where te.deleted_at is null and te.fk_date between %s and %s
                group by te.fk_project
            )
            select c.key_customer                         as customer_id,
                   c.customer_name,
                   p.key_project                          as project_id,
                   p.project_name,
                   round(coalesce(t.total_time, 0), 2)    as total_time,
                   round(coalesce(t.user_bonus, 0), 2)    as user_bonus,
                   c.currency,
                   c.sort_order                           as customer_sort_order,
                   p.sort_order                           as project_sort_order
            from projects p
            join customers c on c.key_customer = p.fk_customer and c.is_enabled
            left join totals t on t.fk_project = p.key_project
            where p.is_enabled
            order by c.sort_order, c.customer_name collate "C",
                     p.sort_order, p.project_name collate "C"
            """,
            (int(start_date), int(end_date)),
        )

    # ── the Time Tracker ────────────────────────────────────────────────────

    def save_sort_order(self, customer_order: list, project_orders: dict) -> bool:
        """customer_order: [(customer_id, name)]; project_orders: {customer_id:
        [(project_id, name)]} — each list in display order."""
        try:
            with self._tx() as conn:
                for position, (customer_id, _) in enumerate(customer_order):
                    conn.execute("update customers set sort_order = %s where key_customer = %s",
                                 (position, customer_id))
                for projects in project_orders.values():
                    for position, (project_id, _) in enumerate(projects):
                        conn.execute("update projects set sort_order = %s where key_project = %s",
                                     (position, project_id))
            return True
        except Exception as e:
            self.log_engine.error(f"Error saving sort order: {e}")
            return False

    def get_current_customers(self) -> pd.DataFrame:
        """Enabled customers — id, name, colour, expected work % — by name."""
        return self.fetch_query(
            'select key_customer as customer_id, customer_name, color, expected_work_pct '
            'from customers where is_enabled order by customer_name collate "C"')

    def get_current_customers_in_sort_order(self) -> pd.DataFrame:
        """Enabled customers — id, name, colour, sort position (so) — in the
        user's order, then by name."""
        return self.fetch_query(
            'select key_customer as customer_id, customer_name, color, sort_order as so '
            'from customers where is_enabled order by so, customer_name collate "C"')

    def get_current_projects_for_customer(self, customer_id: int) -> pd.DataFrame:
        """A customer's enabled projects (project_id, project_name), by name."""
        return self.fetch_query(
            'select key_project as project_id, project_name from projects '
            'where fk_customer = %s and is_enabled order by project_name collate "C"',
            (customer_id,))

    def get_customer_project_info(self, customer_id: int, project_id: int) -> pd.DataFrame:
        """customer_name, project_name and default work item (git_id) of a
        customer/project pair; empty if they don't belong together."""
        return self.fetch_query(
            """
            select c.customer_name, p.project_name, coalesce(p.bk_work_item, 0) as git_id
            from customers c join projects p on p.fk_customer = c.key_customer
            where c.key_customer = %s and p.key_project = %s
            """,
            (customer_id, project_id))

    def get_logged_project_info(self, customer_id: int, project_id: int) -> pd.DataFrame:
        """customer_name, project_name and default work item (git_id) of a
        pair that has time entries; empty when it has none."""
        return self.fetch_query(
            """
            select c.customer_name, p.project_name, coalesce(p.bk_work_item, 0) as git_id
            from customers c join projects p on p.fk_customer = c.key_customer
            where c.key_customer = %s and p.key_project = %s
              and exists (select from time_entries te
                          where te.fk_project = p.key_project and te.deleted_at is null)
            """,
            (customer_id, project_id))

    def get_running_timers(self) -> pd.DataFrame:
        """customer_id and project_id of every running timer."""
        return self.fetch_query(
            """
            select p.fk_customer as customer_id, te.fk_project as project_id
            from time_entries te join projects p on p.key_project = te.fk_project
            where te.ended_at is null and te.deleted_at is null
            order by te.key_time_entry
            """)

    def get_running_timer_names(self) -> pd.DataFrame:
        """customer_name and project_name of every running timer, by name."""
        return self.fetch_query(
            """
            select c.customer_name, p.project_name
            from time_entries te
            join projects p on p.key_project = te.fk_project
            join customers c on c.key_customer = p.fk_customer
            where te.ended_at is null and te.deleted_at is null
            order by c.customer_name collate "C", p.project_name collate "C"
            """)

    def get_running_timer_start(self, customer_id: int, project_id: int) -> pd.DataFrame:
        """start_time (local) of the project's latest running timer; empty if none."""
        return self.fetch_query(
            f"""
            select {_local('te.started_at')} as start_time
            from time_entries te join projects p on p.key_project = te.fk_project
            where p.fk_customer = %s and te.fk_project = %s
              and te.ended_at is null and te.deleted_at is null
            order by te.key_time_entry desc limit 1
            """,
            (customer_id, project_id))

    def get_completed_entries(self, customer_id: int, project_id: int,
                              start_key: int, end_key: int) -> pd.DataFrame:
        """A project's completed entries dated in [start_key, end_key]
        (YYYYMMDD), newest first — found through the project, so entries from
        before a wage change are included."""
        return self.fetch_query(
            f"""
            select te.key_time_entry as time_id,
                   {_local('te.started_at')} as start_time,
                   {_local('te.ended_at')} as end_time,
                   te.duration_hours as total_time,
                   te.comment
            from time_entries te join projects p on p.key_project = te.fk_project
            where p.fk_customer = %s and te.fk_project = %s
              and te.ended_at is not null and te.deleted_at is null
              and te.fk_date between %s and %s
            order by te.started_at desc
            """,
            (customer_id, project_id, int(start_key), int(end_key)))

    def get_first_entry_date(self) -> pd.DataFrame:
        """min_date: the (local) date of the earliest entry, ISO; NULL when none."""
        return self.fetch_query(
            "select to_char(to_date(min(fk_date)::text, 'YYYYMMDD'), 'YYYY-MM-DD') as min_date "
            "from time_entries where deleted_at is null")

    def get_recent_project_hours(self, customer_id: int) -> pd.DataFrame:
        """Hours per project (project_id, h) for a customer over the last 60
        days, running timers counted up to now — through the projects, so
        entries from before a wage change count."""
        return self.fetch_query(
            f"""
            select te.fk_project as project_id,
                   sum(coalesce(te.duration_hours,
                                extract(epoch from now() - te.started_at) / 3600)) as h
            from time_entries te join projects p on p.key_project = te.fk_project
            where p.fk_customer = %s and te.deleted_at is null
              and te.fk_date >= to_char({_LOCAL_TODAY} - 60, 'YYYYMMDD')::integer
            group by te.fk_project
            order by te.fk_project
            """,
            (customer_id,))

    def get_running_timers_with_names(self) -> pd.DataFrame:
        """customer_id, project_id, customer_name, project_name of every
        running timer, by name."""
        return self.fetch_query(
            """
            select p.fk_customer as customer_id, te.fk_project as project_id,
                   c.customer_name, p.project_name
            from time_entries te
            join projects p on p.key_project = te.fk_project
            join customers c on c.key_customer = p.fk_customer
            where te.ended_at is null and te.deleted_at is null
            order by c.customer_name collate "C", p.project_name collate "C"
            """)

    def get_current_customer_projects(self) -> pd.DataFrame:
        """Every enabled project of every enabled customer, by customer and
        project name."""
        return self.fetch_query(
            """
            select c.key_customer as customer_id, c.customer_name,
                   p.key_project as project_id, p.project_name
            from customers c join projects p on p.fk_customer = c.key_customer
            where c.is_enabled and p.is_enabled
            order by c.customer_name collate "C", p.project_name collate "C"
            """)

    def get_customer_color(self, customer_name: str):
        with self._tx() as conn:
            return self._one(conn, "select color from customers "
                                   "where customer_name = %s and is_enabled", (customer_name,)) or None

    # ── entity dialogs (customers and projects) ─────────────────────────────
    # Customer lists follow the Time Tracker's order (a decision for the port:
    # SQLite had no ORDER BY and showed row order).

    def get_current_customer_names(self) -> pd.DataFrame:
        return self.fetch_query(
            f"select c.customer_name from customers c where c.is_enabled order by {_CUSTOMER_ORDER}")

    def get_current_customer_details(self) -> pd.DataFrame:
        """Update-dialog prefills for every enabled customer — the hourly rate
        the one in force today (as _snapshots finds it), so a form saved with
        the rate untouched changes no rate."""
        return self.fetch_query(
            f"""
            select c.customer_name, c.tracker_project, c.expected_work_pct, c.color,
                   t.tracker_name, c.currency, w.wage
            from customers c left join trackers t on t.key_tracker = c.fk_tracker
            left join lateral (
                select w.wage from customer_wages w
                where w.fk_customer = c.key_customer
                order by ((now() at time zone (select timezone from users
                                               where key_user = app_user()))::date
                          between w.valid_from and coalesce(w.valid_to, 'infinity')) desc,
                         w.valid_from
                limit 1
            ) w on true
            where c.is_enabled
            order by {_CUSTOMER_ORDER}
            """)

    def get_disabled_customer_names(self) -> pd.DataFrame:
        return self.fetch_query(
            f"select c.customer_name from customers c where not c.is_enabled "
            f"order by {_CUSTOMER_ORDER}")

    def get_current_project_names(self) -> pd.DataFrame:
        return self.fetch_query(
            f"""
            select p.project_name
            from projects p join customers c on c.key_customer = p.fk_customer
            where p.is_enabled
            order by {_CUSTOMER_ORDER}, p.project_name collate "C"
            """)

    def get_current_projects_with_customer(self) -> pd.DataFrame:
        return self.fetch_query(
            f"""
            select p.project_name, coalesce(p.bk_work_item, 0) as git_id, c.customer_name
            from projects p join customers c on c.key_customer = p.fk_customer
            where p.is_enabled
            order by {_CUSTOMER_ORDER}, p.project_name collate "C"
            """)

    def get_disabled_projects_with_customer(self) -> pd.DataFrame:
        """Disabled projects — each can be re-enabled, whatever other
        customers' projects are called."""
        return self.fetch_query(
            f"""
            select p.project_name, c.customer_name
            from projects p join customers c on c.key_customer = p.fk_customer
            where not p.is_enabled
            order by {_CUSTOMER_ORDER}, p.project_name collate "C"
            """)

    # ── trackers ────────────────────────────────────────────────────────────

    def get_tracker_id(self, tracker_name: str):
        with self._tx() as conn:
            return self._one(conn, "select key_tracker from trackers where tracker_name = %s",
                             (tracker_name,))

    def get_tracker_credentials(self, tracker_name: str):
        """(integration_type, org_url, DECRYPTED pat) for a tracker, or None.
        Server-side only."""
        with self._tx() as conn:
            row = conn.execute("select integration_type, org_url, pat_token from trackers "
                               "where tracker_name = %s", (tracker_name,)).fetchone()
        if row is None:
            return None
        return row[0], row[1] or "", decrypt_pat(row[2] or "", self.db_file, self.log_engine) or ""

    def insert_tracker(self, tracker_name: str, integration_type: str = None,
                       org_url: str = None, pat_token: str = None, jira_site: str = None,
                       jira_email: str = None, jira_api_token: str = None,
                       token_expires: str = None):
        """Jira's site/email/token fields pack into org_url and an
        email:token PAT. The PAT is stored encrypted — the schema refuses
        anything else."""
        if self.get_tracker_id(tracker_name):
            raise ValueError(f"Tracker '{tracker_name}' already exists")
        if not pat_token and jira_email and jira_api_token:
            pat_token = f"{jira_email.strip()}:{jira_api_token.strip()}"
        if pat_token:
            pat_token = encrypt_pat(pat_token, self.db_file, self.log_engine)
        self.execute_query(
            "insert into trackers (tracker_name, integration_type, org_url, pat_token, "
            "token_expires) values (%s, %s, %s, %s, %s)",
            (tracker_name, integration_type or "devops", org_url or jira_site, pat_token,
             _clean_expiry(token_expires)),
        )

    def update_tracker(self, tracker_name: str, new_tracker_name: str = None,
                       integration_type: str = None, org_url: str = None,
                       pat_token: str = None, jira_site: str = None, jira_email: str = None,
                       jira_api_token: str = None, token_expires: str = None):
        """Empty/None leaves a field unchanged. A partial Jira edit (email or
        token) merges with the stored value."""
        changes = {}
        if new_tracker_name and new_tracker_name != tracker_name:
            changes["tracker_name"] = new_tracker_name
        if integration_type:
            changes["integration_type"] = integration_type
        if org_url or jira_site:
            changes["org_url"] = org_url or jira_site
        if not pat_token and (jira_email or jira_api_token):
            current = self.get_tracker_credentials(tracker_name)
            cur_email, _, cur_token = (current[2] if current else "").partition(":")
            email = (jira_email or cur_email).strip()
            token = (jira_api_token or cur_token).strip()
            if email and token:
                pat_token = f"{email}:{token}"
        if pat_token:
            changes["pat_token"] = encrypt_pat(pat_token, self.db_file, self.log_engine)
        if token_expires:
            changes["token_expires"] = _clean_expiry(token_expires)
        if not changes:
            return
        assignments = ", ".join(f"{c} = %({c})s" for c in changes)
        self.execute_query(f"update trackers set {assignments} where tracker_name = %(name)s",
                           {**changes, "name": tracker_name})

    def delete_tracker(self, tracker_name: str):
        """Remove a tracker; its customers are detached (the foreign key sets
        their link to NULL)."""
        with self._tx() as conn:
            if not conn.execute("delete from trackers where tracker_name = %s",
                                (tracker_name,)).rowcount:
                raise ValueError(f"Tracker '{tracker_name}' not found")

    def get_tracker_names(self) -> pd.DataFrame:
        return self.fetch_query('select tracker_name from trackers order by tracker_name collate "C"')

    def get_trackers(self) -> pd.DataFrame:
        """Every tracker by name, the PAT as stored (encrypted)."""
        return self.fetch_query(
            "select tracker_name, integration_type, org_url, pat_token, "
            "to_char(token_expires, 'YYYY-MM-DD') as token_expires "
            'from trackers order by tracker_name collate "C"')

    def get_tracker_types(self) -> pd.DataFrame:
        return self.fetch_query('select tracker_name, integration_type as itype '
                                'from trackers order by tracker_name collate "C"')

    def get_tracker_expiries(self) -> pd.DataFrame:
        return self.fetch_query(
            "select tracker_name, to_char(token_expires, 'YYYY-MM-DD') as token_expires "
            'from trackers where token_expires is not null order by tracker_name collate "C"')

    def get_customer_tracker_names(self) -> dict:
        """{customer_name: tracker_name} for enabled customers with a tracker."""
        df = self.fetch_query(
            "select c.customer_name, t.tracker_name from customers c "
            "join trackers t on t.key_tracker = c.fk_tracker where c.is_enabled")
        return dict(zip(df["customer_name"], df["tracker_name"]))

    def get_tracker_connections(self) -> pd.DataFrame:
        """One row per enabled customer with a usable tracker connection
        (credentials from its tracker). Feeds TrackerEngine.setup_manager."""
        return self.fetch_query(
            f"""
            select c.customer_name, t.pat_token, t.org_url, c.tracker_project,
                   t.integration_type
            from customers c join trackers t on t.key_tracker = c.fk_tracker
            where c.is_enabled and coalesce(t.pat_token, '') != '' and coalesce(t.org_url, '') != ''
            order by {_CUSTOMER_ORDER}
            """)

    # ── reports ─────────────────────────────────────────────────────────────
    # Entries count on the (local) day they start; a running timer counts its
    # hours up to now but has no cost yet. Disabled customers' time is
    # included. Soft-deleted entries never count.

    _REPORT_HOURS = "coalesce(te.duration_hours, extract(epoch from now() - te.started_at) / 3600)"
    _REPORT_FROM = """
        from time_entries te
        join projects p on p.key_project = te.fk_project
        join customers c on c.key_customer = p.fk_customer
        where te.deleted_at is null and te.fk_date between %(first)s and %(last)s
          and (%(customers)s::text[] is null or c.customer_name = any(%(customers)s::text[]))
    """

    @staticmethod
    def _report_params(start: str, end: str, customers=None) -> dict:
        """ISO dates → YYYYMMDD keys; no customers (None or empty) = all."""
        return {"first": int(str(start).replace("-", "")), "last": int(str(end).replace("-", "")),
                "customers": list(customers) if customers else None}

    def report_totals(self, start: str, end: str, customers=None) -> pd.DataFrame:
        """One row: h = hours incl. running timers, c = cost, cth = completed
        hours, n = entries, d = distinct days."""
        return self.fetch_query(
            f"""
            select coalesce(sum({self._REPORT_HOURS}), 0) as h,
                   coalesce(sum(te.cost), 0) as c,
                   coalesce(sum(te.duration_hours), 0) as cth,
                   count(*) as n,
                   count(distinct te.fk_date) as d
            {self._REPORT_FROM}
            """,
            self._report_params(start, end, customers))

    def report_amounts(self, start: str, end: str, customers=None) -> pd.DataFrame:
        """Money per currency — never summed across currencies (v6_plan §4):
        one row per currency with entries in the range; h = hours incl.
        running timers, c = cost, cth = completed hours."""
        return self.fetch_query(
            f"""
            select c.currency,
                   coalesce(sum({self._REPORT_HOURS}), 0) as h,
                   coalesce(sum(te.cost), 0) as c,
                   coalesce(sum(te.duration_hours), 0) as cth
            {self._REPORT_FROM}
            group by c.currency
            order by c.currency
            """,
            self._report_params(start, end, customers))

    def report_hours_for_rounding(self, start: str, end: str, customers, basis: str) -> pd.DataFrame:
        """Hours per billing-rounding unit (h, positive only, with its
        currency): one per entry for 'entry', per project for 'project',
        otherwise per work item — all untagged time of a currency is one unit
        ("no work item" is NULL however it was logged)."""
        hours = self._REPORT_HOURS
        if basis == "entry":
            query = (f"select c.currency, {hours} as h {self._REPORT_FROM} and {hours} > 0 "
                     f"order by te.key_time_entry")
        else:
            unit = "te.fk_project" if basis == "project" else "te.bk_work_item"
            query = (f"select c.currency, sum({hours}) as h {self._REPORT_FROM} "
                     f"group by c.currency, {unit} having sum({hours}) > 0 "
                     f"order by c.currency, {unit}")
        return self.fetch_query(query, self._report_params(start, end, customers))

    def report_hours_by_project(self, start: str, end: str, customers=None) -> pd.DataFrame:
        """Top 12 projects by hours: k = project, cust = customer, h = hours."""
        return self.fetch_query(
            f"""
            select p.project_name as k, c.customer_name as cust, sum({self._REPORT_HOURS}) as h
            {self._REPORT_FROM}
            group by p.key_project, p.project_name, c.customer_name
            having sum({self._REPORT_HOURS}) > 0
            order by h desc, p.project_name collate "C", c.customer_name collate "C"
            limit 12
            """,
            self._report_params(start, end, customers))

    def report_hours_by_customer(self, start: str, end: str, customers=None) -> pd.DataFrame:
        """Top 12 customers by hours: k = customer, h = hours."""
        return self.fetch_query(
            f"""
            select c.customer_name as k, sum({self._REPORT_HOURS}) as h
            {self._REPORT_FROM}
            group by c.key_customer, c.customer_name
            having sum({self._REPORT_HOURS}) > 0
            order by h desc, c.customer_name collate "C"
            limit 12
            """,
            self._report_params(start, end, customers))

    def report_hours_by_day(self, start: str, end: str, customers=None) -> pd.DataFrame:
        """Hours per day, oldest first: d = ISO date, h = hours."""
        return self.fetch_query(
            f"""
            select to_char(to_date(te.fk_date::text, 'YYYYMMDD'), 'YYYY-MM-DD') as d,
                   sum({self._REPORT_HOURS}) as h
            {self._REPORT_FROM}
            group by te.fk_date
            order by te.fk_date
            """,
            self._report_params(start, end, customers))

    def report_hours_by_work_item(self, start: str, end: str, customers=None) -> pd.DataFrame:
        """Top 10 work items by hours: gid = work item, cust = customer, h =
        hours. Untagged time is excluded."""
        return self.fetch_query(
            f"""
            select te.bk_work_item as gid, c.customer_name as cust, sum({self._REPORT_HOURS}) as h
            {self._REPORT_FROM} and te.bk_work_item is not null
            group by te.bk_work_item, c.customer_name
            having sum({self._REPORT_HOURS}) > 0
            order by h desc, gid
            limit 10
            """,
            self._report_params(start, end, customers))

    # ── tasks ───────────────────────────────────────────────────────────────
    # A task names its customer and project through keys now; reads return
    # today's column names (customer_name, project_name, completed, …).

    _TASK_SELECT = f"""
        select t.key_task as task_id, t.title, t.description, t.status, t.priority,
               t.is_completed::integer as completed, t.assigned_to,
               c.customer_name, p.project_name, t.fk_parent_task as parent_task_id,
               to_char(t.due_date, 'YYYY-MM-DD') as due_date,
               t.estimated_hours, t.actual_hours, t.progress_pct as progress_percentage,
               t.tags,
               {_local('t.created_at')} as created_at,
               {_local('t.updated_at')} as updated_at,
               {_local('t.completed_at')} as completed_at,
               cu.display_name as created_by, uu.display_name as updated_by
        from tasks t
        left join customers c on c.key_customer = t.fk_customer
        left join projects p on p.key_project = t.fk_project
        left join users cu on cu.key_user = t.created_by
        left join users uu on uu.key_user = t.updated_by
        where t.deleted_at is null
    """

    # The toolbar's sort labels (single source of truth, as in Database).
    # NULLs sort as in 5.x: undated tasks last in the due-date sorts, and —
    # explicitly, since Postgres puts NULLs last — first everywhere else.
    TASK_SORTS = {
        "Due Date (Earliest First)": "order by t.due_date is null, t.due_date, t.key_task",
        "Due Date (Latest First)": "order by t.due_date is null, t.due_date desc, t.key_task",
        "Priority (High to Low)": """order by case t.priority
            when 'Critical' then 1 when 'High' then 2
            when 'Medium' then 3 when 'Low' then 4 else 5 end, t.key_task""",
        "Priority (Low to High)": """order by case t.priority
            when 'Critical' then 1 when 'High' then 2
            when 'Medium' then 3 when 'Low' then 4 else 5 end desc, t.key_task""",
        "Status": "order by t.is_completed, t.due_date nulls first, t.key_task",
        "Customer": 'order by c.customer_name collate "C" nulls first, t.due_date nulls first, t.key_task',
        "Project": 'order by p.project_name collate "C" nulls first, t.due_date nulls first, t.key_task',
        "Created (Newest First)": "order by t.created_at desc, t.key_task desc",
        "Created (Oldest First)": "order by t.created_at, t.key_task",
    }

    @classmethod
    def task_sort_clause(cls, sort_by: str) -> str:
        return cls.TASK_SORTS.get(sort_by, cls.TASK_SORTS["Due Date (Earliest First)"])

    @staticmethod
    def _task_refs(conn, customer_name, project_name):
        """(fk_customer, fk_project) for the names a task form sends. A
        project named without its customer is found if its name is unique."""
        customer = project = None
        if customer_name:
            customer = PgDatabase._one(conn, "select key_customer from customers "
                                             "where customer_name = %s", (customer_name,))
            if customer is None:
                raise ValueError(f"No customer named '{customer_name}'")
        if project_name:
            rows = conn.execute(
                "select key_project, fk_customer from projects where project_name = %s "
                "and (%s::integer is null or fk_customer = %s)",
                (project_name, customer, customer)).fetchall()
            if len(rows) != 1:
                raise ValueError(f"No single project named '{project_name}'"
                                 + (f" for '{customer_name}'" if customer_name else ""))
            project, customer = rows[0]
        return customer, project

    def insert_task(self, title: str, description: str = None, status: str = "To Do",
                    priority: str = "Medium", assigned_to: str = None,
                    customer_name: str = None, project_name: str = None,
                    due_date: str = None, estimated_hours: float = 0, tags: str = None,
                    created_by: str = None):
        """(ok, message, task as a dict)."""
        try:
            with self._tx() as conn:
                customer, project = self._task_refs(conn, customer_name, project_name)
                key = self._one(
                    conn,
                    """
                    insert into tasks (title, description, status, priority, assigned_to,
                                       fk_customer, fk_project, due_date, estimated_hours, tags)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning key_task
                    """,
                    (title, description, status or "To Do", priority or "Medium", assigned_to,
                     customer, project, due_date or None, estimated_hours or 0, tags))
                task = self._df(conn, self._TASK_SELECT + " and t.key_task = %s", (key,))
            return True, f"Task '{title}' created successfully", task.iloc[0].to_dict()
        except Exception as e:
            self.log_engine.error(f"Failed to create task '{title}': {e}")
            return False, f"Failed to create task '{title}': {e}", None

    def update_task(self, task_id: int, title: str = None, description: str = None,
                    status: str = None, priority: str = None, assigned_to: str = None,
                    due_date: str = None, estimated_hours: float = None,
                    actual_hours: float = None, progress_percentage: int = None,
                    tags: str = None, updated_by: str = None):
        """Only the given fields; (ok, message). Who updated it is recorded
        from the transaction's user."""
        changes = {k: v for k, v in {
            "title": title, "description": description, "status": status,
            "priority": priority, "assigned_to": assigned_to, "due_date": due_date,
            "estimated_hours": estimated_hours, "actual_hours": actual_hours,
            "progress_pct": progress_percentage, "tags": tags,
        }.items() if v is not None}
        if not changes:
            return False, "No fields to update for task"
        if "due_date" in changes:
            changes["due_date"] = changes["due_date"] or None
        assignments = ", ".join(f"{c} = %({c})s" for c in changes)
        if status == "Done":
            assignments += ", completed_at = now()"
        try:
            self.execute_query(f"update tasks set {assignments} "
                               "where key_task = %(key)s and deleted_at is null",
                               {**changes, "key": task_id})
            return True, f"Task {task_id} updated successfully"
        except Exception as e:
            self.log_engine.error(f"Failed to update task {task_id}: {e}")
            return False, f"Failed to update task {task_id}: {e}"

    def delete_task(self, task_id: int):
        """Soft delete; (ok, message)."""
        with self._tx() as conn:
            title = self._one(conn, "update tasks set deleted_at = now() "
                                    "where key_task = %s and deleted_at is null returning title",
                              (task_id,))
        if title is None:
            return False, f"Task {task_id} not found"
        return True, f"Task '{title}' (ID: {task_id}) deleted successfully"

    def set_task_completion(self, task_id: int, completed: bool):
        with self._tx() as conn:
            title = self._one(
                conn,
                "update tasks set is_completed = %(done)s, "
                "completed_at = case when %(done)s then now() end "
                "where key_task = %(key)s and deleted_at is null returning title",
                {"done": bool(completed), "key": task_id})
        if title is None:
            return False, f"Task {task_id} not found"
        action = "completed" if completed else "marked as incomplete"
        return True, f"Task '{title}' (ID: {task_id}) {action}"

    def get_task_by_id(self, task_id: int):
        """The task as a pandas Series, or None."""
        df = self.fetch_query(self._TASK_SELECT + " and t.key_task = %s", (task_id,))
        return df.iloc[0] if not df.empty else None

    def get_tasks_by_customer(self, customer_name: str = None) -> pd.DataFrame:
        if customer_name:
            return self.fetch_query(self._TASK_SELECT + " and c.customer_name = %s "
                                    "order by t.created_at desc, t.key_task desc", (customer_name,))
        return self.fetch_query(self._TASK_SELECT + " order by t.created_at desc, t.key_task desc")

    def get_tasks(self, sort_by: str = "Due Date (Earliest First)",
                  show_completed: bool = False) -> pd.DataFrame:
        where = "" if show_completed else " and not t.is_completed"
        return self.fetch_query(self._TASK_SELECT + where + " " + self.task_sort_clause(sort_by))

    def get_task_titles(self) -> pd.DataFrame:
        return self.fetch_query('select key_task as task_id, title from tasks '
                                'where deleted_at is null order by title collate "C", key_task')

    # ── saved queries ───────────────────────────────────────────────────────
    # The default queries are rewritten for the new schema in Phase 3, with
    # the query editor's read-only lockdown (run_user_query, check_user_query).

    def get_query_list(self) -> pd.DataFrame:
        return self.fetch_query(
            "select query_name, query_sql, is_default::integer as is_default "
            "from saved_queries where deleted_at is null order by key_saved_query")

    def insert_saved_query(self, query_name: str, query_sql: str) -> None:
        """Names are unique among a user's saved queries."""
        self.execute_query("insert into saved_queries (query_name, query_sql) values (%s, %s)",
                           (query_name, query_sql))

    def update_saved_query(self, query_name: str, query_sql: str) -> None:
        self.execute_query("update saved_queries set query_sql = %s "
                           "where query_name = %s and deleted_at is null", (query_sql, query_name))

    def delete_saved_query(self, query_name: str) -> None:
        self.execute_query("update saved_queries set deleted_at = now() "
                           "where query_name = %s and deleted_at is null", (query_name,))

    # ── work items (the tracker cache) ──────────────────────────────────────
    # The sync hands over frames in trackers.base.WORK_ITEM_COLUMNS; reads
    # return them in the same shape.

    _WORK_ITEM_SELECT = """
        select c.customer_name, w.item_type as type, w.bk_work_item as id, w.title, w.state,
               w.bk_parent_work_item as parent_id, w.board_column,
               w.is_done::integer as board_column_done, w.assigned_to,
               to_char(w.changed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') as changed_date,
               w.priority, w.description_text as description
        from work_items w join customers c on c.key_customer = w.fk_customer
    """
    _WORK_ITEM_FIELDS = {  # WORK_ITEM_COLUMNS name → column
        "type": "item_type", "title": "title", "state": "state",
        "parent_id": "bk_parent_work_item", "board_column": "board_column",
        "board_column_done": "is_done", "assigned_to": "assigned_to",
        "changed_date": "changed_at", "priority": "priority", "description": "description_text",
    }

    @staticmethod
    def _work_item_value(column: str, value):
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            return False if column == "is_done" else None
        if column == "is_done":
            return bool(value)
        if column in ("bk_parent_work_item", "priority"):
            return int(value)
        if column == "changed_at":  # without an offset: UTC
            return pd.to_datetime(value, utc=True).to_pydatetime()
        return value

    def get_visible_devops_items(self) -> pd.DataFrame:
        """Cached work items of enabled customers — a disabled customer's
        items stay cached but leave the board and pickers."""
        return self.fetch_query(self._WORK_ITEM_SELECT +
                                " where c.is_enabled order by c.key_customer, w.bk_work_item")

    def get_devops_watermarks(self) -> pd.DataFrame:
        """Per customer_name: the highest cached id (max_id) and latest change
        (max_changed_date, ISO, UTC) — the incremental sync's starting point."""
        return self.fetch_query(
            """
            select c.customer_name, max(w.bk_work_item) as max_id,
                   to_char(max(w.changed_at) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
                       as max_changed_date
            from work_items w join customers c on c.key_customer = w.fk_customer
            group by c.key_customer, c.customer_name
            order by c.customer_name collate "C"
            """)

    def update_devops_data(self, df: pd.DataFrame, mode: str = "replace"):
        """Write synced work items. 'replace' swaps the whole cache (a full
        sync); 'append' and 'merge' upsert by customer and id. Rows of a
        customer that no longer exists are skipped."""
        if df.empty or len(df.columns) == 0:
            self.log_engine.warning("No DevOps data to update. No changes made.")
            return
        if mode not in ("replace", "append", "merge"):
            self.log_engine.error(f"Invalid mode '{mode}'. Must be 'replace', 'append', or 'merge'.")
            return
        fields = [f for f in self._WORK_ITEM_FIELDS if f in df.columns]
        columns = ["fk_customer", "bk_work_item"] + [self._WORK_ITEM_FIELDS[f] for f in fields]
        with self._tx() as conn:
            customers = dict(conn.execute("select customer_name, key_customer from customers"))
            rows, unknown = [], set()
            for record in df.to_dict("records"):
                customer = customers.get(record.get("customer_name"))
                if customer is None:
                    unknown.add(record.get("customer_name"))
                    continue
                rows.append([customer, int(record["id"])] + [
                    self._work_item_value(self._WORK_ITEM_FIELDS[f], record.get(f)) for f in fields])
            if unknown:
                self.log_engine.warning(f"Skipped work items of unknown customers: {sorted(map(str, unknown))}")
            if mode == "replace":
                conn.execute("delete from work_items")
            updates = ", ".join(f"{c} = excluded.{c}" for c in columns[2:])
            conn.cursor().executemany(
                f"insert into work_items ({', '.join(columns)}) "
                f"values ({', '.join(['%s'] * len(columns))}) "
                "on conflict (fk_user, fk_customer, bk_work_item) do update set "
                f"{updates}, synced_at = now()",
                rows,
            )
        self.log_engine.info(f"Work items: {mode} {len(rows)} records")

    def update_devops_item_fields(self, work_item_id: int, fields: dict, customer_name: str = None):
        """Write-through after a successful tracker update, so the cache shows
        the change before the next sync. Only known fields are written."""
        safe = {self._WORK_ITEM_FIELDS[k]: v for k, v in (fields or {}).items()
                if k in ("state", "board_column", "board_column_done", "assigned_to",
                         "changed_date", "priority", "title")}
        if not safe:
            return
        changes = {c: self._work_item_value(c, v) for c, v in safe.items()}
        assignments = ", ".join(f"{c} = %({c})s" for c in changes)
        self.execute_query(
            f"""
            update work_items set {assignments}
            where bk_work_item = %(id)s
              and (%(customer)s::text is null or fk_customer =
                   (select key_customer from customers where customer_name = %(customer)s))
            """,
            {**changes, "id": int(work_item_id), "customer": customer_name})

    # ── the query editor's row edit (plan step 2) ───────────────────────────
    # Rows are addressed by the 5.x table names the editor detects. Every save
    # goes through an entity path — a time entry through the write path, so
    # its cost follows its times; there is no generic UPDATE builder.

    _ROW_EDIT_FIELDS = {
        "time": {"project_name", "start_time", "end_time", "comment", "git_id"},
        "customers": {"expected_work_pct", "color"},
        "projects": {"git_id"},
    }

    @classmethod
    def _row_edit_table(cls, table_name: str) -> str:
        if table_name not in cls._ROW_EDIT_FIELDS:
            raise ValueError(f"Table '{table_name}' is not editable here")
        return table_name

    def get_query_edit_data(self, table_name: str, pk: int) -> pd.DataFrame:
        """The row-edit dialog's current values for one row."""
        table = self._row_edit_table(table_name)
        if table == "time":
            return self.fetch_query(
                f"""
                select p.fk_customer as customer_id, te.fk_project as project_id,
                       p.project_name,
                       {_local('te.started_at')} as start_time,
                       {_local('te.ended_at')} as end_time,
                       te.comment, coalesce(te.bk_work_item, 0) as git_id, c.customer_name
                from time_entries te
                join projects p on p.key_project = te.fk_project
                join customers c on c.key_customer = p.fk_customer
                where te.key_time_entry = %s and te.deleted_at is null
                """, (pk,))
        if table == "projects":
            return self.fetch_query(
                "select coalesce(p.bk_work_item, 0) as git_id, c.customer_name "
                "from projects p join customers c on c.key_customer = p.fk_customer "
                "where p.key_project = %s", (pk,))
        return self.fetch_query(
            "select expected_work_pct, color from customers where key_customer = %s", (pk,))

    def update_data_from_query(self, **kwargs):
        """Save the row-edit dialog: table_name, pk_data = (pk column, pk),
        and the dialog's fields."""
        table = self._row_edit_table(kwargs.pop("table_name", None))
        pk = int(kwargs.pop("pk_data")[1])
        unknown = set(kwargs) - self._ROW_EDIT_FIELDS[table]
        if unknown:
            raise ValueError(f"Invalid column(s) {sorted(unknown)} for table '{table}'")
        with self._tx() as conn:
            if table == "time":
                project = None
                if "project_name" in kwargs:
                    project = self._one(
                        conn,
                        """
                        select sibling.key_project
                        from time_entries te
                        join projects own on own.key_project = te.fk_project
                        join projects sibling on sibling.fk_customer = own.fk_customer
                        where te.key_time_entry = %s and sibling.project_name = %s
                        """, (pk, kwargs["project_name"]))
                    if project is None:
                        raise ValueError(
                            f"No project named '{kwargs['project_name']}' for this entry's customer")
                self._edit_time_entry(conn, pk, kwargs.get("start_time"), kwargs.get("end_time"),
                                      kwargs.get("comment", ""), kwargs.get("git_id"), project)
            elif table == "projects":
                if "git_id" in kwargs:
                    conn.execute("update projects set bk_work_item = %s where key_project = %s",
                                 (_work_item(kwargs["git_id"]), pk))
            else:
                changes = {k: (v if k != "color" else v or None) for k, v in kwargs.items()}
                if changes:
                    assignments = ", ".join(f"{c} = %({c})s" for c in changes)
                    conn.execute(f"update customers set {assignments} where key_customer = %(key)s",
                                 {**changes, "key": pk})

    def get_sibling_project_names(self, project_id: int) -> pd.DataFrame:
        """Enabled projects of the customer that owns project_id, by name."""
        return self.fetch_query(
            """
            select sibling.project_name
            from projects own join projects sibling on sibling.fk_customer = own.fk_customer
            where own.key_project = %s and sibling.is_enabled
            order by sibling.project_name collate "C"
            """, (project_id,))

    def get_project_list_from_project_id(self, project_id: int) -> pd.DataFrame:
        """Every project (project_id, project_name) of the customer that owns project_id."""
        return self.fetch_query(
            """
            select sibling.key_project as project_id, sibling.project_name
            from projects own join projects sibling on sibling.fk_customer = own.fk_customer
            where own.key_project = %s
            order by sibling.key_project
            """, (project_id,))

    # ── backup: this user's data (plan step 8) ──────────────────────────────
    # "Backup now" and "Download" export the user's own rows through the app
    # role — row-level security applies, no other credential is needed. The
    # whole database is backed up by compose's "backup" service (pg_dump as
    # the admin, scripts/pg_backup.sh).

    BACKUP_SUFFIX = ".json.gz"
    EXPORT_FORMAT = "worktimer-v6-export"
    _EXPORT_TABLES = {  # parents first; table → key column
        "trackers": "key_tracker", "customers": "key_customer",
        "customer_wages": "key_customer_wage", "projects": "key_project",
        "bonuses": "key_bonus", "time_entries": "key_time_entry", "tasks": "key_task",
        "saved_queries": "key_saved_query", "work_items": "key_work_item",
    }

    @staticmethod
    def _exported(value):
        """JSON for a column value — money and hours exact (Decimal as text),
        times ISO 8601 with their UTC offset."""
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    def export_data(self) -> dict:
        """Every row of this user's (soft-deleted ones included — they are
        history), from one consistent snapshot, keys kept."""
        from .migrator import discover

        with self._tx() as conn:
            conn.execute("set transaction isolation level repeatable read")
            user = conn.execute(
                "select bk_user, email, display_name, timezone from users "
                "where key_user = app_user()").fetchone()
            tables = {}
            for table, key in self._EXPORT_TABLES.items():
                cur = conn.execute(f"select * from {table} order by {key}")
                columns = [c.name for c in cur.description]
                tables[table] = [dict(zip(columns, map(self._exported, row))) for row in cur]
        return {
            "format": self.EXPORT_FORMAT,
            "format_version": 1,
            "schema_version": max(m.version for m in discover()),
            "exported_at": clock.now_in(ZoneInfo("UTC")).isoformat() + "+00:00",
            "user": dict(zip(("bk_user", "email", "display_name", "timezone"), user)),
            "tables": tables,
        }

    def backup_to(self, dest_path: str) -> str:
        """Write export_data() to dest_path as gzipped JSON."""
        with gzip.open(dest_path, "wt", encoding="utf-8") as f:
            json.dump(self.export_data(), f, ensure_ascii=False)
        return dest_path

    # ── the query editor (Phase 3) ──────────────────────────────────────────
    # Users' own SQL: one SELECT, on worktimer_readonly for this user, in a
    # READ ONLY transaction, sent as a prepared statement (the server refuses
    # a second statement), in the user's time zone, capped in time and rows.

    USER_QUERY_ROWS = 5000
    USER_QUERY_TIMEOUT_MS = 15_000

    EDITOR_FALLBACK_QUERY = "select * from v_time_entries order by started_at desc limit 100"

    # The table a query reads from → (the row-edit dialog's table, its key).
    ROW_EDIT_TABLES = {
        "v_time_entries": ("time", "key_time_entry"),
        "time_entries": ("time", "key_time_entry"),
        "customers": ("customers", "key_customer"),
        "projects": ("projects", "key_project"),
    }

    DEFAULT_QUERIES = {name: dedent(text).strip() for name, text in {
        "time": """
            select key_time_entry, started_at, ended_at, round(duration_hours, 2) as hours,
                   customer_name, project_name, cost, currency, bk_work_item, comment
            from v_time_entries
            order by started_at desc
            limit 100
            """,
        "customers": """
            select c.key_customer, c.customer_name, w.wage, c.currency,
                   c.expected_work_pct, c.color, t.tracker_name, c.is_enabled
            from customers c
            left join customer_wages w on w.fk_customer = c.key_customer and w.valid_to is null
            left join trackers t on t.key_tracker = c.fk_tracker
            order by c.sort_order, c.customer_name
            """,
        "projects": """
            select p.key_project, p.project_name, c.customer_name, p.bk_work_item, p.is_enabled
            from projects p
            join customers c on c.key_customer = p.fk_customer
            order by c.customer_name, p.project_name
            """,
        "weekly": """
            with current_period as (
                select te.customer_name, te.project_name, sum(te.duration_hours) as hours
                from v_time_entries te
                join dates d on d.key_date = te.fk_date
                join dates today on today.date = current_date
                where d.iso_year = today.iso_year and d.week = today.week
                group by te.customer_name, te.project_name
            )
            select customer_name, project_name, hours from (
                select 1 as part, customer_name, project_name, round(hours, 2) as hours
                from current_period
                union all select 2, '', '', null
                union all select 3, customer_name, 'total', round(sum(hours), 2)
                from current_period group by customer_name
            ) rows
            order by part, customer_name, project_name
            """,
        "monthly": """
            with current_period as (
                select te.customer_name, te.project_name, sum(te.duration_hours) as hours
                from v_time_entries te
                join dates d on d.key_date = te.fk_date
                join dates today on today.date = current_date
                where d.year = today.year and d.month = today.month
                group by te.customer_name, te.project_name
            )
            select customer_name, project_name, hours from (
                select 1 as part, customer_name, project_name, round(hours, 2) as hours
                from current_period
                union all select 2, '', '', null
                union all select 3, customer_name, 'total', round(sum(hours), 2)
                from current_period group by customer_name
            ) rows
            order by part, customer_name, project_name
            """,
    }.items()}

    def _user_query_tx(self):
        with self._tx() as conn:
            timezone = self._timezone(conn).key
        return self.pools.transaction(self.user_key, readonly=True,
                                      timeout_ms=self.USER_QUERY_TIMEOUT_MS, timezone=timezone)

    def run_user_query(self, query: str) -> pd.DataFrame:
        """The query editor's Run: the rows (at most USER_QUERY_ROWS;
        ``df.attrs["truncated"]`` says whether there were more)."""
        text = _user_select(query)
        with self._user_query_tx() as conn:
            # A server-side cursor: only the rows fetched cross over (a query
            # returning millions can't fill this shared process's memory), it
            # takes exactly one query, and it leaves nothing on the pooled
            # connection for the next user to see. Closed with the transaction.
            with conn.cursor(name="user_query") as cur:
                cur.adapters.register_loader("numeric", FloatLoader)
                cur.execute(text)
                columns = [c.name for c in cur.description]
                rows = cur.fetchmany(self.USER_QUERY_ROWS + 1)
        df = pd.DataFrame([tuple(map(_shown, row)) for row in rows[:self.USER_QUERY_ROWS]],
                          columns=columns)
        df.attrs["truncated"] = len(rows) > self.USER_QUERY_ROWS
        return df

    def check_user_query(self, query: str) -> None:
        """Raise if the query would be refused or is invalid — planned
        (EXPLAIN), never run."""
        text = _user_select(query)
        with self._user_query_tx() as conn:
            # prepare=True: the extended protocol, which takes one statement
            # only; then dropped — the pool's next user must not see it.
            try:
                conn.cursor().execute("explain " + text, prepare=True)
            finally:
                if conn.info.transaction_status == TransactionStatus.INTRANS:
                    conn.execute("deallocate all")

    # ── import (Phase 4) ────────────────────────────────────────────────────
    # Loads data in the export shape (tables of rows with their source keys):
    # a v6 export, or a 5.x file turned into one by src/importer_v5.py. Keys
    # are new — every reference is remapped. Tracker tokens arrive as
    # plaintext (or None) and are encrypted with this server's key.

    _IMPORT_TABLES = {  # parents first; table → (key, columns written, references)
        "trackers": ("key_tracker", ["tracker_name", "integration_type", "org_url", "pat_token",
                                     "token_expires", "created_at"], {}),
        "customers": ("key_customer", ["customer_name", "currency", "color", "fk_tracker",
                                       "tracker_project", "expected_work_pct", "sort_order",
                                       "is_enabled", "created_at"], {"fk_tracker": "trackers"}),
        "customer_wages": ("key_customer_wage", ["fk_customer", "wage", "valid_from", "valid_to",
                                                 "created_at"], {"fk_customer": "customers"}),
        "projects": ("key_project", ["fk_customer", "project_name", "bk_work_item", "is_enabled",
                                     "sort_order", "created_at"], {"fk_customer": "customers"}),
        "bonuses": ("key_bonus", ["bonus_pct", "valid_from", "valid_to", "created_at",
                                  "deleted_at"], {}),
        "time_entries": ("key_time_entry", ["fk_project", "started_at", "ended_at", "fk_date",
                                            "duration_hours", "wage_snapshot", "bonus_pct_snapshot",
                                            "cost", "user_bonus", "bk_work_item", "comment",
                                            "created_at", "updated_at", "deleted_at"],
                         {"fk_project": "projects"}),
        "tasks": ("key_task", ["fk_customer", "fk_project", "fk_parent_task", "title",
                               "description", "status", "priority", "is_completed", "assigned_to",
                               "due_date", "estimated_hours", "actual_hours", "progress_pct",
                               "tags", "completed_at", "created_at", "updated_at", "deleted_at"],
                  {"fk_customer": "customers", "fk_project": "projects", "fk_parent_task": "tasks"}),
        "saved_queries": ("key_saved_query", ["query_name", "query_sql", "created_at",
                                              "deleted_at"], {}),
        "work_items": ("key_work_item", ["fk_customer", "bk_work_item", "bk_parent_work_item",
                                         "display_ref", "item_type", "title", "state",
                                         "board_column", "is_done", "assigned_to", "changed_at",
                                         "priority", "description_text", "synced_at"],
                       {"fk_customer": "customers"}),
    }
    _NUMERIC = {"duration_hours", "cost", "user_bonus", "bonus_pct_snapshot", "bonus_pct",
                "expected_work_pct", "estimated_hours", "actual_hours"}
    _DATES = {"valid_from", "valid_to", "due_date", "token_expires"}

    def _import_value(self, column: str, value):
        """An export value (JSON text for money, dates, times) as its column's type."""
        if value is None:
            return None
        if column in self._NUMERIC:
            return Decimal(str(value))
        if column in self._DATES:
            return date.fromisoformat(str(value)[:10])
        if column.endswith("_at"):
            stamp = datetime.fromisoformat(str(value))
            if stamp.tzinfo is None:
                raise ValueError(f"{column} {value!r} has no UTC offset")
            return stamp
        if column == "pat_token":
            return encrypt_pat(value, self.db_file, self.log_engine)
        return value

    @staticmethod
    def _account_is_empty(conn) -> bool:
        """Nothing of the user's but the default saved queries."""
        return not conn.execute(
            """
            select exists (select from customers) or exists (select from trackers)
                or exists (select from bonuses) or exists (select from tasks)
                or exists (select from work_items)
                or exists (select from saved_queries where not is_default)
            """).fetchone()[0]

    def account_is_empty(self) -> bool:
        with self._tx() as conn:
            return self._account_is_empty(conn)

    def import_export(self, data: dict, replace: bool = False) -> dict:
        """Load export-shaped `data` into this user's account in one
        transaction; {table: rows loaded}. Refused unless the account is
        empty — or `replace`, which first deletes all of the user's data.
        Default saved queries are skipped; this server's defaults are
        re-seeded instead."""
        tables = data.get("tables", {})
        loaded = {}
        with self._tx() as conn:
            if replace:
                for table in ("time_entries", "tasks", "work_items", "customers", "bonuses",
                              "trackers"):
                    conn.execute(f"delete from {table}")
                conn.execute("delete from saved_queries where not is_default")
            elif not self._account_is_empty(conn):
                raise ValueError("This account already has data — import into an empty "
                                 "account, or choose to replace everything")
            keys: dict[str, dict] = {table: {} for table in self._IMPORT_TABLES}
            for table, (key, columns, refs) in self._IMPORT_TABLES.items():
                rows = tables.get(table) or []
                if table == "saved_queries":
                    rows = [r for r in rows if not r.get("is_default")]
                if table == "tasks":
                    rows = self._parents_first(rows)
                for row in rows:
                    values = {}
                    for column in columns:
                        if column not in row:
                            continue
                        value = row[column]
                        if column in refs and value is not None:
                            value = keys[refs[column]].get(value)
                            if value is None and column != "fk_parent_task":
                                raise ValueError(f"{table} row {row.get(key)}: {column} "
                                                 "names a row that isn't in the import")
                        values[column] = self._import_value(column, value)
                    names = list(values)
                    new_key = self._one(
                        conn,
                        f"insert into {table} ({', '.join(names)}) "
                        f"values ({', '.join(['%s'] * len(names))}) returning {key}",
                        [values[n] for n in names])
                    keys[table][row.get(key)] = new_key
                loaded[table] = len(rows)
            self._seed_default_queries(conn)
        return loaded

    @staticmethod
    def _parents_first(tasks: list) -> list:
        """Tasks ordered so each parent is loaded before its subtasks (a
        parent that is missing, or a cycle, loads without its link)."""
        by_key = {t.get("key_task"): t for t in tasks}
        ordered, placed = [], set()

        def place(task, trail=()):
            k = task.get("key_task")
            if k in placed:
                return
            parent = task.get("fk_parent_task")
            if parent in by_key and parent not in trail:
                place(by_key[parent], trail + (k,))
            elif parent is not None and (parent not in by_key or parent in trail):
                task = {**task, "fk_parent_task": None}
            placed.add(k)
            ordered.append(task)

        for task in tasks:
            place(task)
        return ordered

    def import_totals(self) -> pd.DataFrame:
        """Per customer: entries, hours and cost — the "after" side of the
        import report (deleted entries excluded)."""
        return self.fetch_query(
            """
            select customer_name as customer, count(*) as entries,
                   coalesce(sum(duration_hours), 0) as hours, coalesce(sum(cost), 0) as cost
            from v_time_entries
            group by customer_name
            order by customer_name collate "C"
            """)
