---

# WorkTimer

>A helper program to keep track of time spent on different tasks, with built-in DevOps integration.

---

## Changelog

### 4.0.0 (2025-09-XX)
- Rewritten UI interface with NiceGUI. Now a (locally hosted) web application
  - Overall cleaner and nicer layout (full screen width compatible!)
  - Color coding in query editor
  - Multirow text input support
- Query Engine
  - "Standard" queries are now stored in the database instead of in code
  - Added option for users to save custom queries in the database for easier future usage
- DevOps Engine
  - Can now request and store table of all DevOps epics, features, and user stories for faster, more responsive UI
  - Ending tasks now has user-story with drop-down list instead of ID input
  - Added support to create user-story directly from the program
- Added database compare feature
  - Schema compare current db-file with old db-file. Simplifies future migration
  - Added option to run code in any db file and save results. Used in conjunction with compare to make changes
- Docker support
  - Added support for running file via docker for a fully independent solution
- Bug fixes
  - Fixed many minor issues with add-data not setting column values correctly in some cases

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