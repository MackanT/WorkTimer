# WorkTimer — User Guide

Welcome to **WorkTimer** — a locally hosted web application for time tracking with tracker integration (Azure DevOps and Jira).

---

## Getting Started

### Requirements

- **Python 3.11+** with [`uv`](https://docs.astral.sh/uv/) for running directly, **or**
- **Docker** for 24/7 operation

First time with `uv`? Install it and sync the dependencies once:
```powershell
pip install uv      # then restart your terminal
uv sync
```

### Starting the application

**Option A — Direct Python (recommended for development)**
```powershell
uv run -m main
```

**Option B — Docker (recommended for 24/7 operation)**
```powershell
docker compose up -d
```

Docker reads `DB_NAME` and `DEBUG_MODE` from a `.env` file in the project root. Copy `.env.template` to `.env` and edit it to set your values. The `.env` file is gitignored so each user can have their own settings.

Then open **`http://localhost:8080`** in your browser.

### First-time setup

Entity management lives in **dialogs**: click **Data Input** in the nav bar and pick an entity (Customers / Trackers / Projects / Bonus) — the dialog opens over whatever page you're on. The command palette (**Ctrl + K**) opens the same dialogs directly ("Add customer", "Update tracker", …).

1. **Add a customer** — *Data Input → Customers*, fill in the name and wage, click **Add**
2. **Add a project** — *Data Input → Projects* (or the **＋ Add project** button on the customer's card on the Time Tracker), enter a name, click **Add**
3. **Optionally configure a bonus** — *Data Input → Bonus*, fill in the bonus percent, click **Add**
4. **Optionally connect a tracker** — *Data Input → Trackers*, then link it on the customer (see [Tracker integration](#tracker-integration) below)

---

## Navigation

WorkTimer has a fixed top navigation bar with the following pages:

| Page | Purpose |
|------|---------|
| **Time Tracker** | Start/stop timers and view logged hours |
| **Data Input** | A dropdown menu — manage customers, trackers, projects and bonuses in dialogs |
| **Board** | Kanban board + hierarchy view of tracker work items (shown when a tracker is configured) |
| **Reports** | Time analytics dashboard — tiles, charts, CSV export |
| **Query Editor** | Write and run SQL against the local database |
| **Tasks** | Built-in task manager — disabled by default, enable in `config/config_ui.yml` |
| **Notepad** | Markdown notes organised in a sidebar |
| **Log** | Real-time application log |
| **Documentation** | This guide, plus shortcuts, changelog and tracker contacts |
| **Settings** | Tracker sync/defaults/contacts, tags, theme, and data tools |

---

## Time Tracker

Track billable hours across customers and projects.

- **Time span** — filter by Day, Week, Month, Year, All-Time, or a custom date range
- **Start/stop** — click the checkbox next to any project to start or stop a timer
- **Stop dialog** — add a comment, link a tracker work item (★ marks items related to the project's default), re-assign the project, or set a custom stop time
- **Right-click a project row** — add/manage time entries, update the project (rename, default Git-ID), or disable it
- **Right-click a customer header** — update the customer, add a project, or disable the customer
- **Quick-adds** — a dashed *Add customer* card sits at the end of the row; every customer card has an *＋ Add project* button
- **Edit Order** — drag rows to reorder projects (a light line shows where the drop lands), use the arrows for single steps, or hit the **sort** button on a card to order that customer's projects by the last 60 days of logged time; **Save Order** persists

---

## Board & Hierarchy

A Kanban view of the connected trackers' work items, from the local cache.

- **Customer tabs** switch between connected customers; type chips follow the customer's tracker levels (Azure: Epic/Feature/User Story; Jira: Epic/Story/Sub-task)
- **Drag a card** between columns to move it (Azure: board column; Jira: a workflow status transition)
- **Click a card** to open the full dialog — description (markdown editor + preview), state/assignee/priority, comments, image insert/paste, and an *Open in tracker* link
- **Create branch** (Azure DevOps) — the branch button in the card dialog creates a git branch in Azure Repos from a source branch's tip and links it to the work item (its Development area); repo, name and source are editable, with a `story/123-title` style suggestion prefilled. The naming is configurable per tracker/type (see Settings), and the add form has an **Auto-create git branch** switch — turning it on reveals the branch-name template and a base-branch dropdown (repo default preselected), and the branch is made right after the item
- **Search** filters by title, assignee, state, column, id, description and the parent chain; *Incl. done* extends to closed items
- **＋** adds a work item with the current customer/type preset
- The **Hierarchy** toggle renders the same data as a tree, coloured by board column, with story-progress rollups and a Focus selector; ＋ pre-parents under the focused node

---

## Reports

A visual analytics dashboard for your tracked time.

- **Filters** — pick customers (one, several, or all) and a period (Day / Week / Month / Year / Custom)
- **Stat tiles** — hours, billable amount and target utilisation for the selection
- **Charts** — daily hours trend, hours by project, hours by customer, and top work items, coloured by each customer's colour
- **Billing rounding** — round the billable tiles/CSV up to an increment, applied *per entry*, *per work item*, *per project* or on the *grand total*; display-only, never written to the database (the default increment comes from *Settings → Data*)
- **CSV export** — download the current selection for invoicing or further analysis

---

## Managing data (Data Input dialogs)

Each dialog has operation tabs (Add / Update / Disable / Re-enable — Delete for trackers) and closes on a successful save.

### Customers
- **Add** — name, wage, optional tracker link
- **Update** — rename, link/unlink a tracker, pick the tracker project, expected work %, colour
- **Disable / Re-enable** — soft-archive without losing historical entries (disabled customers disappear from the board and pickers; their cached items return on re-enable)

### Trackers
A tracker is a connection (type + org/site + credentials) that customers link to — several customers can share one.
- **Add / Update** — fields follow the type: Azure DevOps takes org + PAT, Jira takes site / account email / API token; secret fields show *blank = unchanged*
- **Token expires** — optional date; when set, WorkTimer shows a sticky warning (once a day, from 30 days out, until you dismiss it) before the PAT / API token runs out, instead of sync silently failing
- **Test connection** — verifies the credentials immediately and lists the org's projects
- **Delete** — removes the tracker and detaches its customers

### Projects
- **Add** — link a project to a customer, optionally with a default work-item (Git) ID
- **Update / Disable / Re-enable** — rename, change the default ID, archive

### Bonuses
- **Add** — record a bonus percentage with a start date (defaults to 0 % when unset)

### Work items
Created from the Board/Hierarchy ＋ or the palette, for any level of the customer's tracker:
- Markdown descriptions with live preview and image insert/paste
- Parent pre-selection and per-level description templates (editable in *Settings → Trackers*)
- Per-tracker/per-type field defaults apply automatically (see Settings)

---

## Query Editor

A full SQL editor for custom data analysis.

- **Preset queries** — click a built-in query to load it instantly
- **Custom queries** — write SQL, save with a name, run later
- **Execute** — press **F5**, **ctrl+enter** or the Run button
- **Edit results** — click any row in the result table to open an edit dialog
- **Copy results** — disable edit mode to copy rows into memory (csv-format)
- **Syntax feedback** — the editor highlights errors before you run
- **Skins** — pick your own editor colour scheme under *Settings → Theme*

---

## Notepad

A markdown-based notebook with a VS Code-style sidebar.

- Notes are stored as `.md` files under `data/notes/`
- Assign colors, icons, and groups from the right-click menu; a `/` in the group name nests sub-groups ("Customer/Project"), and collapsing a parent hides its subtree
- **Drag notes** to reorder — drop on another note to insert before it (adopting its group) or on a group header to move into that group; a light line previews the landing spot
- Click rendered content to switch to split editor + preview mode; press **Escape** to return
- Pin notes to keep them at the top
- An external **Todo** note (`docs/todo.md`) is always pinned and is read-write

---

## Settings

Four tabs, matching the app's standard layout:

### Trackers
- **Synchronisation** — incremental/full sync buttons with last-sync times
- **Work-item form defaults** — prefills for State, Priority, Initial board column, Source and Contact person, per tracker **and per work-item type** ("All types" as the base, a specific type overriding it per field); plus the **Branch name template** (`{{type}}`, `{{id}}`, `{{title}}` — e.g. `feat/{{id}}-{{title}}`) used by branch creation
- **Description templates** — edit the markdown scaffold preloaded into a new work item's description, per level (Epic / Feature / User Story / …). Placeholders: `{{today}}` inserts the creation date; `{{source}}` and `{{contact_person}}` (alias `{{contact}}`) stay in sync with the form's dropdowns — the line carrying the placeholder is rewritten on change, so it can be moved or relabelled freely (keep some label text on it, e.g. `**Source:** {{source}}`)
- **Contacts** — per-customer contacts and assignees used in the work-item forms. The **cloud button** on Assignees fetches the project's members from the tracker (tick whom to import); a **Default Assignee** can be picked per customer

### Tags
Define tags used to categorise work items — icon + colour per tag, add/edit/delete in the table.

### Theme
- **Theme colours** — customise the app colour scheme (Quasar + Tailwind token pairs). Press **Save Theme**, then reload (**Ctrl + R**) to apply
- **Query editor skin** — your personal colour scheme for the SQL editor, with a live preview; saved per user

### Data
- **Backup** — list of recent backups, *Backup now*, and a browser download
- **Time & billing defaults** — global rounding / currency / target settings used by Reports
- **About** — version and update status

---

## Log

Real-time view of all application events.

- Colour-coded by level: Info (white), Warning (yellow), Error (red)
- Each entry shows timestamp, level, source engine, and message
- **Logs are in-memory only** — they reset on restart and are not saved to disk

---

## Tracker integration

WorkTimer speaks to **Azure DevOps** and **Jira Cloud** through per-tracker connections; different customers can use different trackers side by side.

1. *Data Input → Trackers → Add*:
   - **Azure DevOps** — org name (e.g. `my-org`, not the full URL) + a PAT with *Work Items: Read, Write, Manage* scope (add *Code: Read & Write* if you want to create branches from work items)
   - **Jira** — the site (`yoursite.atlassian.net`), your Atlassian account email, and an API token (create one at *id.atlassian.com → Security → API tokens*)
2. Hit **Test connection** — it should list the org's projects
3. *Data Input → Customers → Update* — link the customer to the tracker and pick its project
4. Sync starts automatically; the Board appears in the nav bar

What works on both trackers: board + hierarchy, search, create/update/move work items, comments, image attachments, time-entry linking and comment write-back. Jira specifics: board moves are workflow transitions, status *is* the board column, and markdown converts to native Jira formatting (headings, lists, tables, checkboxes, code, images) in both directions.

**Credentials are encrypted at rest** with a key stored at `data/.pat_key`. The key is deliberately excluded from backups — a backup restored on another machine needs the tokens re-entered.

Sync schedule (background):
- **Incremental** — every hour
- **Full** — daily at 2 AM (or trigger either manually from Settings → Trackers)

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

**Tracker items not appearing**
- Use **Test connection** on the tracker to verify the credentials
- Azure: the PAT needs *Work Items: Read/Write/Manage* scope and the org field is the org name only
- Jira: the API token pairs with your account email; the project field is the project key
- Check the Log page for specific error messages

**Sync data is stale**
- Run a Full Sync from Settings → Trackers (or Ctrl+K → "Sync trackers")

**Tokens unreadable after restoring a backup**
- Expected: the encryption key (`data/.pat_key`) never travels with backups — re-enter the credentials on the trackers

**UI not updating**
- Hard-refresh the browser: **Ctrl + Shift + R** (F5 is reserved by the app)
- Check the Log page for errors

**Database errors**
- Ensure the `data/` directory is writable
- Check the Log page for SQL error details
