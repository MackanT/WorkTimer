---

# WorkTimer

A modern web-based time tracking application with built-in task management and Azure DevOps integration. Track billable hours across customers and projects, manage to-do lists, create DevOps work items, and analyze your time with custom SQL queries—all through a clean, locally-hosted interface.

---

## Changelog
### 5.0.5 (2026-xx-xx)
- **Features**
  - ad recommended work items first in the timer dialogs' DevOps-ID dropdown — when the project has a default work item, that item and its whole subtree (an Epic's features + stories, a Feature's stories; breadth-first, then everything else in the old order) float to the top of the list, so the item you're logging against is right there instead of buried in an arbitrary sort. Recommended (same-subtree) entries are marked with a **★** so it's visible where the related group ends. Applies to both the stop dialog and the manual-entry dialog; type-to-filter unchanged.
  - rf Settings page redesigned around the app's standard toolbar-tab idiom (like Data Input / Info) — the hand-rolled sidebar with hard-coded colours is gone. Four tabs: **DevOps** (sync controls moved out of the toolbar into a Synchronisation card + the contacts editor with an in-panel customer selector), **Tags**, **Theme**, and a new **Data** tab. Per-section actions (Add / Reset / Save) now live inside the section they affect; every panel gets the same scroll + card + accent-header treatment.
  - ad Settings → Data tab: the **Backup** dialog is now an inline card (recent backups listed, Backup now / Download); an **About** card shows the app version + update status; and a **Time & billing defaults** editor lets you change the global rounding / currency / target settings from the UI — saved to a small `config/time_settings.yml` override merged over `config_ui.yml` at load, so the commented main config file is never rewritten (applies live for the current session).
  - ad **command palette** — press **Ctrl+K** anywhere to open a searchable palette (type to filter, ↑/↓ + Enter, or click): jump to any page, **start a timer on any project**, **stop a running timer** (routes through the normal stop dialog on the Time page, so comment / project re-assign / stop-time all still apply — even when triggered from another page), sync DevOps incrementally, or back up the database (same folder/keep-10 as Settings). Timer actions update the nav-bar pills and the Time page immediately. Also: **Go to Board — Kanban / Hierarchy view** (jumps straight into either board view) and **Add Epic / Feature / User Story** (opens the board's add dialog with the type pre-selected, from any page; types come from the tracker provider's hierarchy). Inside the SQL query editor Ctrl+K remains the comment chord; the browser's own Ctrl+K is suppressed elsewhere. Typing **`#`** switches the palette into **work-item find-mode**: the same matching as the board's search (all words, case-insensitive, incl. the parent/ancestor chain) but across ALL customers, types and states (closed included, shown greyed with the customer's colour dot; newest-changed first, capped at 12); Enter opens the item's full dialog (description, comments, Open-in-DevOps) without navigating anywhere. The command list itself never grows — work items only appear behind the `#` prefix.
  - rf hierarchy nodes are now coloured by **board column** instead of by type — "everything active = green" hid exactly what the board shows, so In Progress / On Hold / New etc. each get a colour (deterministic palette, cycled for many columns), items in a done-token column or done state grey out, and column-less items show neutral slate. The legend is now **dynamic**, built from the same colour map for the currently visible slice (customer / focus / show-closed), so it always matches the graph. Item type still reads from tree depth.
  - ad create work items from the Hierarchy view — the hierarchy toolbar gains a ＋ button, so a filtered subtree no longer forces a round-trip back to the Board to add something. When a node is focused, the new item is **pre-parented under it** and defaults to the next level down (focused Epic → new Feature, focused Feature → new User Story, with the Parent dropdown pre-selected); whole-tree or leaf focus opens the normal add form. The graph redraws immediately after a successful add.

### 5.0.4 (2026-09-01)
- **Features**
  - ad manage individual time entries from the Time Tracker — right-click a project row → "Manage entries" lists the completed entries in the selected date range with inline edit (start / end / comment) and delete, so fixing a wrong time or removing a stray entry no longer needs the query editor. Edits recompute `total_time`/`cost` via the update trigger; new `update_time_entry` / `delete_time_entry` DB helpers (keyed by `time_id`).
  - fx image insert (Insert-image button + paste-to-upload) is now available when **creating** a DevOps work item, not only when updating one — closes the gap in the board's add dialog. Since the customer is chosen in the add form (and can change), the upload target resolves at upload time and the paste handler's customer stays in sync as the selection changes.
  - ad re-assign a time entry's project when stopping a timer — the stop dialog now has a Project dropdown (the customer's projects; defaults to the one the timer ran on), so an entry started on the wrong project (e.g. "generic" → "specific task") can be moved on save without a trip to the query editor. Moves the denormalized `project_name` too so reports stay correct; `total_time`/`cost` are recomputed and unchanged (same customer/wage).
  - ad stop a timer at a past time — the stop dialog shows "Stop: now" with a small clock button that reveals a custom stop-time picker, so a forgotten running timer can be backdated instead of over-billing. Left untouched, the stop time is stamped when Save is pressed (not when the dialog opened); a manual value is rejected if it precedes the timer's start, and `total_time`/`cost` recompute from the chosen end. The symmetric counterpart to the existing "Start from past time".
  - ad search box on the DevOps Board — filter the current board (selected customer + type) by a case-insensitive substring across each card's title, assignee, state, board column, #id, and its **ancestor chain** (parent → … → epic, by id + title, so searching a parent's key/name surfaces its children). Debounced, clearable. An **"Incl. done"** toggle (remembered per user) also searches Done/closed items, surfacing matches in their columns while a search is active (it won't flood the board otherwise). Note: descriptions aren't in the local cache so they aren't searched.
- **Major changes**
  - rf pluggable tracker architecture (prep for Jira & co. — no behavior change): new `src/trackers/` package with a `TrackerProvider` contract (connect, fetch work items as the canonical DataFrame, board moves, create/update, comments, attachments, `type_hierarchy()`, `capabilities()`) and a provider registry. Azure DevOps is now the first module (`AzureDevOpsProvider`, key `devops`): the org-URL building, `System.*` field mapping, and PAT attachment fetches moved out of `DevOpsManager` into it, leaving the manager a provider-neutral per-customer multiplexer. New auto-migrated `customers.integration_type` column (default `'devops'`) selects each customer's provider — different customers can use different trackers once more modules exist. The board's work-item type chips/seeding now come from the provider's `type_hierarchy()` instead of hard-coded Epic/Feature/User Story.
- **Minor improvements**
  - fx Ctrl+Enter in the query editor no longer also inserts a newline into the SQL — the keypress is intercepted before CodeMirror sees it and only runs the query (F5 / Ctrl+Enter outside the editor unchanged).
  - ad Visual-Studio-style comment chord in the query editor: **Ctrl+K Ctrl+C** comments the selected lines with `-- `, **Ctrl+K Ctrl+U** uncomments (the built-in Ctrl+/ still works). Blank lines are left alone; the chord times out after 2 s.
  - fx the results grid's Ctrl+C row-copy no longer hijacks copying anything else while grid rows are still selected from an earlier click — copying from the row-edit dialog's fields (e.g. a description), from the SQL editor, or any selected text on the page now copies what you actually selected; row-copy only kicks in when nothing else is being copied.
  - rf Notepad's toolbar now wraps its title in the shared toolbar-group, so the page icon + title spacing matches every other page (it was sitting a full gap width apart).

### 5.0.3 (2026-08-11)
- **Features**
  - ad per-customer fields (auto-migrated): **expected work %**, a **billing-rounding** override, and an **indicator colour**. Editable in Add Data (add/update customer) and via the query-editor row dialog; the "Wage" label is now "Hourly rate" (UI only — the `wage` column is unchanged). On Reports, the utilisation target derives from the selected customers' expected % (summed; all customers when none selected) and billing rounding is applied automatically from a single selected customer's setting (or the global default) — no manual toggle. The indicator colour is used throughout: a dot on the board's customer tabs and on time-tracker customer cards, a left-edge tint on board cards, a filled customer badge in the work-item dialog, and — when exactly one customer is selected on Reports — the accent for that customer's trend + cumulative charts. The "Hours by customer", "Hours by project", and "Top work items" bar charts are always coloured per customer (each project / work item resolves to its customer's colour).
  - ad Reports customer filter is now a **multi-select** (pick any set of customers, or none for all) whose selection is **remembered per user** as the default view.
  - ad Reports page: a visual time-analytics dashboard (ECharts, no new deps) — stat tiles (hours / amount / entries / active days / % of target) each with a period-over-period ▲▼ delta; a daily hours trend with a rolling-average line; a cumulative-hours line with a utilisation target reference (100% = target hours/day × workdays × target%); and hours-by-project, hours-by-customer, and top-work-items (by git_id) bar charts. Filter by customers (multi-select) + period (Day/Week/Month/Year/Custom). Periods are to-date (Month = MTD vs the previous month's first N days). Hours count still-running timers up to now (coalesce(end_time, now)), not just stopped entries. A **Rounding** control picks the billing-rounding basis — off / per entry / per work item / per project / grand total — plus a **"round up to (min)"** increment input (seeded from a single selected customer's setting, editable, remembered per user). Rounds **up** by default (billing convention; `time_settings.rounding_mode` can switch to nearest/down). Applied to the billable tiles + CSV only; charts and the live Time Tracker always show real tracked hours, and nothing is ever written to the DB (display-only). New `time_settings` config (rounding, currency, target hours/day + %).
  - rf merged the Hierarchy view into the Board page. The Board toolbar gains a "Board | Hierarchy" toggle; the two views share the selected customer (remembered per user). The standalone Hierarchy page, its `/hierarchy` route, and its nav entry are removed — `hierarchy_page` became an embeddable `create_hierarchy_view()`.
  - ad database backup (Settings → "Backup" in the toolbar): "Backup now" writes a consistent copy to a `backups/` folder next to the database (keeps the last 10) and "Download" saves one via the browser. Uses SQLite's online-backup API (`Database.backup_to`), safe while the app is running — never a raw file copy.
  - ad image support in the markdown editors: an Insert-image button (opens the file picker directly — no dialog) and paste-to-upload. Notepad images save into the note's assets folder; DevOps work-item descriptions upload images as DevOps **attachments** (the returned URL is embedded, so it renders in Azure DevOps). New `DevOpsClient/Manager/Engine.upload_attachment` + `/upload_devops_image` endpoint.
  - ad markdown formatting toolbar on every markdown editor: bold/italic/inline-code (wrap selection), bullet/numbered/task-checkbox lists, heading, quote, code block, and link — each transforms the current selection in the editor (block marks toggle on/off), so the markdown syntax is discoverable without typing it.
  - ad markdown-table builder: a "Table" button on every markdown editor (DevOps descriptions, notepad) opens a grid dialog — set rows (up to 30) / columns (up to 8), fill cells, pick per-column alignment (shown live in an HTML preview), then either Insert at the editor's cursor (via the CodeMirror view, kept in sync) or Copy to clipboard. Paste an existing table into the dialog to edit it. Core `build_markdown_table` / `parse_markdown_table` are unit-tested (alignment, pipe/newline escaping, ragged rows, build↔parse round-trip).
  - ad multi-project support per customer: a `devops_project` column (auto-migrated) lets a customer target a specific project in an org that has several, instead of always the alphabetically-first. The customer "Update" form gains a Project dropdown populated from the org's live project list (preselecting the current choice); connect() falls back to the first project, so existing customers are untouched. Changing it re-inits the DevOps engine.
  - ad DevOps work-item picker for Git ID everywhere it's edited — Add Data "Add project" & "Update project", and the query-editor row-edit for `time` and `projects` rows. A searchable dropdown of the relevant customer's active work items (pick one instead of typing a raw id); falls back to manual entry when DevOps is offline. New `devops_id` dynamic-widget type + `DevOpsEngine.get_work_item_options`.
  - ad draggable divider in the query editor to resize the query input vs. the results grid (position remembered per user)
  - ad work-item comments to the devops dialog (board card click + hierarchy node click) - view existing comments and post new ones - plus an "open in azure devops" link
  - ad interactive hierarchy - click a node to view/edit its fields, description and comments in a dialog
  - ad informative hierarchy nodes - progress rollups on epics/features ("144 of 154 done") and done items greyed out, with a legend entry
  - rf hierarchy nodes look nicer - rounded borderless shapes with a soft shadow to match the app's cards
  - rf board + hierarchy toolbars now use the app's labelled toolbar-group layout (icon + page title, uppercase section labels, dividers) to match the other pages; hierarchy's layout direction is now chip buttons matching the board's type chips (shared segmented_chips component)
  - rf board cards are now rounded and borderless with a soft shadow (matching the app's cards / hierarchy nodes), and column headers use a consistent semibold title + subtle count
  - rf route board + hierarchy muted text through the theme's muted token, and "done" indicators through the theme's positive colour, so re-theming propagates (no more hardcoded text-grey-* literals)
  - rf devops comments - newest first, with the add-comment box above the thread
  - ad devops hierarchy page - epic/feature/user-story tree rendered as a mermaid graph, per customer, with a "show closed" toggle, zoom controls, a scrollable viewport, a focus selector to drill into a single epic/feature's subtree, a colour legend, a top-down/left-right layout toggle, and visible arrows
  - fx hierarchy nodes rendering empty for titles with special characters - "[ref:...]" metadata tags are stripped and node labels are now whitelisted to letters/digits/space/.,:- so no mermaid-breaking character (()[]{}<>|"/+%?! etc.) can survive
  - fx hierarchy large trees opening as an unreadable 170-node scatter - customers with many items now open focused on the first epic (a tight subtree); small trees still open whole, and "Whole tree" stays in the focus dropdown
  - fx hierarchy nodes rendering as empty boxes despite valid text - mermaid now draws labels as native svg text (htmlLabels:false) instead of html in a foreignObject, which blanked out at certain positions (especially under the zoom transform)
  - ad delete option for tasks (delete button in the task update panel, with confirmation)
  - ad auto re-initialize devops when a customer's pat token / org url is added or changed (no app restart needed)
- **Major changes**
  - fx run all azure devops api-calls in worker threads - ui no longer freezes during syncs, board dialogs or form saves
  - rf remove dead scaffolding code (broken services, unused engines, events and devops methods)
- **Minor improvements**
  - ad indicator in software to warn/notify user if they are running a older version of the software (compares the local `pyproject.toml` version against `main`'s using a proper semver check — so 5.0.10 > 5.0.2, and a local build ahead of main never shows a false "downgrade")
  - fx task creation reporting success even when the insert failed
  - fx settings page crashing when devops is not configured
  - fx event-handler leaks when re-visiting tasks/log/notepad pages
  - fx note rename overwriting existing notes with the same title + ad delete confirmation
  - fx task update form breaking on titles containing quotes (parameterized dynamic queries)
  - fx daily 2am devops sync waiting an extra day when app started between 00:00-02:00
  - fx devops cache updates hitting the wrong customer on work-item id collisions
  - fx markdown preview css leaking styles into the rest of the app
  - fx "text" form fields rendering single-line (now multiline, affects task description)
  - fx bind to 127.0.0.1 by default + per-install random storage secret (set HOST in .env for lan access)
  - ad db busy_timeout + consistent locking (avoids "database is locked" with multiple tabs)
  - ad auto-extension of dates table horizon (weekly/monthly reports would go blank after 2030)
  - ad live theme apply on save + correct reload hint (ctrl+r, f5 is reserved for query editor)
  - ad board/time pages now auto-refresh after devops syncs and data edits (wired up existing events)
  - fx pin python 3.11 via .python-version + declare missing direct deps in pyproject (dotenv, pyyaml, requests, pygments)
  - rf time-tracker midnight day-view rollover now uses the shared, unit-tested next-occurrence helper (verified timing; the refresh logic was already correct)
  - rf share one db connection across all browser tabs (was one connection + schema init per tab)
  - ad schema auto-migration on startup - adds missing columns and recreates missing/outdated triggers from one source of truth (replaces the temp devops migration)
  - fx backdated manual time entries now get the bonus rate valid on the entry date (was: today's rate)
  - fx scripts now read DB_NAME from .env like the app (scanned a nonexistent database before)
  - ad confirmation dialogs on the settings reset buttons
  - fx "All-Time" range now starts at the first recorded entry (was hardcoded 2000-01-01)
  - fx log page filter no longer drops client-local entries
  - rf misc cleanup - form loads awaited instead of sleeps, cached form data sources, theme re-resolution by content, temp-file cleanup, removed unenforceable task foreign keys
  - rf remove the legacy form factory (~700 lines) - all forms now render via the dynamic widget system (ad datetime widget type to cover the last gap)
  - fx restore conditional field visibility in devops forms (source/contact/parent now hide again based on work item type - silently broken since the board rework)
  - rf split helpers.py into ui_styles.py + markdown_utils.py, mv task card component into tasks page
  - fx updating a customer/project without passing devops credentials/git-id no longer wipes them
  - fx notepad checkbox clicks not toggling the markdown (dispatcher state was silently copied by app.storage.client)
  - ad local regression test suite (66 tests, `uv run pytest`) covering the schema/db, forms, markdown, events and devops logic changed in this release
  - fx stop uv rebuilding worktimer as a package on every sync (`package = false`) - fixes the intermittent "Access is denied" on the dist-info inside OneDrive

### 5.0.2 (2026-06-01)
- **Major changes**
  - ad new boards tab to be new devops/kanban base
  - ad easier way to move items between columns in devops + see work item descriptions and info
  - mv devops logic from data-input tab to new devops tab
- **Minor improvements**
  - ad safety checks to db-operations
  - ad missing logging to code (change print -> logger)

### 5.0.1 (2026-04-30)
- **Minor improvements**
  - ad support for syntax-highlighting in markdown viewers
  - ad support for checkboxes in markdown viewers
  - ad active-timer indicator in navigation bar
  - ad better small screen support
  - ad support for starting timers in post
  - rf simplifed time_tracking code
  - up notepad colors/icons/external documents are now defined in config files
- **Bug Fixes**
  - fx issue where drop-downs do not auto-set defualt values
  - fx issue where notepad markdown had issues on different browsers
  - fx issue where summing total time per customer did not include scd2 historic data

### 5.0.0 (2026-04-06)

- **Architecture — complete rewrite**
  - Per-client `AppCore` orchestrator: each browser tab gets its own isolated app state
  - Multi-client support — a single user can have multiple tabs open simultaneously without state conflicts
  - Event-driven UI updates via `EventBus`; components subscribe to events rather than polling
  - SPA sub-page routing: all pages pre-loaded, navigation happens without full page reload
  - Persistent page state across navigation (scroll position, selected items, etc.)
  - Config loading centralised in `AppCore._load_configs`: theme, UI, data, DevOps contacts all reloaded per client

- **UI**
  - Complete visual overhaul — cleaner, simplified layout across all pages
  - Consistent page height and card sizing (previously hardcoded per page)
  - Cleaned up and consolidated `config_ui_styles.yml`

- **Settings — complete redesign**
  - New VS Code-style sidebar navigation replacing the old tab bar
  - **DevOps Contacts** — manage customers, contacts, and assignees entirely from the UI; no more manual YAML editing
    - Accordion sidebar with per-customer sub-list
    - Chip-based add/remove for contacts and assignees in a tabbed detail panel
    - Default assignee picker now works correctly and is persisted
    - Add/delete customers directly from the sidebar; reset button restores bundled template
  - **DevOps Tags** — full add / edit / delete / reset from the settings UI
  - **Theme** — live colour picker with inline swatches on all colour fields; save then refresh to apply
  - DevOps **Incremental** and **Full Sync** buttons in the toolbar to force updates

- **Theme & Styling**
  - New `config_theme.yml` — full colour scheme customisation without touching code
  - Quasar CSS variables and Tailwind token resolution managed automatically

- **Notepad — new page**
  - Markdown notes stored as `.md` files under `data/notes/`
  - VS Code-style sidebar: assign group, colour, and icon per note; pin notes to top
  - Click rendered content to enter split editor + preview mode; press Escape to return
  - Auto-saves on edit with debounce
  - Paste images directly into the editor
  - External `docs/todo.md` always pinned and editable in-app

- **Log**
  - Filter log by level (Info / Warning / Error)
  - Export log to file
  - Clear log button

- **DevOps**
  - Added: Can now set board column of new and existing devops items
  - Fixed: application now recovers and reconnects if internet is unavailable at startup
  - Fixed: DevOps integration now auto-enables when the first customer with a PAT token is added (no restart required)
  - Fixed: tags defined in config file now propagate correctly to DevOps work items

- **Time Tracker**
  - Right-click a project row to add an extra time entry without starting/stopping a live timer
  - Active timer is now clearly marked with an animated indicator on the project card

- **Query Editor**
  - Non-SELECT queries (CREATE, ALTER, UPDATE, DELETE) now show a success/info notification on completion instead of silently returning nothing
  - Toggle edit mode on query results; when disabled, rows can be copied to clipboard in CSV format

- **Bug Fixes**
  - Settings changes (theme, contacts) now trigger refresh of dropdowns on the Data Input page
  - Dropdowns no longer show all options when the parent field is blank — they stay empty until a parent is selected
  - Default assignee is now correctly applied when creating DevOps work items

### 4.0.3 (2026-01-17)
- **Minor improvements**
  - Added so devops table is created if not present on program startup
- **Bug Fixes**
  - Fixed bug where adding customers with wage=0 did not work
  - Fixed bug where devops changes were not auto-triggered by incremental refreshes of devops data
  - Fixed bug where adding new projects to existing customer did now always auto-trigger UI-update

### 4.0.2 (2025-12-17)
- **Minor improvements**
  - Top navigation bar is now locked at top of screen
  - When logging devops-id to task, only New and Active items are shown
  - rewrote loging to be simpler and follow standard python logging
  - Switched log to use ui.log with better futureproofing + auto-scroll function
  - Added scrollable feature to time tracker customer card and made it a bit more compact
  - Active timer icon is now more responsive and triggers directly
  - Added option to resort customers and projects in time-tracker
  - Added new scehma-fixer function to automatically loop over db, and find any missing columns and or triggers with option to auto-apply them
  - Fixed bug where one could not update a old time via ui if comment was blank

### 4.0.1 (2025-11-26)
- **Centralized Settings**
 - Environment variables and other global settings are now stored in `.env` file to ensure both Docker and Python code can use the same values - Previously these were stored in both a `config_settings.yml` file for python and a `docker-compose.yml` file for Docker.
- **Bug Fixes**
  - **Timezone issue** - Timezone used by application is now specified in dockerfile. Now defaults to Stockholm/Sweden instead of UTC-0.
  - **Customer changes w. Devops** - Code previously attempted a devops refresh after adding or updating a customer. This crashed the program if no devops customers existed. Added catch to only run if needed.
  - **Docker db-initialization** - Code previously crashed if db-initializing proceeded via Docker as mounted file created a directory instead of sqlite file. Docker now mounts a directory instead in which the code generates the db. 
  - **Adding Customer Wage** - Fixed issue where float input fas used, is now corrected to int.
  - **Adding Tasks** - Fixed bug where `Assigned To` was a drop-down selection without values. Is now a input for text instead.
  - **Updating Tasks** - Fixed bug where `Status` and `Priority` in were not set correct when updating. Before the current value was used as options instead of default-option, and the correct options were removed. Now standard options are shown and selected values is used as default.
  - **Deleting Tasks** - Fixed bug where deleting tasks only set status to "Completed" instead of actually removing them.


### 4.0.0 (2025-11-17)
- **Rewritten UI interface** - Complete rewrite with NiceGUI as a locally hosted web application
  - **Full-width compatible layout** - Cleaner, modern design that adapts to screen width
  - **Color-coded query editor** - Syntax highlighting for SQL queries
  - **Multirow text input** - Better support for long-form text entry
  - **YAML-driven configuration** - Add new entries without code changes via config files
  - **Centralized UI styling system** - All UI styles managed through `config_ui_styles.yml` for consistency
  - **Modern log viewer** - Redesigned log window with dark theme, monospace fonts, and terminal icon
- **To-Do System** - Built-in task management (non-DevOps)
  - **Task tracking** - Store tasks with descriptions, due dates, priority, and status
  - **Card and table view modes** - Toggle between visual card grid and detailed table view
  - **Task visual customization** - Customer/project icons and colors via `task_visuals.yml`
  - **Priority and status filtering** - Sort tasks by due date, priority, status, customer, or project
  - **Inline task editing** - Click cards to switch to view/edit mode
- **Query Engine Enhancements**
  - **Database-stored queries** - Standard queries now in database instead of hardcoded
  - **Custom query management** - Save, update, and delete user-defined queries
  - **Query result row editing** - Edit individual rows directly from query results
  - **Syntax validation** - Real-time SQL syntax checking before execution
- **DevOps Engine Improvements**
  - **Local work item cache** - Store epics, features, and user stories for faster UI response
  - **User story dropdown** - Replace ID input with searchable dropdown when ending tasks
  - **Work item creation** - Create user stories, features, and epics directly from the program
  - **Automatic sync** - Full and incremental DevOps loads run automatically
  - **Contact management** - YAML files for employees and customer contacts for dropdown simplification
  - **Markdown preview** - Live preview of formatted descriptions when creating work items
  - **Parent work item linking** - Automatically link user stories to features/epics
- **Database Tools**
  - **Schema comparison** - Compare current db with old db files for migration planning
  - **Database script runner** - Execute SQL on any db file and save results for migration
- **Docker Support**
  - **Containerized deployment** - Run via Docker for fully independent solution
- **Info & Documentation**
  - **In-app documentation** - FAQ and README visible within the program
  - **Enhanced logging** - Separate logs per engine (DevOps, QueryEngine, WorkTimer) with source tracking
- **Code Architecture & Quality**
  - **Modular UI structure** - UI split into separate modules (time_tracking, tasks, query_editor, add_data, utils)
  - **Generic form builder** - `EntityFormBuilder` and `DataPrepRegistry` pattern for DRY form generation
  - **Centralized helper functions** - Eliminated 250+ lines of duplicate code through helper consolidation
  - **DataFrame validation helpers** - Reusable functions for checking empty DataFrames
  - **Standardized save handlers** - Generic save button system reduces form boilerplate
- **Bug Fixes**
  - **Add-data column values** - Fixed multiple issues with incorrect column value handling
  - **Customer ID propagation** - Updating customer IDs now propagates to existing projects
  - **Card layout conflicts** - Removed conflicting CSS classes in card padding styles

### 3.0.1 (2025-09-15)
- Added total counts on time in weekly and monthly selects
- Added UI color customization
- Revamped UI to use tabs and less collapsing headers
- Added keyboard shortcuts to query + log
- Cleaned up UI also in query window
- Added simplified method to re-enable old customers and projects
- Closing query now automatically redraws UI (in case changes were made that affect customers, projects, times, etc.)

### 3.0.0 (2025-06-26)
- First official release
- Fixed long-standing bug with customer headers auto-closing on minimization of the program
- Message popup now supports multiple types: error, info, etc.
- DevOps connector throws better error on failure to connect
- Error/Info and edit popups are now centered on screen upon creation
- Added argparse support: `--db {db_name}` to allow running code with multiple databases
- Added option for startup checks on db. Currently only checks if a bonus is added or not
- Newlines are now kept when writing to DevOps
- When adding or updating customers, org-url and pat-token can now be entered directly
- Fixes datepicker not visually resetting every midnight
