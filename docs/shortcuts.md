# Keyboard shortcuts & quick interactions

## Everywhere

| Shortcut | Action |
|---|---|
| **Ctrl + K** | Open the **command palette** — jump to pages, start/stop timers, add work items, switch board views, sync DevOps, back up the database |
| **Ctrl + K**, then type **`#`** | **Find work items** — search every customer/type/state (closed included) by title, id, assignee, state, column or parent/epic name; **Enter** opens the item's full dialog right where you are |
| **↑ / ↓ · Enter · Esc** | Navigate / run / close inside the palette |
| **Ctrl + R** | Reload the page (F5 is reserved — see Query Editor) |

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
| **Click checkbox** | Start / stop a timer (stopping opens the save dialog: comment, ★-recommended DevOps item, re-assign project, custom stop time) |
| **Right-click a project row** | **Add time entry** · **Start from past time** · **Manage entries** (edit/delete individual entries in the selected range) |

## Board

| Interaction | Action |
|---|---|
| **Drag a card** | Move it to another column (synced to Azure DevOps) |
| **Drop on the Done zone** | Mark it Done |
| **Click a card** | Open the full work-item dialog (description, comments, attachments) |
| **Search box** | Filter by title, #id, assignee, state, column or parent/epic name; toggle **Incl. done** to search closed items too |

## Notepad

| Shortcut | Action |
|---|---|
| **Esc** | Exit edit mode |
| **Paste an image** | Uploads and embeds it in the note (also works in DevOps description editors, where it uploads as a work-item attachment) |
