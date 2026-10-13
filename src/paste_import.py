"""Time entries pasted from a spreadsheet (the Excel import): the pasted table
read, its columns guessed from their headers (Swedish or English) and
content, and its rows turned into entries — or into a list of what to fix.
No database and no UI: src/pages/settings.py shows it, the data layer
imports it.

Excel and Google Sheets copy a selection as tab-separated text, quoting a
cell that holds a tab, a line break or a quote; dates and numbers arrive as
the sheet displays them.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

FIELDS = ("date", "customer", "project", "hours", "start", "end", "comment")
IGNORE = "ignore"
REQUIRED = ("date", "customer")
DEFAULT_PROJECT = "General"
DAY_STARTS = time(8, 0)  # where rows with only hours are placed, one after another
MAX_ROWS = 20_000
MAX_HOURS = Decimal(24)

_HEADERS = {
    "date": {"date", "datum", "dag", "day"},
    "customer": {"customer", "kund", "client", "klient", "uppdragsgivare", "company", "företag",
                 "bolag"},
    "project": {"project", "projekt", "uppdrag", "assignment", "engagement"},
    "hours": {"hours", "hour", "hrs", "h", "timmar", "timme", "tim", "antal", "tid", "time",
              "duration", "arbetstid", "debiterbart"},
    "start": {"start", "starttid", "från", "from", "in", "börjar", "begin"},
    "end": {"end", "slut", "sluttid", "till", "to", "ut", "stop", "slutar"},
    "comment": {"comment", "comments", "kommentar", "kommentarer", "beskrivning", "description",
                "notering", "note", "notes", "anteckning", "anteckningar", "text", "aktivitet",
                "activity", "arbetsuppgift", "uppgift", "task", "vad"},
}


class Entry(NamedTuple):
    row: int  # the row in the pasted table, header included (1-based)
    day: date
    customer: str
    project: str
    hours: Decimal
    start: time | None  # both given, or neither: then placed from DAY_STARTS
    end: time | None
    comment: str


class Problem(NamedTuple):
    row: int
    message: str


# ── the table ───────────────────────────────────────────────────────────────


def read_table(text: str) -> list[list[str]]:
    """The pasted cells, trimmed, without empty rows or empty trailing
    columns. Raises ValueError for more than MAX_ROWS rows."""
    rows = [[cell.strip() for cell in row]
            for row in csv.reader(io.StringIO(text.strip("\r\n")), delimiter="\t")]
    rows = [row for row in rows if any(row)]
    if len(rows) > MAX_ROWS + 1:
        raise ValueError(f"More than {MAX_ROWS:,} rows — import them in parts".replace(",", " "))
    width = max((max((i + 1 for i, c in enumerate(row) if c), default=0) for row in rows),
                default=0)
    return [(row + [""] * width)[:width] for row in rows]


def _norm(header: str) -> str:
    return " ".join(re.sub(r"[^\wåäö ]", " ", header.lower()).split())


def _header_field(header: str) -> str | None:
    words = _norm(header)
    for field, names in _HEADERS.items():
        if words in names:
            return field
    first = words.split(" ")[0] if words else ""
    if len(first) >= 3:
        for field, names in _HEADERS.items():
            if first in names:
                return field
    return None


def guess_columns(rows: list[list[str]]) -> tuple[bool, list[str]]:
    """(has_header, a field or IGNORE per column): from the header names where
    they say it, else from what the column holds."""
    if not rows:
        return False, []
    width = len(rows[0])
    header_fields = [_header_field(cell) for cell in rows[0]]
    body_if_header = rows[1:] or rows
    has_header = any(header_fields) or (
        len(rows) > 1
        and not any(_kind(cell) in ("date", "number", "clock") for cell in rows[0] if cell)
        and any(_column_kind([r[i] for r in rows[1:]]) in ("date", "number", "clock")
                for i in range(width)))
    body = body_if_header if has_header else rows
    fields: list[str | None] = [None] * width
    if has_header:
        for i, field in enumerate(header_fields):
            if field and field not in fields:
                fields[i] = field
    columns = [[r[i] for r in body] for i in range(width)]
    kinds = [_column_kind(c) for c in columns]

    def free(kind):
        return [i for i in range(width) if fields[i] is None and kinds[i] == kind]

    if "date" not in fields and free("date"):
        fields[free("date")[0]] = "date"
    clocks = free("clock")
    if "start" not in fields and "end" not in fields and len(clocks) >= 2:
        fields[clocks[0]], fields[clocks[1]] = "start", "end"
    if "hours" not in fields and "start" not in fields:
        numbers = free("number") or free("clock")  # "7:30" alone is a duration
        if numbers:
            fields[numbers[0]] = "hours"
    texts = free("text")
    if texts:
        stats = {i: _text_stats(columns[i]) for i in texts}  # (distinct share, mean length)
        if "customer" not in fields:
            customer = min(texts, key=lambda i: stats[i])
            fields[customer] = "customer"
            texts.remove(customer)
        if "comment" not in fields and texts:
            # Comments vary (or run long); projects repeat.
            comment = max(texts, key=lambda i: stats[i])
            if stats[comment][0] > 0.3 or stats[comment][1] >= 20 or "project" in fields:
                fields[comment] = "comment"
                texts.remove(comment)
        if "project" not in fields and texts:
            project = min(texts, key=lambda i: stats[i])
            if stats[project][0] <= 0.5:
                fields[project] = "project"
    return has_header, [f or IGNORE for f in fields]


def _text_stats(column: list[str]) -> tuple[float, float]:
    values = [v for v in column if v]
    if not values:
        return 1.0, 0.0
    return len(set(values)) / len(values), sum(map(len, values)) / len(values)


# ── values ──────────────────────────────────────────────────────────────────

_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?$")
_LOCAL = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})(?: .*)?$")
_CLOCK = re.compile(r"(\d{1,2})[:.](\d{2})(?::(\d{2}))?$")
_EXCEL_EPOCH = date(1899, 12, 30)


def _kind(cell: str) -> str:
    if not cell:
        return "empty"
    if _ISO.match(cell) or _LOCAL.match(cell):
        return "date"
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", cell):
        return "clock"
    if parse_hours(cell) is not None:
        return "number"
    return "text"


def _column_kind(column: list[str]) -> str:
    kinds = [_kind(c) for c in column if c]
    if not kinds:
        return "empty"
    for kind in ("date", "clock", "number"):
        if kinds.count(kind) >= 0.8 * len(kinds):
            return kind
    return "text"


def date_order(cells: list[str]) -> str:
    """"dmy" or "mdy" for a column of d/m/y-style dates: month-first only
    when a value can't be day-first; else day-first, as in Sweden."""
    for cell in cells:
        m = _LOCAL.match(cell)
        if m and int(m.group(1)) <= 12 < int(m.group(2)):
            return "mdy"
    return "dmy"


