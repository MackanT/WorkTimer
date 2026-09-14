# WorkTimer — Claude Context

## Project Overview
WorkTimer V5 is a local NiceGUI web app (SPA) running on port 8080. It tracks time
against customer/project entries and integrates with issue trackers — Azure DevOps
and Jira Cloud — via a pluggable provider architecture.

## Stack
- **Python 3.11+** with `asyncio`
- **NiceGUI ≥2.24.1** (Quasar/Vue under the hood) — single-page app
- **SQLite** via custom `QueryEngine` in `src/globals.py`
- **Azure DevOps** SDK (`azure-devops`, `msrest`); **Jira Cloud** via plain REST v3
- **cryptography** (Fernet) — tracker credentials encrypted at rest (key: `data/.pat_key`)
- **Pandas** for query results
- Version: see `pyproject.toml` → `project.version`

## Architecture

```
main.py                    Entry point; calls ui.run() on port 8080
src/core/app.py            AppCore — per-client state (one instance per NiceGUI client ID)
src/core/events.py         EventBus — thread-safe cross-thread communication + ui.notify()
src/pages/root.py          SPA shell; injects layout CSS, renders nav bar, registers sub-pages
src/ui/elements.py         NavigationBar, toolbar() context manager, card helpers
src/pages/                 One file per page (time_tracking, settings, log, board, …)
src/pages/add_data.py      Entity-management DIALOGS (customers/trackers/projects/bonus)
                           — the old Data Input page is retired; open_entity_dialog()
src/trackers/              Pluggable tracker providers: base.py (TrackerProvider ABC,
                           TrackerCapabilities), azure.py, jira.py, registry.py.
                           Customers link to rows in the `trackers` table (credentials
                           live there, encrypted); `DevOpsManager` multiplexes per customer
src/services/              BaseService + typed services; background threads call these
src/services/update_checker.py  Daily GitHub update check (see Update Check section)
config/                    YAML configs for theme, UI layout, navigation, tracker contacts
                           (+ gitignored per-user overrides: time_settings.yml,
                           tracker_defaults.yml)
```

## Key Patterns

**Per-client isolation** — All runtime state lives in `AppCore`, retrieved via
`await AppCore.get_or_initialize()`. Never share mutable state between clients.

**Thread-safe UI updates** — Use `event_bus.emit(event_name, **kwargs)` and
`event_bus.notify(msg, type_="info"|"positive"|"negative"|"warning")`.
Background threads must go through the event bus.

**Background tasks** — `core._setup_page_timers("page_name", *async_fns)` cancels
old tasks for a page and starts new ones. Or use `asyncio.create_task()` for
one-off tasks.

**Storage**
- `app.storage.general` — app-wide, persistent across restarts (used for update check cache)
- `app.storage.client` — per-client session (browser tab lifetime)
- `app.storage.user` — per-user (keyed by storage secret)

**Navigation bar** — `core.nav_bar` is a `NavigationBar` instance on each `AppCore`.
Key methods: `set_active_timers(names)`, `set_update_available(version_str)`.

## Update Check
`src/services/update_checker.py` fetches `pyproject.toml` from the GitHub `main` branch
once per 24 h (guarded by `app.storage.general`). Result is cached process-wide via
`_process_cache`. When a newer version is found, `core.nav_bar.set_update_available(version)`
shows an amber badge on the right side of the nav bar. The check runs as a background task
in `_setup_spa_shell()` in `root.py`.

GitHub repo: `https://github.com/MackanT/worktimer`

## Config Files
- `config/config_theme.yml` — color palette (Tailwind tokens + hex)
- `config/config_ui.yml` — navigation structure + form schemas
- `config/config_ui_styles.yml` — widget sizing, layout classes
- `.env` — `DB_NAME`, `DEBUG_MODE`

## CSS Layout Notes
Layout CSS is injected per-client in `root.py` `_LAYOUT_CSS`. Key variables:
`--wt-nav-h: 68px`, `--wt-toolbar-h: 56px`. The `.nicegui-sub-pages` container
is `position: fixed` below the nav bar. Pages use `wt-page-content` class for
proper flex height chaining.
