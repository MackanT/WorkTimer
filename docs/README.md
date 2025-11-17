---

# WorkTimer

A modern web-based time tracking application with built-in task management and Azure DevOps integration. Track billable hours across customers and projects, manage to-do lists, create DevOps work items, and analyze your time with custom SQL queries—all through a clean, locally-hosted interface.

---

## Changelog

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
