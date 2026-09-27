"""Architecture guard (v6 phase 0.2): SQL against WorkTimer's own tables lives
only in the data layer, src/database.py. Pages, UI modules and services reach
the database through named ``Database`` methods — which is what lets the
Postgres port happen behind one API.

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
DATA_LAYER = {SRC / "database.py"}

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
    assert not offenders, "SQL outside src/database.py:\n" + "\n".join(offenders)


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