def parse_date(cell: str, order: str = "dmy") -> date | None:
    m = _ISO.match(cell)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _LOCAL.match(cell)
        if m:
            a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            year += 2000 if year < 100 else 0
            day, month = (a, b) if order == "dmy" else (b, a)
            return date(year, month, day)
        if re.fullmatch(r"\d{5}(\.0+)?", cell):  # an Excel date serial, unformatted
            return _EXCEL_EPOCH + timedelta(days=int(float(cell)))
    except ValueError:
        return None
    return None


def parse_hours(cell: str) -> Decimal | None:
    """Hours as a number: "7,5", "7.5", "7:30", "7 h", "7,5h" — None if it
    isn't one."""
    text = cell.strip().lower().replace(" ", " ")
    text = re.sub(r"\s*(h|hrs|hours|tim|timmar)$", "", text)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m:
        return Decimal(int(m.group(1))) + Decimal(int(m.group(2))) / 60
    if re.fullmatch(r"\d+([.,]\d+)?", text):
        try:
            return Decimal(text.replace(",", "."))
        except InvalidOperation:
            return None
    return None


def parse_clock(cell: str) -> time | None:
    m = _CLOCK.fullmatch(cell.strip())
    if m:
        try:
            return time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
        except ValueError:
            return None
    try:  # an Excel time, unformatted: a fraction of a day
        fraction = float(cell.replace(",", "."))
    except ValueError:
        return None
    if 0 <= fraction < 1:
        seconds = round(fraction * 86400)
        return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)
    return None


def _name(cell: str) -> str:
    return " ".join(cell.split())


