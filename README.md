# WorkTimer
A helper program to keep time of time spent on different tasks, with built in DevOps integration.

# Changelog

1.0.1 (2025-09-15)
- Added total counts on time in weekly and monthly selects
- Added ui color customization
- Revamped ui to use tabs and less collapsing headers
- Added keyboard shortcuts to query + log
- Cleaned up ui also in query window
- Added simplified method to reenable old customer and projects
- Closing query now automatically redraws ui (in case changes were made that affect customers, projects, times etc)

1.0.0 (2025-06-26)
- First official release
- Fixed long standing bug with customer headers auto-closing on minimization of the program
- Message popup now supports multiple types, error, info, etc.
- DevOps connector throws better error on failure to connect
- Error/Info and edit popups are now centered on screen upon creation
- Added argpares support '--db {db_name}' to allow running code with multiple databases
- Added option for startup checks on db. Currently only checks if a bonus is added or not
- Newlines are now kept when writing to devops
- When adding or updating customers org-url and pat-token can now be entered directly
- Fixes datepicker not visually reseting every midnight