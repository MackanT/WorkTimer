---

# WorkTimer

A modern web-based time tracking application with built-in task management and Azure DevOps integration. Track billable hours across customers and projects, manage to-do lists, create DevOps work items, and analyze your time with custom SQL queries—all through a clean, locally-hosted interface.

---

## Changelog

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
