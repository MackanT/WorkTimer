"""Architecture guards for the v6 migration.

Phase 0.2 — SQL against WorkTimer's own tables lives only in the data layer,
src/database.py (plus the v6 migration runner, src/migrator.py). Pages, UI
modules and services reach the database through named ``Database`` methods —
which is what lets the Postgres port happen behind one API.

Phase 0.3 — the user's calendar time is read only through src/clock.py (see
the second half of this file).

Scans string literals (docstrings excluded; f-strings joined with their
placeholders) for SQL shapes that name a WorkTimer table, plus the
``ORDER BY CASE WHEN`` sort fragment. Tracker query languages (WIQL's
``FROM WorkItems``, JQL's ``ORDER BY updated DESC``) don't match, and neither
does SQL shown as sample text without a WorkTimer table.
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
# The data layer: the Database class, and the migration runner that owns the
# schema (it creates its own history table).
DATA_LAYER = {SRC / "database.py", SRC / "migrator.py"}

# Today's table names. Phase 2 renames them — add time_entries, customer_wages,
# bonuses, saved_queries, work_items and users here then, or the guard goes
# blind to the new schema.
_TABLES = r"(time|customers|projects|trackers|tasks|queries|devops|bonus|dates)"
SQL = re.compile(
    rf"""
      \bselect\b[\s\S]*?\bfrom\s+{_TABLES}\b
    | \binsert\s+into\s+{_TABLES}\b
    | \bupdate\s+{_TABLES}\s+set\b
    | \bdelete\s+from\s+{_TABLES}\b
    | \b(create|drop|alter)\s+table\b
    | \border\s+by\s+case\s+when\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _string_literals(tree):
    """(line, text) of every string literal that isn't a docstring."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield node.lineno, "".join(
                v.value if isinstance(v, ast.Constant) else "?" for v in node.values)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docstrings):
            yield node.lineno, node.value


def test_no_sql_outside_the_data_layer():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path in DATA_LAYER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, text in _string_literals(tree):
            if SQL.search(text):
                snippet = " ".join(text.split())[:70]
                offenders.append(f"{path.relative_to(SRC.parent)}:{lineno}: {snippet!r}")
    assert not offenders, "SQL outside the data layer:\n" + "\n".join(offenders)


def test_the_guard_recognises_the_sql_that_used_to_live_in_pages():
    """Keeps the pattern honest — a guard that matches nothing passes
    vacuously."""
    for sql in [
        "SELECT customer_name FROM customers WHERE is_current = 1",
        "select min(date(start_time)) as min_date from time",
        "select c.customer_name, p.project_name from time t join customers c",
        "update queries set query_sql = ? where query_name = ?",
        "insert into queries (query_name, query_sql) values (?, ?)",
        "delete from time where time_id = ?",
        "ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC",
    ]:
        assert SQL.search(sql), sql
    for text in [
        "Select a customer",
        "Select the project from the list",
        "Time Tracker",
        "Delete task",
        "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = 'x'",
        "project = ABC ORDER BY updated DESC",
        "select customer_name, sum(cost) as amount from time_entries order by amount desc",
    ]:
        assert not SQL.search(text), text


# ── one clock (v6 phase 0.3) ────────────────────────────────────────────────
#
# Anything on the user's calendar reads the time through src/clock.py. The
# exceptions are technical timing, where the *server's* clock is the right one
# (in v6 "local" becomes the user's timezone) — allowed per enclosing
# function, so unrelated edits don't break the list. Epoch timers
# (time.time(): retry cooldowns, unique filenames) aren't calendar reads and
# aren't scanned.

TECHNICAL_CLOCK_READS = {
    ("globals.py", "_seconds_until_next"): "the 2 AM full-sync scheduler",
    ("pages/log.py", "save_log_to_file"): "export filename",
    ("pages/settings.py", "_backup_now"): "backup filename",
    ("pages/settings.py", "_download"): "backup filename",
    ("ui/command_palette.py", "_backup"): "backup filename",
    ("services/update_checker.py", "check_for_update"): "update-check cache age",
}
_CLOCK_CALLS = {("datetime", "now"), ("datetime", "today"), ("datetime", "utcnow"),
                ("date", "today")}


class _ClockReads(ast.NodeVisitor):
    """(enclosing function, line) of every datetime.now() / date.today()-style
    call, including datetime.datetime.now()."""

    def __init__(self):
        self.stack, self.found = ["<module>"], []

    def _function(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute):
            base = f.value
            name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
            if (name, f.attr) in _CLOCK_CALLS:
                self.found.append((self.stack[-1], node.lineno))
        self.generic_visit(node)


def test_calendar_time_is_read_through_src_clock():
    offenders, seen = [], set()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "clock.py":
            continue
        visitor = _ClockReads()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        for function, lineno in visitor.found:
            if (rel, function) in TECHNICAL_CLOCK_READS:
                seen.add((rel, function))
            else:
                offenders.append(f"src/{rel}:{lineno} in {function}()")
    assert not offenders, (
        "Read the time through src/clock.py (or, for server-side timing, add the "
        "function to TECHNICAL_CLOCK_READS with a reason):\n" + "\n".join(offenders))
    stale = set(TECHNICAL_CLOCK_READS) - seen
    assert not stale, f"allowlist entries with no clock read left: {sorted(stale)}"
