# Tests

Regression suite for WorkTimer — codifies the checks that were run by hand while
fixing the AUDIT.md findings. Run these locally before pushing.

## Running

```bash
uv run pytest              # full suite
uv run pytest -v           # verbose (per-test names)
uv run pytest tests/test_database.py        # one file
uv run pytest -k bonus     # tests matching a keyword
```

If `uv run` ever stumbles on a OneDrive file lock during sync, run pytest
directly against the venv instead:

```bash
.venv/Scripts/python.exe -m pytest
```

## Layout

| File | Covers |
|------|--------|
| `test_database.py` | schema init & auto-migration, trigger drift/recreation, backdated-bonus rate, customer-scoped devops cache, partial customer/project updates, identifier/table validation, dates-horizon extension |
| `test_helpers.py` | date ranges, id/table parsing, widget-value + chip-group extraction, dynamic options |
| `test_markdown.py` | `.wt-md` scoping, checkbox id stamping, `data:` stripping, HTML→markdown |
| `test_ui_styles.py` | content-idempotent theme resolution, width fallback |
| `test_events.py` | `register_unique` (no SPA handler stacking), register/unregister |
| `test_notepad_logic.py` | checkbox toggle, title/filename derivation, save-note collision suffixing |
| `test_tasks_logic.py` | task-id extraction, NULL-last sorting, `Task.from_df_row`, card signature |
| `test_devops.py` | credential skipping, `get_description` 4-tuple, epic/feature/story hierarchy df |
| `test_forms.py` | conditional field visibility, widget-class coverage of every config field type |
| `test_globals.py` | shared DB connection, next-2 AM scheduler math |
| `test_smoke.py` | `import main` (page registration), all page modules import, helpers re-exports |

Tests import from `src.*` (configured via `pythonpath = ["."]` in
`pyproject.toml`) and never touch the real database — DB tests use a temp-file
SQLite via the `db` fixture in `conftest.py`.
