# WorkTimer V5 — Code Audit

**Date:** 2026-08-03 · **Version audited:** 5.0.2 (pyproject) · **Scope:** all source under `src/`, `main.py`, `scripts/`, `config/` (~15,500 lines of Python; `.venv`, `.git`, `_Old/` excluded)

> **Remediation status (2026-08-03, for 5.0.3): all substantive findings fixed** — see `docs/CHANGELOG.md` 5.0.3.
> §1–§6 in full; §7.1–7.8 (incl. schema single-sourcing with startup auto-migration and the backdated-bonus trigger); §8.1–8.10 (**§7.4/§8.1 done**: the legacy `make_input_row` form factory and its binding machinery were deleted outright — every remaining caller was a dead fallback — with a new `datetime` widget covering the last config type, and conditional field visibility restored in the DynamicWidget path where it had silently stopped working; helpers.py split into `ui_styles.py` + `markdown_utils.py` with back-compat re-exports; task card moved into tasks.py taking the `Task` dataclass); and §9 (incl. `update_customer`/`update_project` None-wipe hardening and checkbox-stamp robustness).
> Deliberately left as-is: mixed SQL keyword casing (§7.9 — pure churn) and the `extract_table_name` first-`from` regex (§9 — guarded by the editable-table whitelist).

> **5.0.5 addendum (2026-09-14):** re-verified before the user-base grows — all of the above holds. Note the internal naming this audit uses was renamed in 5.0.5: `src/devops.py` → `tracker_manager.py` (`DevOpsManager` → `TrackerManager`, `DevOpsClient` → `AzureDevOpsClient`), `src/ui/devops_forms.py` → `work_item_forms.py`, `devops_handlers.py` → `work_item_handlers.py`, `DevOpsEngine` → `TrackerEngine`, `core.devops_engine` → `core.tracker_engine`, and `customers.devops_project` → `tracker_project` (auto-migrated). The §5 security items are in place (localhost bind + `HOST` override, per-install storage secret, protocol-restricted bleach) and credentials are now Fernet-encrypted at rest in the `trackers` table.

---

## Summary

The codebase is in decent shape for a personal tool: config-driven UI, per-client state isolation, a working event bus, and a pragmatic write-through cache for DevOps data. The main problem areas are:

1. **Blocking Azure DevOps API calls running directly on the asyncio event loop** — freezes the whole UI for all tabs during syncs and form loads.
2. **A handful of genuine correctness bugs** (task-creation failures reported as success, Settings page crash when DevOps is offline, event-handler leaks on SPA navigation).
3. **A large amount of dead scaffolding code** — an entire broken service layer, unused engines, unused events, unused DevOps methods.
4. **Three parallel "generations" of the same subsystems** (two form-widget factories, three schema-migration mechanisms, two markdown-preview wiring approaches) causing drift and inconsistent behavior.

Findings are ordered by severity. `file:line` references point at the anchor line.

---

## 1. Critical / High — Correctness Bugs

