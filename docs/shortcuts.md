# Keyboard shortcuts & quick interactions

## Everywhere

| Shortcut | Action |
|---|---|
| **Ctrl + K** | Open the **command palette** — jump to pages, start/stop timers, add work items (every tracker level), open the data dialogs (add/update customer, tracker, project…), switch board views, sync trackers, back up the database |
| **Ctrl + K**, then type **`#`** | **Find work items** — search every customer/type/state (closed included) by title, id, assignee, state, column, description or parent/epic name; **Enter** opens the item's full dialog right where you are |
| **↑ / ↓ · Enter · Esc** | Navigate / run / close inside the palette |
| **Ctrl + R** | Reload the page (F5 is reserved — see Query Editor) |
| **Data Input (nav bar)** | Dropdown menu — opens the Customers / Trackers / Projects / Bonus dialog over the current page |

> Ctrl+K is not available while typing in a text field, and inside the SQL
> editor it belongs to the comment chord below.

## Query Editor

| Shortcut | Action |
|---|---|
| **F5** or **Ctrl + Enter** | Execute the query (Ctrl+Enter works from inside the editor without inserting a newline) |
| **Ctrl + K, Ctrl + C** | Comment the selected lines (`-- `) |
| **Ctrl + K, Ctrl + U** | Uncomment the selected lines |
| **Ctrl + /** | Toggle comment (CodeMirror built-in) |
| **Ctrl + C** | With result-grid rows selected (and focus outside the editor): copy the selected rows as tab-separated text. Otherwise: normal copy of whatever you selected |
| **Ctrl/Shift + Click** | Select rows in the result grid (Edit Mode off) |

## Time Tracker

| Interaction | Action |
|---|---|
| **Click checkbox** | Start / stop a timer (stopping opens the save dialog: comment, ★-recommended tracker item, re-assign project, custom stop time) |
| **Right-click a project row** | **Add time entry** · **Start from past time** · **Manage entries** · **Update project** (rename / default Git-ID) · **Disable project** |
| **Right-click a customer header** | **Update customer** · **Add project** (pre-filled) · **Disable customer** |
| **＋ Add project** (in a card) / **dashed Add-customer card** | Quick-add dialogs, pre-filled where possible |
| **Edit Order: drag a project row** | Reorder within the customer (a light line shows where it lands); arrows still work; the **sort** button orders by the last 60 days of usage |

## Board

| Interaction | Action |
|---|---|
| **Drag a card** | Move it to another column (Azure: board column; Jira: workflow status transition) |
| **Drop on the Done zone** | Mark it Done |
| **Click a card** | Open the full work-item dialog (description, comments, image insert/paste) |
| **Search box** | Filter by title, #id, assignee, state, column, description or parent/epic name; toggle **Incl. done** to search closed items too |

## Notepad

| Shortcut | Action |
|---|---|
| **Esc** | Exit edit mode |
| **Paste an image** | Uploads and embeds it in the note (also works in work-item description editors, where it becomes a tracker attachment) |
| **Drag a note** | Reorder — drop on a note to insert before it (adopting its group), or on a group header to move into that group |
| **Group name with `/`** | Nests sub-groups ("Customer/Project"); collapsing the parent hides the subtree |
