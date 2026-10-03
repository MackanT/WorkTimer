# WorkTimer — User Guide

WorkTimer tracks your billable hours across customers and projects, with
Azure DevOps and Jira boards, reports, notes and a query editor. Most people
use the shared **hosted WorkTimer** in the browser; it can also run on your
own PC ([Running it yourself](#running-it-yourself)).

---

## Getting started

### Signing in

Open the WorkTimer address you were given and enter your email. You get a
one-time code by email — type it in, and you stay signed in for 30 days on
that browser. Only emails the administrator has added can sign in.

The first time, your WorkTimer is empty, and it is **yours alone**: nobody
else signed in sees your entries, customers, trackers, notes or settings
([Your data](#your-data)).

### Moving from WorkTimer 5.x

Bring everything along in one zip:

1. On the PC where you use 5.x, **close WorkTimer**, open its folder, select
   the **`data`** and **`config`** folders together → right-click → *Send to
   → Compressed (zipped) folder*. Only those two: the whole folder is far too
   big. The zip carries your database, notes and pasted images, the key that
   unlocks your tracker tokens, and your settings.
   (5.x in Docker: first `docker cp worktimer-worktimer-1:/app/config .`, then
   zip `data` with that `config`.)
2. In the hosted WorkTimer: *Settings → Data → Import*, and choose the zip.
   It is checked first — the summary lists customers, entries, notes and
   settings files, and any problem in the 5.x data with what to fix there.
   Nothing is written until you press **Import**.
3. After the import, every customer's entries, hours and cost are shown
   before and after, side by side — they should all match. Your trackers
   connect with the tokens you had; reload the page to see your settings.
4. Stop using 5.x — keep its folder as a fallback.

If the zip is over 95 MB, leave out `data\backups` (5.x's own backup copies).
Only `worktimer.db` works too, but then your notes and settings stay behind
and the tracker tokens must be entered again. Saved queries you wrote
yourself come along, but need rewriting: the table names changed.

### Starting fresh

Entity management lives in **dialogs**: click **Data Input** in the nav bar and pick an entity (Customers / Trackers / Projects / Bonus) — the dialog opens over whatever page you're on. The command palette (**Ctrl + K**) opens the same dialogs directly ("Add customer", "Update tracker", …).

1. **Add a customer** — *Data Input → Customers*, fill in the name and hourly rate, click **Add**
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
| **Query Editor** | Write and run SQL over your data |
| **Tasks** | Built-in task manager — shown when switched on for this WorkTimer |
| **Notepad** | Markdown notes organised in a sidebar |
| **Log** | Real-time log of what WorkTimer does for you |
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

A running timer keeps running when you close the tab — it shows as a pill in
the nav bar wherever you open WorkTimer next.

---

## Board & Hierarchy

A Kanban view of the connected trackers' work items, from WorkTimer's copy of them.

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
- **Add** — name, hourly rate, optional tracker link
- **Update** — rename, link/unlink a tracker and pick its *Tracker project* (the DevOps/Jira project the Board, sync and new work items use — listed from the selected tracker; without its token, only the projects other customers already use on it), expected work %, colour
- **Hourly rate** (in *Update*) — a new rate from any date (*Rate from*), also back in time: it applies until the customer's next rate change. Below the form, *Hourly rates* lists the customer's rates (from, to, rate); once you change the rate or its date, *After saving* shows the result, and beside each changed period how many time entries get the new price and how the amount changes — saving asks first. Time dated before the change keeps its price. A change entered by mistake goes with its **✕** in the list: the earlier rate applies again
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

A SQL editor for your own analysis. Queries only read, and only ever see
your data.

- **Preset queries** — click a built-in query to load it instantly
- **Custom queries** — write SQL, save with a name, run later
- **Execute** — press **F5**, **ctrl+enter** or the Run button
- **Edit results** — with *Edit Mode* on, click a cell of a time entry, customer or project to change it
- **Copy results** — with *Edit Mode* off, select rows and copy them (csv-format)
- **Syntax feedback** — the editor highlights errors before you run
- **Skins** — pick your own editor colour scheme under *Settings → Theme*

---

## Notepad

A markdown-based notebook with a VS Code-style sidebar.

- Your notes are your own — pasted images included
- Assign colors, icons, and groups from the right-click menu; a `/` in the group name nests sub-groups ("Customer/Project"), and collapsing a parent hides its subtree
- **Drag notes** to reorder — drop on another note to insert before it (adopting its group) or on a group header to move into that group; a light line previews the landing spot
- Click rendered content to switch to split editor + preview mode; press **Escape** to return
- Pin notes to keep them at the top

---

## Settings

Four tabs, matching the app's standard layout. Everything here is your own.

### Trackers
- **Synchronisation** — incremental/full sync buttons with last-sync times
- **Work-item form defaults** — prefills for State, Priority, Initial board column, Source and Contact person, per tracker **and per work-item type** ("All types" as the base, a specific type overriding it per field); plus the **Branch name template** (`{{type}}`, `{{id}}`, `{{title}}` — e.g. `feat/{{id}}-{{title}}`) used by branch creation
- **Description templates** — edit the markdown scaffold preloaded into a new work item's description, per level (Epic / Feature / User Story / …). Placeholders: `{{today}}` inserts the creation date; `{{source}}` and `{{contact_person}}` (alias `{{contact}}`) stay in sync with the form's dropdowns — the line carrying the placeholder is rewritten on change, so it can be moved or relabelled freely (keep some label text on it, e.g. `**Source:** {{source}}`)
- **Contacts** — per-customer contacts and assignees used in the work-item forms. The **cloud button** on Assignees fetches the project's members from the tracker (tick whom to import); a **Default Assignee** can be picked per customer

### Tags
Define tags used to categorise work items — icon + colour per tag, add/edit/delete in the table.

### Theme
- **Theme colours** — your colour scheme for the app (Quasar + Tailwind token pairs). Press **Save Theme**, then reload (**Ctrl + R**) to apply
- **Query editor skin** — your colour scheme for the SQL editor, with a live preview

### Data
- **Backup** — *Backup now* keeps a copy of your data, listed here; *Download* saves one to your PC
- **Import** — bring in a 5.x zip or database, or a WorkTimer backup ([Moving from WorkTimer 5.x](#moving-from-worktimer-5x))
- **Time & billing defaults** — rounding and target settings used by Reports
- **About** — version, plus **Report a bug** / **Request a feature** buttons that open a prefilled GitHub issue (also available from the command palette)

---

## Log

Real-time view of what WorkTimer does for you — syncs, saves, errors.

- Colour-coded by level: Info (white), Warning (yellow), Error (red)
- Each entry shows timestamp, level, source engine, and message
- **Logs are in-memory only** — they reset when WorkTimer restarts

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

**Tokens are stored encrypted.** Where they can't be read — a backup
restored elsewhere, or a 5.x `worktimer.db` imported without its zip — enter
them again on the tracker.

Sync schedule (background):
- **Incremental** — every hour
- **Full** — nightly, between 02:00 and 04:00
- Or trigger either from *Settings → Trackers* (or Ctrl+K → "Sync trackers")

---

## Your data

On the hosted WorkTimer, each person has their own account. Your time
entries, customers, trackers and their tokens, notes, settings, theme, saved
queries and log are yours: nobody else signed in can see them, and the Query
Editor reads only your rows. The administrator, who runs the server, can
reach its database and backups — as with any hosted service.

The server is backed up every night. Your own copy is a click away:
*Settings → Data → Download*.

---

## Running it yourself

WorkTimer also runs on your own PC, with Python or Docker — see the
[README on GitHub](https://github.com/mackant/worktimer/blob/main/docs/README.md)
for installing and updating. There, WorkTimer has no sign-in and everything
lives in its `data/` folder: notes in `data/notes/` (with a pinned Todo note,
`docs/todo.md`), backups in `data/backups/`, and the key that unlocks your
tracker tokens in `data/.pat_key` — never copied into backups.

---

## Troubleshooting

**"Reconnecting" or a sign-in page after a long time away**
- Your 30-day sign-in ran out: reload the page and sign in again with the emailed code

**Tracker items not appearing**
- Use **Test connection** on the tracker to verify the credentials
- Azure: the PAT needs *Work Items: Read/Write/Manage* scope and the org field is the org name only
- Jira: the API token pairs with your account email; the project field is the project key
- Check the Log page for specific error messages

**Sync data is stale**
- Run a Full Sync from Settings → Trackers (or Ctrl+K → "Sync trackers")

**Tokens unreadable after an import or restore**
- Re-enter the credentials on the trackers (see [Tracker integration](#tracker-integration))

**A saved query fails after moving from 5.x**
- The table names changed: open the query, look up the new names in the preset queries, and save it again

**UI not updating**
- Hard-refresh the browser: **Ctrl + Shift + R** (F5 is reserved by the app)
- Check the Log page for errors
