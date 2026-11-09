"""A tracker project's work-item process: its levels root → leaf, each with
its board and types, and every type's states with their category.

Azure DevOps reads it per project (Basic, Agile, Scrum, CMMI or a custom
process) from the project's backlog configuration; `AGILE` is the fallback —
what the app assumed before it asked.
"""

from dataclasses import dataclass, field

PROPOSED, IN_PROGRESS, RESOLVED, COMPLETED, REMOVED = (
    "Proposed", "InProgress", "Resolved", "Completed", "Removed")

# A state's category where no process says (offline, or a tracker without
# categories): the state names of Azure's system processes and Jira's.
_GUESSED = {
    "new": PROPOSED, "to do": PROPOSED, "proposed": PROPOSED, "approved": PROPOSED,
    "design": PROPOSED, "active": IN_PROGRESS, "doing": IN_PROGRESS,
    "in progress": IN_PROGRESS, "committed": IN_PROGRESS, "resolved": RESOLVED,
    "closed": COMPLETED, "done": COMPLETED, "removed": REMOVED,
}


def guess_category(state) -> str | None:
    return _GUESSED.get(str(state or "").strip().lower())


def category_of(state, cached=None) -> str | None:
    """A cached item's state category: the one its process gave it, else
    guessed from the state's name."""
    return cached if isinstance(cached, str) else guess_category(state)


def categories(df) -> list:
    """category_of() for each row of a work-item frame."""
    cached = df["state_category"] if "state_category" in df.columns else [None] * len(df)
    return [category_of(s, c) for s, c in zip(df["state"], cached)]


def is_closed(category) -> bool:
    """Finished or removed — hidden where only live work shows."""
    return category in (COMPLETED, REMOVED)


def is_open(state, category) -> bool:
    """Still to work on: not started or in progress (a state of unknown
    category counts too) — except one named Resolved, done in all but name
    (Agile files it under In Progress)."""
    if str(state or "").strip().lower() == "resolved":
        return False
    return category in (None, PROPOSED, IN_PROGRESS)


@dataclass(frozen=True)
class Level:
    name: str            # the backlog's name, also its board's (e.g. Stories)
    types: tuple         # its work-item types, the default one first
    tasks: bool = False  # the task level: no board — the state is the column


@dataclass(frozen=True)
class Process:
    levels: tuple                               # root → leaf, the task level last
    states: dict = field(default_factory=dict)  # type → {state: category}, workflow order

    @property
    def types(self) -> tuple:
        """Every type above the task level, root → the working level."""
        return tuple(t for lv in self.levels if not lv.tasks for t in lv.types)

    @property
    def task_types(self) -> tuple:
        return tuple(t for lv in self.levels if lv.tasks for t in lv.types)

    @property
    def root_types(self) -> tuple:
        return self.levels[0].types

    @property
    def working_type(self) -> str:
        """The type boards open on: the requirement level's default (User
        Story, Issue, Product Backlog Item, Requirement)."""
        return next(lv for lv in reversed(self.levels) if not lv.tasks).types[0]

    def level_of(self, wtype) -> Level | None:
        return next((lv for lv in self.levels if wtype in lv.types), None)

    def board(self, wtype) -> str | None:
        """The board a type's cards live on — None on the task level."""
        level = self.level_of(wtype)
        return level.name if level and not level.tasks else None

    def state_options(self, wtype=None) -> list:
        """A type's states in workflow order — or every type's, merged."""
        if wtype is not None:
            return list(self.states.get(wtype, {}))
        return list(dict.fromkeys(
            s for t in self.types + self.task_types for s in self.states.get(t, {})))

    def category(self, wtype, state) -> str | None:
        return self.states.get(wtype, {}).get(state) or guess_category(state)


_AGILE_STATES = {"New": PROPOSED, "Active": IN_PROGRESS, "Resolved": IN_PROGRESS,
                 "Closed": COMPLETED, "Removed": REMOVED}

AGILE = Process(
    levels=(Level("Epics", ("Epic",)), Level("Features", ("Feature",)),
            Level("Stories", ("User Story",)), Level("Tasks", ("Task",), tasks=True)),
    states={"Epic": _AGILE_STATES, "Feature": _AGILE_STATES, "User Story": _AGILE_STATES,
            "Task": {"New": PROPOSED, "Active": IN_PROGRESS, "Closed": COMPLETED,
                     "Removed": REMOVED}},
)


def from_azure(config, work_item_types) -> Process:
    """A project's process from Azure DevOps: its backlog configuration
    (levels and their boards) and work-item types (states and category)."""

    def level(backlog, tasks=False) -> Level:
        names = [t.name for t in (backlog.work_item_types or [])]
        default = getattr(backlog.default_work_item_type, "name", None)
        if default in names:
            names.insert(0, names.pop(names.index(default)))
        return Level(backlog.name, tuple(names), tasks)

    portfolio = sorted(config.portfolio_backlogs or [], key=lambda b: -(b.rank or 0))
    levels = [level(b) for b in portfolio]
    if config.requirement_backlog:
        levels.append(level(config.requirement_backlog))
    if config.task_backlog:
        levels.append(level(config.task_backlog, tasks=True))
    levels = tuple(lv for lv in levels if lv.types)
    if not any(not lv.tasks for lv in levels):
        raise ValueError("no backlog levels")
    covered = {t for lv in levels for t in lv.types}
    states = {t.name: {s.name: s.category for s in (t.states or [])}
              for t in work_item_types if t.name in covered}
    return Process(levels, states)