### 1.1 `insert_task` failures are reported as success
[tasks.py:869](src/pages/tasks.py#L869) does `success = await core.query_engine.function_db("insert_task", **values)` then `if success:`. But `Database.insert_task` ([database.py:943](src/database.py#L943)) returns a **3-tuple** `(bool, msg, task_dict)` — a non-empty tuple is always truthy, so `(False, "Failed to create task...", None)` still shows "Task created" and refreshes. Compare [tasks.py:1010](src/pages/tasks.py#L1010) where `update_task`'s 2-tuple *is* correctly unpacked.
**Fix:** `success, msg, _ = await ...` and use `msg` in the notify.

### 1.2 Settings page crashes when DevOps is not initialized
[settings.py:743](src/pages/settings.py#L743) takes `_eng = core.devops_engine` and immediately reads `_eng.last_incremental_sync` at line 754. `core.devops_engine` is `None` whenever DevOps init was skipped (no customers with PAT, no internet, cooldown — all normal paths in [app.py:202-273](src/core/app.py#L202-L273)) → `AttributeError` and the Settings page fails to render. `DevOpsService.refresh_incremental_async` has the same problem (`self.core.devops_engine.update_devops` on `None`), though it at least fails inside a thread.
**Fix:** guard with `if core.devops_engine:` and render "DevOps not configured" state; disable the sync buttons.

### 1.3 Event-handler leak on every SPA navigation (tasks, log, notepad)
`ui.sub_pages` navigation does **not** fire `on_disconnect`, and page functions re-run on every visit:

- [tasks.py:652-658](src/pages/tasks.py#L652-L658): the cleanup guard `if page_state.get("_refresh_handler")` checks a dict created **6 lines earlier** — it can never be true, so it's dead code. Every visit to Tasks registers another `tasks_refresh_requested` handler on the per-client event bus. After N visits, one checkbox click triggers N full task fetches against N-1 dead containers.
- [log.py:163](src/pages/log.py#L163): `on_new_log` is only unregistered in `on_disconnect` ([log.py:253](src/pages/log.py#L253)) — SPA-navigating away and back stacks handlers for the client's lifetime; every log line then does N pushes (N-1 into dead widgets, swallowed by `try/except`).
- [notepad.py:317](src/pages/notepad.py#L317): `ui.on('notepad_cb_toggle', ...)` is registered per visit. Old handlers keep a stale `state` alive; a checkbox click after re-navigation can fire multiple toggles (toggling twice = visually reverts) and schedule saves against stale note objects.
- [tasks.py:988-994](src/pages/tasks.py#L988-L994): `task_selected` has the same pattern (works within one visit, leaks across visits).

**Fix:** store the handler on the *event bus/client* level and unregister before re-registering, or register once per client keyed in `app.storage.client` (the pattern already used for `timer_indicator_registered` in [root.py:124](src/pages/root.py#L124)).

### 1.4 Note rename can collide and destroy another note
[notepad.py:158-161](src/pages/notepad.py#L158-L161): `save_note` renames the file to a slug derived from the first `# heading`. If two notes resolve to the same slug (e.g. both titled "Ideas"), `old_path.rename(new_path)` **silently overwrites the other note on POSIX and raises `FileExistsError` on Windows** — either data loss or a crash mid-save (the debounced save then never writes the content).
**Fix:** on collision, suffix the filename (`ideas-1.md`) the same way `create_note` already does.

### 1.5 Task update form breaks on titles containing a quote
The `dynamic_query` mechanism substitutes raw values into SQL: [helpers.py:1515](src/helpers.py#L1515) `query.replace("{parent_value}", str(parent_val))`, used by every field in the task-update config ([config_ui.yml:841](config/config_ui.yml#L841) e.g. `... = '{parent_value}'`). A task titled `Don't forget` produces invalid SQL; the exception is swallowed (`except Exception: return None`) so fields silently stay empty. It's also injection-shaped, even if the app is local.
**Fix:** pass the value as a bound parameter — e.g. replace `{parent_value}` with `?` and forward `params=(parent_val,)` through `query_db`.

### 1.6 Daily full DevOps refresh waits ~25h if started between 00:00–02:00
[globals.py:91-95](src/globals.py#L91-L95): `tomorrow = now + 1 day; target = tomorrow.replace(hour=2)` — if the app starts at 00:30, the *upcoming* 02:00 is skipped and the first full refresh happens the following night.
**Fix:** `target = now.replace(hour=2, ...); if target <= now: target += timedelta(days=1)`.

### 1.7 “Due Date (Earliest First)” sorts NULL due-dates first
[tasks.py:187](src/pages/tasks.py#L187): `CASE WHEN due_date IS NULL THEN 1 ELSE 0 END DESC` — `DESC` puts the `1` (NULL) rows **first**. The "Latest First" variant on line 188 puts NULLs last. Almost certainly both should push NULLs to the bottom; the Earliest-First case wants `ASC` (or swap the 1/0).

### 1.8 Write-through DevOps cache updates by `id` only
[database.py:1201-1204](src/database.py#L1201-L1204): `UPDATE devops SET ... WHERE id = ?`. Work-item IDs are only unique **per organization** — with two DevOps customers, a board move or field edit for one customer's item #1234 also rewrites the other customer's #1234 row. The merge path gets this right ([database.py:1168-1170](src/database.py#L1168-L1170) deletes by `customer_name AND id`).
**Fix:** thread `customer_name` through `update_devops_item_fields` (callers in [board.py:217](src/pages/board.py#L217) and [devops_handlers.py:73](src/ui/devops_handlers.py#L73) have it available).

---

## 2. High — Event-Loop Blocking (UI freezes)

The codebase is inconsistent about keeping network I/O off the asyncio loop. Only one call site does it right — [board.py:225](src/pages/board.py#L225) wraps `set_board_column` in `asyncio.to_thread`. Everywhere else, synchronous `azure-devops`/`requests` calls run **directly on the event loop**, freezing every connected tab for the duration:

| Call site | Blocking call |
|---|---|
| [globals.py:200](src/globals.py#L200) `update_devops` | `manager.get_epics_feature_df()` — WIQL query + batched `get_work_items` for **all** customers. Runs on the loop at startup and **every hourly scheduled incremental** ([globals.py:75-84](src/globals.py#L75-L84)). This is the single biggest freeze. |
| [globals.py:165](src/globals.py#L165) `setup_manager` | `DevOpsManager(df, log)` constructor `connect()`s to each org — network per customer, on the loop. The `asyncio.wait_for(..., 30)` in [app.py:283](src/core/app.py#L283) cannot actually interrupt sync code. |
| [devops_handlers.py:120](src/ui/devops_handlers.py#L120) `add_work_item` | fully sync create + `set_board_column` — Add dialog freezes the app while ADO responds. |
| [devops_handlers.py:235](src/ui/devops_handlers.py#L235), [245](src/ui/devops_handlers.py#L245) `update_work_item` | `update_work_item_fields` / `set_board_column` sync inside an async fn. |
| [devops_handlers.py:307](src/ui/devops_handlers.py#L307) `load_work_item_details` | `get_description` sync — clicking a board card freezes until the API answers. |
| [devops_handlers.py:368](src/ui/devops_handlers.py#L368), [423](src/ui/devops_handlers.py#L423) | `load_board_columns` sync on cache miss (correctly wrapped in an executor only in `preload_cached_board_columns`). |
| [time_tracking.py:526](src/pages/time_tracking.py#L526) | `manager.save_comment(...)` sync when stopping a timer with "Store to DevOps". |

**Fix:** one pattern, applied everywhere: `await asyncio.to_thread(self.DO.manager.xxx, ...)`. Given `DevOpsManager` methods are all sync, a thin async facade on the manager would make it impossible to get wrong.

The settings sync buttons dodge this via `BaseService.run_in_thread` ([services.py:27](src/services/services.py#L27)) — but that spins up a *second event loop in a thread* running `update_devops`, meaning a settings-triggered sync and the hourly scheduled sync can run **concurrently from two loops** against the same SQLite connection and `DevOpsEngine.df`. The merge path (delete-loop + `to_sql`) is not atomic, so concurrent merges can duplicate rows. A simple `asyncio.Lock` around `update_devops` would remove the race.

---

## 3. Medium — Threading, State & Lifecycle

### 3.1 `Database` locking is inconsistent
`execute_query` / `fetch_query` / `smart_query` take `self._conn_lock` ([database.py:1816-1852](src/database.py#L1816-L1852)), but several write paths use raw cursors and bypass it entirely:
- [database.py:566-578](src/database.py#L566-L578) `insert_manual_time_row`
- [database.py:905-929](src/database.py#L905-L929) `insert_task`
- [database.py:1160-1175](src/database.py#L1160-L1175) `update_devops_data` (`to_sql` + delete loop)
- [database.py:1201](src/database.py#L1201) `update_devops_item_fields`
- [database.py:246-266](src/database.py#L246-L266) inline devops migration

All DB work goes through `asyncio.to_thread` → these *do* run on different threads concurrently. SQLite serializes at the C level, but interleaved statements between two half-finished multi-statement operations are possible.

Bigger issue: **each browser tab creates its own `Database` connection** (per-client `QueryEngine` in [app.py:182](src/core/app.py#L182)), each running `initialize_db()` DDL. Two connections writing concurrently → `sqlite3.OperationalError: database is locked`, and **no `busy_timeout` is set** so it fails immediately instead of waiting.
**Fix (small):** `self.conn.execute("PRAGMA busy_timeout=5000")` in `Database.__init__`. **Fix (better):** make the `Database`/`QueryEngine` a process-wide singleton like the DevOps engine already is — per-client instances of a same-file SQLite connection buy nothing.

### 3.2 Process-wide loggers vs per-client event buses
`_setup_logger("AppCore"/"Database"/"DevOps")` ([app.py:112-131](src/core/app.py#L112-L131)) uses fixed names on Python's process-wide logger registry. The second client's call early-returns because *client 1's* `EventBusLogHandler` is already attached — so client 2's logs are delivered to **client 1's** event bus and log buffer, and client 2's Log page shows only what came via the global buffer. When a client disconnects, its handler stays attached to the shared logger forever (handler leak; emits into a dead UI context each log line, error-logged and swallowed).
**Fix:** either make loggers per-client (`logging.getLogger(f"AppCore.{client_id}")`) with handler removal in the disconnect cleanup, or accept process-wide logging and attach exactly one process-wide handler that fans out to *all* live clients' buffers.

### 3.3 `EventBus.notify()` / `run_in_ui()` still have the bug `emit()` was fixed for
[events.py:169-176](src/core/events.py#L169-L176) documents that entering `self._ui_context` from a background thread corrupts the NiceGUI slot stack, and `emit()` correctly branches on `asyncio.get_running_loop()`. But `notify()` ([events.py:260-261](src/core/events.py#L260-L261)) and `run_in_ui()` ([events.py:214](src/core/events.py#L214)) enter the context manager unconditionally — and `notify()` is exactly what background threads call (`BaseService.run_in_thread` error paths, [services.py:55](src/services/services.py#L55)).
**Fix:** route `notify()` through `emit()`/`run_coroutine_threadsafe` the same way.

### 3.4 Shared config dicts are mutated per-render
`get_config_loader()`'s docstring says "Configs are immutable so sharing across clients is safe" ([app.py:476](src/core/app.py#L476)) — but:
- [query_editor.py:336-337](src/pages/query_editor.py#L336-L337) and [424](src/pages/query_editor.py#L424) write `field["default"] = table_row.get(...)` into `core.query_config`, which is the **singleton loader's dict** — one client's last-edited row becomes another client's (and the next dialog's) form default.
- [helpers.py:1834-1875](src/helpers.py#L1834-L1875) `assign_dynamic_options` writes `field["options"]` into the same shared field dicts (add_data, devops forms).
- [app.py:404-411](src/core/app.py#L404-L411) mutates `navigation_config["board"]["enabled"]` on the shared UI config.

Mostly harmless today because the values converge, but it's a footgun (and the reason stale defaults occasionally appear).
**Fix:** `copy.deepcopy` the fields list at form-render time, or resolve defaults into a separate dict instead of the config.

### 3.5 `DevOpsWorkItemHandlers.__init__` fires an unguarded background preload
[devops_handlers.py:33-35](src/ui/devops_handlers.py#L33-L35): first instantiation runs `preload_cached_board_columns()` via `ensure_future`, which dereferences `self.DO.manager.clients` — if a DevOps form is opened before init completes (manager `None`), the task raises `AttributeError` as an unhandled task exception. The `_preload_started` handshake with [app.py:307](src/core/app.py#L307) (which reaches into the other class's private flag) works but is fragile.
**Fix:** guard `if self.DO and self.DO.manager:` inside `_background_work`, and let the preload live in one place only (app.py already does it at the right time).

### 3.6 Triple-redundant singleton guards for scheduled DevOps tasks
Module flag `_devops_scheduled_started` ([globals.py:12](src/globals.py#L12)) + instance flag `self._scheduled_started` ([globals.py:60](src/globals.py#L60)) + `_global_devops_initialized`/`_global_devops_engine` in [app.py:24-26](src/core/app.py#L24-L26). Since the engine itself is a process singleton now, the module-level flag and instance flag are redundant with each other. Pick one.

---

## 4. Medium — Performance

### 4.1 N+1 query on time-tracking render
[time_tracking.py:772-776](src/pages/time_tracking.py#L772-L776): every project row runs its own `select 1 from time ... end_time is null` query, awaited sequentially. With 20 projects that's 20 round-trips through `asyncio.to_thread` per full render — and edit-mode arrow clicks trigger a **full re-render per click** ([time_tracking.py:799](src/pages/time_tracking.py#L799)).
**Fix:** fetch all active timers once (`select customer_id, project_id from time where end_time is null`) and pass the set down. The query already exists in `update_tab_indicator_now`.

### 4.2 Legacy parent-binding: quadruple event firing + permanent 4 Hz polls
[helpers.py:1722-1728](src/helpers.py#L1722-L1728) attaches the *same* update handler to `update:model-value`, `update`, `change`, **and** `input` ("Don't break - try to attach multiple events") — NiceGUI's `.on()` doesn't raise, so all four attach and one user change can fire the handler (and its DB `dynamic_query`) several times. On top of that, html/markdown children spawn a `ui.timer(0.25)` **forever-poll** per widget ([helpers.py:1757](src/helpers.py#L1757)). The comment at line 1732 says polling defaults to on ("default True") while the code defaults it off (`field_config.get("parent_update", False)`) — comment and code disagree.
**Fix:** attach only `update:model-value`; delete the poll (the DynamicWidget path already does this properly via `on_value_change`).

### 4.3 Dialog accumulation in time tracking
[time_tracking.py:414](src/pages/time_tracking.py#L414): `show_time_entry_dialog` builds a brand-new `ui.dialog` on every timer stop and never disposes it — DOM nodes pile up over a long-running day. The file already solves this for the manual dialogs (pre-created shells, [time_tracking.py:1064-1070](src/pages/time_tracking.py#L1064-L1070)); use the same pattern.

### 4.4 `data_fetcher` re-queries everything per widget refresh
[add_data.py:210-211](src/pages/add_data.py#L210-L211): every child-widget refresh calls `prepare_data_sources()` again — up to ~4 queries per widget, × widgets per form, on each parent change / tab switch. Cache the result per refresh cycle.

### 4.5 Repeated head-HTML injection on SPA revisits
[board.py:34](src/pages/board.py#L34) `ui.add_head_html(_BOARD_CSS)` and the two `ui.run_javascript` document-level listeners in [query_editor.py:547-584](src/pages/query_editor.py#L547-L584) run on **every** visit to those pages, stacking duplicate `<style>` blocks and keydown listeners for the client's lifetime (each Ctrl+C press then writes the clipboard N times).

### 4.6 `update_devops_data` merge does row-by-row deletes
[database.py:1166-1171](src/database.py#L1166-L1171): a Python loop of single-row `DELETE`s before the append. `executemany` (or a single `DELETE ... WHERE (customer_name, id) IN (...)`) would do.

---

## 5. Medium — Security / Robustness

*(Local single-user tool — judged in that context, but the bind address raises the stakes.)*

- **App binds to `0.0.0.0` with no auth** ([main.py:113](main.py#L113)): anyone on the LAN can read your notes (also served raw at `/notes_assets` — [notepad.py:232](src/pages/notepad.py#L232) statically serves the entire notes dir including `notes_meta.json`), run arbitrary SQL via the Query Editor (`smart_query` executes anything), and **read DevOps PAT tokens** (`select pat_token from customers` — they're also in the seeded default "customers" query, [database.py:373](src/database.py#L373)). Suggest defaulting `host="127.0.0.1"` with an env override.
- **Hardcoded storage secret** ([main.py:120](main.py#L120)): `"worktimer-v5-secret-change-in-production"` — fine for localhost, weak on a LAN. Generate/persist a random one on first run.
- **`bleach` allows the `data:` protocol** ([helpers.py:334](src/helpers.py#L334)) — permits `data:text/html` links in rendered notes. Drop `data:` or restrict to `data:image/*` if pasted-image previews need it.
- **Global CSS leakage from markdown previews:** `MARKDOWN_DARK_MODE_CSS` ([helpers.py:206-238](src/helpers.py#L206-L238)) uses bare element selectors (`h1`, `p`, `code`, `table`…) inside a `<style>` tag that is injected with the preview HTML — CSS is document-global, so whenever a notepad/DevOps preview is on screen it restyles headings/paragraphs of the *whole app*. Scope every rule under a wrapper class (`.wt-md h1 { ... }`).
- **WIQL built by string interpolation** ([devops.py:356-372](src/devops.py#L356-L372)) — inputs are own-system values today, but `min_changed_date` comes from DB text. Low risk, worth normalizing.
- **`update_customer` / `update_project` overwrite with `None`**: [database.py:706-716](src/database.py#L706-L716) sets `org_url = ?, pat_token = ?` unconditionally — any caller that omits them wipes the credentials. Current forms always send values, but the API is one refactor away from destroying tokens. Build the SET clause from provided-only fields (as `update_task` already does).

---

## 6. Dead / Broken Code Inventory

Verified by grep — no references outside their own definitions:

| Item | Location | Notes |
|---|---|---|
| `DatabaseService` | [services.py:62](src/services/services.py#L62) | **Broken too**: calls nonexistent `query_engine.get_customers()`; `ORDER BY name` — no such column. |
| `TimerService` | [services.py:240](src/services/services.py#L240) | Queries nonexistent `time_entries` table / `c.name`; `start_timer` is an empty placeholder. |
| `DevOpsService.create_work_item_async` | [services.py:196](src/services/services.py#L196) | Calls `devops_engine.create_epic` etc. — methods don't exist on the engine. Only `refresh_incremental_async`/`refresh_full_async` are used. |
| `AddData` engine | [globals.py:43](src/globals.py#L43), [app.py:188-191](src/core/app.py#L188-L191) | Initialized + refreshed on every client start (a wasted DB query), then never read by any page. |
| `Database.db` class attribute | [database.py:11](src/database.py#L11), [18](src/database.py#L18) | Global singleton handle, never read. |
| Events with no listeners | `ui_refresh_requested` (3 emit sites), `devops_refreshed` (2), `time_entry_started`, `time_entry_stopped` | Emitted into the void. Either implement the refresh listeners (the time-tracking page would genuinely benefit — currently other pages don't refresh after query-editor edits) or delete the emits. |
| `DevOpsManager.get_work_item_details`, `.get_board_columns`, `.get_team_for_customer` (+ client impls) | [devops.py:93-98](src/devops.py#L93-L98), [249-265](src/devops.py#L249-L265), [devops.py:657-766](src/devops.py#L657-L766) | ~150 lines of unused API surface; `get_team_for_customer`'s auto-detect duplicates `get_board_columns_via_team_autodetect`. |
| `devops_helper` branches `save_comment` / `get_workitem_level` | [globals.py:256-267](src/globals.py#L256-L267) | Only the `create_*` branches are reached ([devops_handlers.py:120](src/ui/devops_handlers.py#L120)); time-tracking calls `manager.save_comment` directly. |
| `get_unique_list` | [helpers.py:1815](src/helpers.py#L1815) | Marked deprecated; zero callers. |
| `ConfigData` model | [config.py:42](src/config.py#L42) | Never instantiated. |
| `EXTERNAL_NOTES` global | [notepad.py:32](src/pages/notepad.py#L32) | Superseded by `config_notepad.yml`; unused. |
| `PAGE_HEIGHT` import | [notepad.py:24](src/pages/notepad.py#L24) | Imported, unused (legacy constant per [elements.py:194](src/ui/elements.py#L194)). |
| Duplicated members in `DynamicEditorWithPreview` | [dynamic_widgets.py:706-734](src/ui/dynamic_widgets.py#L706-L734) | `on_value_change`, `widget` property and setter are each defined **twice**, verbatim. Delete the second copies. |
| `main.py` leftovers | [main.py:66-75](main.py#L66-L75) debug `'j'` key handler registered outside any page (never fires — all pages are under `@ui.page`), [main.py:78-95](main.py#L78-L95) commented-out example routes. |
| `update_available` storage key | [update_checker.py:86](src/services/update_checker.py#L86) | Written, never read. |
| Commented-out filter options | [log.py:49-56](src/pages/log.py#L49-L56) | Noise. |
| `src/worktimer.egg-info/` | committed build artifact — add to `.gitignore`. |
| `_Old/` | archived V4 code — fine to keep, but consider moving out of the repo root. |

Deleting the broken services alone removes ~150 lines that would crash if ever called.

---

## 7. Inconsistencies

### 7.1 `"text"` field type means two different widgets
- Legacy factory: `make_input_row` renders `type: text` as **`ui.textarea`** ([helpers.py:887-890](src/helpers.py#L887-L890)).
- Widget registry: `WIDGET_CLASSES["text"] = DynamicInput` — a **single-line input** ([dynamic_widgets.py:758](src/ui/dynamic_widgets.py#L758)); `DynamicTextArea` exists but is only mapped to `"textarea"`.

Consequence: the Task **description** fields ([config_ui.yml:740](config/config_ui.yml#L740), [845](config/config_ui.yml#L845)) render as single-line inputs in the task forms. Map `"text"` → `DynamicTextArea` (or change the config to `textarea`).

### 7.2 Three different defaults for `optional`
- `FieldConfig.optional` defaults **False** ([config.py:55](src/config.py#L55))
- `make_input_row` labels default **True** (`field.get("optional", True)`, [helpers.py:856](src/helpers.py#L856)) — so a field without `optional:` shows "(optional)" in its label…
- …while validation treats it as **required** (`not f.get("optional", False)`, [add_data.py:152](src/pages/add_data.py#L152), [devops_forms.py:36-40](src/ui/devops_forms.py#L36-L40), [query_editor.py:346-348](src/pages/query_editor.py#L346-L348)).

Pick one default (required-by-default is the safer read) and align label logic with validation.

### 7.3 F5 is blocked globally, while Settings tells you to press F5
- [root.py:110-112](src/pages/root.py#L110-L112) blocks F5 app-wide (so the query editor can bind it to Execute).
- [settings.py:564](src/pages/settings.py#L564), [683](src/pages/settings.py#L683): "Theme saved — refresh page to apply **(F5)**" — the shortcut the app just disabled. Visiting the query editor also perma-blocks **Ctrl+R** for the rest of the session ([query_editor.py:547-553](src/pages/query_editor.py#L547-L553) — a document-level listener that survives SPA navigation).
- Cleaner: scope the F5/Ctrl+R suppression to the query-editor page (add/remove the listener on enter/leave), and have "Save Theme" re-apply `ui.colors()` live instead of asking for a refresh.

### 7.4 Two form systems, two markdown-preview mechanisms
`make_input_row` + `bind_parent_relations` (helpers, event-name shotgun + polling) vs `DynamicWidget` classes (clean `on_value_change`). Both are in active use — query editor uses Dynamic widgets *with a fallback to* `make_input_row` ([query_editor.py:427-431](src/pages/query_editor.py#L427-L431)). Long-term, everything should converge on the DynamicWidget path; the helpers factory + its binding machinery (~450 lines) can then go.

### 7.5 Three schema-evolution mechanisms
1. `initialize_db` DDL ([database.py:40](src/database.py#L40))
2. Inline devops column migration marked `## TEMP Solution for now` ([database.py:245-266](src/database.py#L245-L266))
3. `get_expected_schema` + `validate_and_migrate_schema` ([database.py:1316-1639](src/database.py#L1316-L1639)) — a **second full copy of the schema** including trigger SQL, drifting independently of #1.

The devops columns in #2 are already covered by #3. Suggest: `initialize_db` creates tables; `validate_and_migrate_schema(auto_migrate=True)` runs at startup (it currently only runs via the manual script); delete #2. Better still, generate `get_expected_schema` data and the CREATE statements from one definition.

### 7.6 Backdated manual entries get *today's* bonus
`trigger_time_insert_row` ([database.py:103-106](src/database.py#L103-L106)) resolves `bonus_percent` with `current_date`, not the entry's `date_key`. A manual entry for last month ([database.py:545](src/database.py#L545)) is priced with today's bonus (wage similarly comes from the *current* customer row — consistent with using the current `customer_id`, but the bonus one looks unintended given bonus rows carry validity ranges).

### 7.7 `tasks` table declares unenforceable foreign keys
[database.py:302-304](src/database.py#L302-L304): FKs reference `customers(customer_name)` / `projects(project_name)` — neither is UNIQUE, so SQLite would reject these with "foreign key mismatch" the moment `PRAGMA foreign_keys=ON` is set. Today FKs are off, so they're decorative. Either drop them or reference the id columns.

### 7.8 Scripts read config that doesn't exist
[generate_task_visuals.py:177-184](scripts/generate_task_visuals.py#L177-L184) reads `config/config_settings.yml` (**file doesn't exist** — settings moved to `.env`) and falls back to `worktimer.db` **in the repo root**, while the real DB is `data/worktimer.db`. The script silently scans a nonexistent DB and generates an empty config. `validate_schema.py` hardcodes `data/worktimer.db` and ignores `DB_NAME` from `.env`. Both should load `.env` like the app does.

### 7.9 Misc consistency nits
- SQL keyword casing flips between files (lowercase in database.py, UPPER in tasks.py/add_data.py).
- `print()` in config.py/main.py vs `logger` everywhere else.
- Inline imports scattered mid-function (`import time`, `socket`, `shutil` ×3 in settings.py, `asyncio` in [dynamic_widgets.py:95](src/ui/dynamic_widgets.py#L95), `from datetime import date` again at [helpers.py:677](src/helpers.py#L677)).
- Hardcoded `slate-700`/`gray-100` classes in settings.py/notepad.py while everything else pulls colors from the theme config.
- `QueryConfig` docstring says "from config_query.yml" ([config.py:189](src/config.py#L189)) — it's carved out of `config_ui.yml`.
- `pyproject.toml` runtime deps include `setuptools` (build tool) but **omit `python-dotenv` and `pyyaml`**, both imported at startup ([main.py:13](main.py#L13), [helpers.py:4](src/helpers.py#L4)) — a fresh `pip install .` fails at import time.
- [pyproject.toml:38](pyproject.toml#L38) console script `worktimer = "src.main:main"` points at a module that doesn't exist (`main.py` lives at the repo root and isn't packaged) — the entry point, and the nav-badge advice "Run: pip install --upgrade worktimer" ([elements.py:162](src/ui/elements.py#L162)), can't work as packaged.

---

## 8. Spaghetti / Refactor Targets

### 8.1 `helpers.py` is a junk drawer (1,942 lines)
Styling singleton, markdown pipeline, date utils, widget factory, parent-binding engine, DataFrame utils, task-card component. At minimum split into `ui_styles.py`, `markdown.py`, `forms/legacy.py`, `dates.py`. The task card (`create_task_card`, 180 lines) belongs next to tasks.py, and its stringly-typed `columns=[{"label": "Title", ...}]` contract ([helpers.py:1121-1131](src/helpers.py#L1121-L1131) re-parses by display-label) should take the `Task` dataclass directly — `Task.to_columns_format` → card → `column_map.get("Title")` is a round-trip through display strings for data you already had typed.

### 8.2 `devops_helper` dispatch-by-string
[globals.py:248-305](src/globals.py#L248-L305): a 60-line `if/elif` re-packing kwargs for manager methods, used by exactly one caller for three of its six branches. Call `manager.create_*` directly (as time_tracking already does for `save_comment`) and delete the helper.

### 8.3 `get_epics_feature_df` triples the same block
[devops.py:190-244](src/devops.py#L190-L244): identical 18-line row-dict construction for Epic/Feature/User Story (the only difference is `parent_id`). One loop over `items` with a type lookup does it in a third of the code — and would make adding "Bug" support a one-liner.

### 8.4 Nine identical route handlers
[root.py:194-246](src/pages/root.py#L194-L246): eight copies of `await _setup_spa_shell()`. Replace with:
```python
for path in ["/time", "/add_data", "/board", "/query_editor", "/tasks", "/log", "/info", "/settings", "/notepad"]:
    ui.page(path)(_setup_spa_shell)
```
Also [root.py:179-184](src/pages/root.py#L179-L184): `root_page` fully renders the shell, then immediately `ui.navigate.to("/time")` — a redirect-only handler would skip the wasted render.

### 8.5 `_set_widget_value_safe` (devops_handlers)
[devops_handlers.py:513-534](src/ui/devops_handlers.py#L513-L534): the assignee branch's `if value in options / else` arms are **identical**, and every branch does both `widget.set_value(x)` *and* `widget.value = x`. Collapses to ~6 lines.

### 8.6 Sort options duplicated
[tasks.py:668-678](src/pages/tasks.py#L668-L678) restates the keys of `get_sort_query`'s dict ([tasks.py:186-200](src/pages/tasks.py#L186-L200)). Hoist the dict to module level and use `list(SORT_QUERIES)` for the select.

### 8.7 `parse_widget_values` redundant branches
[helpers.py:1893-1904](src/helpers.py#L1893-L1904): the "Switch" branch (`hasattr value and set_value`) and the fallback (`hasattr value`) return the same thing — one `hasattr(widget, "value")` check suffices.

### 8.8 `settings.py` sleep-and-hope sync labels
[settings.py:764-772](src/pages/settings.py#L764-L772): fire background sync, `await asyncio.sleep(0.5)`, then read `last_incremental_sync` — the sync usually takes longer, so the label shows the *previous* run's time. Have the service emit an event (`devops_refreshed` already exists and is currently listener-less!) and update the label in the handler — this fixes two findings at once.

### 8.9 `on_task_edit_click` sleeps to win races
[tasks.py:266](src/pages/tasks.py#L266), [284](src/pages/tasks.py#L284): `await asyncio.sleep(0.2)` waiting for options to load, then pokes a private `widget._on_parent_change()`. Awaiting the actual load (expose the create-task from `build_form_widgets`, or an async `load()` on the wrapper) removes the timing dependency.

### 8.10 UIStyles singleton ceremony
[helpers.py:18-79](src/helpers.py#L18-L79): `_instance` + `get_instance()` + class-level `_styles`/`_resolved`/`_theme_configured`, plus [app.py:82](src/core/app.py#L82) reaching in with `UI_STYLES.__class__._theme_configured = False` to force re-resolution. Module-level functions with a module-level dict would express the same thing without the reset hack.

---

## 9. Low / Nits

- **Dates table ends 2030-12-31** ([database.py:191](src/database.py#L191)) and only repopulates when *empty* — in 2031, weekly/monthly report queries silently lose rows (inner `join dates`). Extend on startup when `max(date) < today + 1y`.
- **“All-Time” starts 2000-01-01** ([helpers.py:439](src/helpers.py#L439), has a TODO) — should be `min(start_time)` from DB.
- `insert_time_row` accepts `git_id`/`comment` but ignores them when *starting* a timer ([database.py:486-499](src/database.py#L486-L499)) — asymmetric signature.
- `initialize_db`'s `finally` logs "Database loaded without errors!" **even after the except block caught an error** ([database.py:309-313](src/database.py#L309-L313)).
- `_get_widget_value` chip-group branch returns a *boolean* (`any(selected)`) ([helpers.py:641-642](src/helpers.py#L641-L642)) while `parse_widget_values` returns the selected *list* — check_input works by accident.
- `DynamicNumber._refresh_impl` coerces dict-sourced values with `int()` ([dynamic_widgets.py:333](src/ui/dynamic_widgets.py#L333)) — truncates decimal values (e.g. a wage of 850.5) on refresh.
- `extract_table_name` regex grabs the first `from` anywhere ([helpers.py:566](src/helpers.py#L566)) — a CTE or subquery in a custom query yields the wrong "table" for edit-mode; guarded downstream by the editable-table whitelist, so cosmetic.
- Checkbox-ID stamping assumes tags end `...>` not `.../>` ([helpers.py:344-350](src/helpers.py#L344-L350)) — fine with html5lib serialization, brittle if bleach changes.
- Delete-note and settings Reset buttons act **immediately with no confirm** ([notepad.py:787](src/pages/notepad.py#L787), [settings.py:122](src/pages/settings.py#L122), [511](src/pages/settings.py#L511), [559](src/pages/settings.py#L559)) — the board dialog already has a nice discard-confirm pattern to copy.
- Uploaded-DB temp file in add_data's Update tab is never deleted ([add_data.py:506-510](src/pages/add_data.py#L506-L510)); the Compare tab removes its temp file only on success (leak on exception).
- `log.py` filter re-render uses only the global buffer ([log.py:173](src/pages/log.py#L173)), dropping per-core entries the initial render included.
- `PageState.ui_data_df = None` ([time_tracking.py:60](src/pages/time_tracking.py#L60)) — un-annotated in a dataclass, so it's a *class* attribute, not a field. Works (instance assignment shadows), but `ui_data_df: Optional[pd.DataFrame] = None` says what you mean.
- `date_input`/`create_date_range_picker`/`DynamicDateInput` are three implementations of "input with calendar popup" ([helpers.py:651](src/helpers.py#L651), [time_tracking.py:103](src/pages/time_tracking.py#L103), [dynamic_widgets.py:342](src/ui/dynamic_widgets.py#L342)).
- Two date-pickers fire the same change handler twice ([time_tracking.py:138-139](src/pages/time_tracking.py#L138-L139) binds `update:model-value` on both the input *and* the picker that's bound to it) → duplicate `update_time_tracker` tasks per change.
- `get_work_item_description` returns a 4-tuple on success and 2-tuple on failure ([devops.py:561-564](src/devops.py#L561-L564)); the caller defensively indexes (`desc_result[3] if len > 3`). Return a dict or a consistent tuple.
- `devops_columns_cache` is a `defaultdict(dict)` yet callers still `setdefault(customer, {})` ([devops_handlers.py:366](src/ui/devops_handlers.py#L366)).
- Update-checker URL user `mackant` vs repo docs `MackanT` — works (GitHub is case-insensitive), but align for grep-ability.
- `.nicegui/` storage JSON files are committed alongside the repo — gitignore them.

---

## 10. Suggested Priority Order

| # | Action | Effort | Findings addressed |
|---|---|---|---|
| 1 | Wrap all DevOps manager calls in `asyncio.to_thread` (or async facade) | S–M | §2 (all UI freezes) |
| 2 | Fix `insert_task` tuple check; guard `settings_page` for `devops_engine=None` | S | §1.1, §1.2 |
| 3 | Fix SPA event-handler leaks (tasks / log / notepad) | S | §1.3 |
| 4 | Parametrize `dynamic_query`; fix note-rename collision | S | §1.5, §1.4 |
| 5 | `PRAGMA busy_timeout` + route stray cursor writes through the lock; consider a process-wide DB singleton | M | §3.1 |
| 6 | Add `customer_name` to `update_devops_item_fields`; fix 2 AM scheduler; fix NULL-due-date sort | S | §1.8, §1.6, §1.7 |
| 7 | Delete dead code (services, AddData, unused DevOps methods, duplicate members, dead events *or* wire up `ui_refresh_requested` properly) | M | §6 |
| 8 | Fix `notify()` thread-safety; per-client logger names | M | §3.2, §3.3 |
| 9 | Map `"text"` → textarea; unify `optional` default; stop mutating shared configs | S–M | §7.1, §7.2, §3.4 |
| 10 | Batch active-timer query; reuse stop-timer dialog; single event binding in legacy forms | M | §4.1–§4.3 |
| 11 | Consolidate schema definitions; converge on DynamicWidget forms | L | §7.5, §7.4 |
| 12 | Bind to 127.0.0.1 by default; random storage secret; scope markdown CSS | S | §5 |

*Sections §1–§5 are worth doing regardless; §6–§9 pay down maintenance cost; §8's refactors are opportunistic.*