# ── rows → entries ──────────────────────────────────────────────────────────


def parse(rows: list[list[str]], has_header: bool,
          fields: list[str]) -> tuple[list[Entry], list[Problem], int]:
    """(entries, problems, rows skipped): each body row with a date, a
    customer and either hours or a start and end becomes an entry. Rows
    with no time (empty or 0 hours) are skipped, not problems. A customer
    (or a customer's project) written in several ways — case, spacing —
    takes its first spelling."""
    missing = [f for f in REQUIRED if f not in fields]
    if "hours" not in fields and not {"start", "end"} <= set(fields):
        missing.append("hours (or start and end)")
    if missing:
        return [], [Problem(0, f"No column chosen for: {', '.join(missing)}")], 0
    first = 2 if has_header else 1
    body = rows[1:] if has_header else rows
    at = {f: fields.index(f) for f in FIELDS if f in fields}
    order = date_order([r[at["date"]] for r in body])
    entries, problems, skipped = [], [], 0
    spelling: dict = {}  # a name's first spelling in the paste, by its case-insensitive form

    def spelled(name: str, within: str = "") -> str:
        return spelling.setdefault((within, name.casefold()), name)

    def cell(row, field):
        return row[at[field]] if field in at else ""

    for n, row in enumerate(body, start=first):
        raw_hours, raw_start, raw_end = cell(row, "hours"), cell(row, "start"), cell(row, "end")
        if not (raw_hours or raw_start or raw_end):
            skipped += 1
            continue
        day = parse_date(cell(row, "date"), order)
        if day is None:
            problems.append(Problem(n, f"“{cell(row, 'date') or '(empty)'}” is not a date"))
            continue
        customer = spelled(_name(cell(row, "customer")))
        if not customer:
            problems.append(Problem(n, "No customer"))
            continue
        start = end = None
        if raw_start or raw_end:
            start, end = parse_clock(raw_start), parse_clock(raw_end)
            if start is None or end is None:
                bad = raw_start if start is None else raw_end
                problems.append(Problem(n, f"“{bad or '(empty)'}” is not a time of day"))
                continue
            if end <= start:
                problems.append(Problem(n, f"Ends ({raw_end}) before it starts ({raw_start})"))
                continue
            hours = Decimal((datetime.combine(day, end) - datetime.combine(day, start))
                            .total_seconds()) / 3600
        else:
            hours = parse_hours(raw_hours)
            if hours is None:
                problems.append(Problem(n, f"“{raw_hours}” is not a number of hours"))
                continue
            if hours == 0:
                skipped += 1
                continue
            if hours > MAX_HOURS:
                problems.append(Problem(n, f"{raw_hours} hours is more than a day"))
                continue
        project = spelled(_name(cell(row, "project")) or DEFAULT_PROJECT, customer.casefold())
        entries.append(Entry(n, day, customer, project, hours, start, end, cell(row, "comment")))
    return entries, problems, skipped


def placed(entries: list[Entry]) -> list[tuple[datetime, datetime]]:
    """(start, end) per entry, in order: its own times, or — with only hours —
    from DAY_STARTS on its day, after the day's earlier hours-only entries."""
    next_start: dict[date, datetime] = defaultdict(lambda: None)
    spans = []
    for e in entries:
        if e.start is not None:
            spans.append((datetime.combine(e.day, e.start), datetime.combine(e.day, e.end)))
            continue
        start = next_start[e.day] or datetime.combine(e.day, DAY_STARTS)
        end = start + timedelta(seconds=round(e.hours * 3600))
        next_start[e.day] = end
        spans.append((start, end))
    return spans


def by_customer(entries: list[Entry]) -> list[dict]:
    """Per customer, in first-seen order: entries, hours, first and last day,
    and its projects (first-seen order)."""
    groups: dict[str, dict] = {}
    for e in entries:
        g = groups.setdefault(e.customer, {"customer": e.customer, "entries": 0,
                                           "hours": Decimal(0), "first": e.day, "last": e.day,
                                           "projects": []})
        g["entries"] += 1
        g["hours"] += e.hours
        g["first"], g["last"] = min(g["first"], e.day), max(g["last"], e.day)
        if e.project not in g["projects"]:
            g["projects"].append(e.project)
    return list(groups.values())
