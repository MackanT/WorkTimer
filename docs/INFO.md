# WorkTimer — User Guide

Welcome to **WorkTimer** — a locally hosted web application for time tracking and Azure DevOps management.

---

## Getting Started

### Starting the application

**Option A — Direct Python (recommended for development)**
```powershell
uv run -m src.main
```

**Option B — Docker (recommended for 24/7 operation)**
```powershell
docker compose up -d
```

Docker reads `DB_NAME` and `DEBUG_MODE` from a `.env` file in the project root. A default `.env` ships with the project — edit it if you want a different database name or debug output.

Then open **`http://localhost:8080`** in your browser.

#### First-time setup with `uv`

If `uv` is not installed:
```powershell
pip install uv
```

Restart your terminal after installation, then sync dependencies:
```powershell
uv sync
```

---

### First-time setup

1. **Add a customer** — open *Data Input → Customer*, fill in the name and wage, click **Add**
2. **Add a project** — open *Data Input → Project*, select your customer, enter a project name, click **Add**
3. **Optionally configure bonus** — open *Data Input → Bonus*, fill in the bonus percent, click **Add**
4. **Optionally configure DevOps** — add an org URL and PAT token on the customer record (see [DevOps integration](#devops-integration) below)

---

## Navigation

WorkTimer has a fixed top navigation bar with the following pages:

| Page | Purpose |
|------|---------|
| **Time Tracker** | Start/stop timers and view logged hours |
| **Data Input** | Add and manage customers, projects, bonuses, and DevOps work items |
| **Query Editor** | Write and run SQL against the local database |
| **Tasks** | Built-in task manager — disabled by default, enable in `config/config_ui.yml` |
| **Notepad** | Markdown notes organised in a sidebar |
| **Log** | Real-time application log |
| **Info** | This guide |
| **Settings** | DevOps contacts, tags, and app theme |

---

## Time Tracker

Track billable hours across customers and projects.

- **Time span** — filter by Day, Week, Month, Year, All-Time, or a custom date range
- **Start/stop** — click the checkbox next to any project to start or stop a timer
- **Active indicator** — an animated icon in the header shows when a timer is running
- **Stop dialog** — when stopping a timer you can add a comment and optionally link a DevOps work item

---

## Data Input

Manage the core entities that drive time tracking and DevOps.

### Customers
- **Add** — name, wage, optional DevOps org URL and PAT token
- **Update** — rename or update DevOps credentials
- **Disable / Re-enable** — soft-archive a customer without losing historical entries

### Projects
- **Add** — link a project to a customer
- **Update** — rename or change DevOps defaults
- **Disable / Re-enable** — archive without losing time entries

### Bonuses
- **Add** — record a bonus percentage with a start date
- If no bonus is configured all calculations default to 0 %

### DevOps Work Items
Create User Stories, Features, and Epics directly from the app:
- Supports markdown descriptions with live preview
- Child items can be linked to a parent feature or epic at creation time
- Requires a valid PAT token on the customer record

---

## Query Editor

A full SQL editor for custom data analysis.

- **Preset queries** — click a built-in query to load it instantly
- **Custom queries** — write SQL, save with a name, run later
- **Execute** — press **F5**, **ctrl+enter** or the Run button
- **Edit results** — click any row in the result table to open an edit dialog
- **Copy results** — disable edit mode to copy rows into memory (csv-format)
- **Syntax feedback** — the editor highlights errors before you run

---

## Notepad

A markdown-based notebook with a VS Code-style sidebar.

- Notes are stored as `.md` files under `data/notes/`
- Assign colors, icons, and groups from the sidebar
- Click rendered content to switch to split editor + preview mode; press **Escape** to return
- Pin notes to keep them at the top
- An external **Todo** note (`docs/todo.md`) is always pinned and is read-write

---

## Settings

Access via the **Settings** page (⚙ icon in the nav bar). Uses a sidebar layout — click a section name to open it. The **Incremental** and **Full Sync** buttons are always visible in the Settings toolbar on the right.

### DevOps Contacts

Manage per-customer contacts and assignees used when creating DevOps work items.

- **Add customer** — click **+** next to *DevOps Contacts* in the sidebar
- **Select a customer** — click its name in the sidebar sub-list
- **Contacts tab** — add/remove delivery contact names (chips)
- **Assignees tab** — add/remove assignee emails (chips)
- **Default Assignee** — pick from the assignees list; saved with the save button
- **Delete customer** — trash icon at the top of the detail panel
- **Reset** — ↺ button restores the bundled template

### DevOps Tags

Define tags used to categorise DevOps work items.

- **Add Tag** — click **+** in the sidebar; choose an icon from the preset list or enter a custom Material icon name; pick a colour
- **Edit / Delete** — action buttons on each row in the table
- **Reset** — ↺ restores the bundled template

### Theme

Customise the app colour scheme.

- **Paired colours** — one picker sets both the Quasar hex value and the nearest Tailwind token (e.g. *Primary / Accent*, *Dark / Toolbar background*)
- **Component colours** — Quasar semantic colours (positive, negative, info, warning)
- **Additional tokens** — Tailwind tokens used for dividers, borders, and chip backgrounds
- A colour swatch updates live as you drag the picker
- Press **Save Theme**, then **F5** to apply

---

## Log

Real-time view of all application events.

- Colour-coded by level: Info (white), Warning (yellow), Error (red)
- Each entry shows timestamp, level, source engine, and message
- **Logs are in-memory only** — they reset on restart and are not saved to disk

---

## DevOps integration

DevOps features require a PAT (Personal Access Token) configured per customer.

1. Go to *Data Input → Customer → Update*
2. Set **DevOps Org. URL** to your organisation name (e.g. `my-org`, not `https://dev.azure.com/my-org`)
3. Set **DevOps PAT** to a token with *Work Items: Read, Write, Manage* scope
4. After saving, DevOps sync will run automatically

Sync schedule (background):
- **Incremental** — every hour
- **Full** — daily at 2 AM (or trigger manually from Settings → DevOps Contacts)

---

## Docker deployment

```powershell
# Start (detached)
docker compose up -d

# View live logs
docker compose logs -f

# Stop
docker compose down
```

The database file is volume-mounted so data persists across restarts. See `docker-compose.yml` for the mount path.

---

## Troubleshooting

**App won't start**
- Check port 8080 is not used by another process
- Verify Python 3.11+ is installed

**DevOps work items not appearing**
- Confirm the PAT has *Work Items: Read/Write/Manage* scope
- Org URL must be the org name only, not the full `https://dev.azure.com/…` URL
- Check the Log page for specific error messages

**Sync data is stale**
- Run a Full Sync from Settings → DevOps Contacts sync strip

**UI not updating**
- Hard-refresh the browser: **Ctrl + F5**
- Check the Log page for errors

**Database errors**
- Ensure the `data/` directory is writable
- Check the Log page for SQL error details

