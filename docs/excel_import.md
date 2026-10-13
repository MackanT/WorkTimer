# Import time from Excel

Bring the time report you keep in Excel into WorkTimer by **copying and
pasting** — no template to fill in, no file to upload. Your customers and
projects are created as part of it.

**Where:** [Settings → Data → Import time from Excel](/settings?tab=data)
(on the hosted WorkTimer).

---

## What your sheet needs

- **One row per piece of work**, with at least a **date**, a **customer** and
  **hours** — or a **start and end time** instead of hours.
- A **project** and a **comment** are optional. Without a project column,
  each customer gets one project, *General*.
- Your own column order and headers are fine: WorkTimer guesses which column
  is which, and you can correct it. Extra columns (week number, totals …) can
  stay.

## Step by step

1. **Copy from Excel.** Select your table **including its header row** — click
   the top-left cell, then **Ctrl + Shift + End** — and copy it (**Ctrl + C**).
2. **Paste in WorkTimer.** In *Settings → Data → Import time from Excel*,
   click the box and paste (**Ctrl + V**).
3. **Check the columns.** The first rows are shown, with a dropdown above each
   column showing what WorkTimer thinks it is. Change any that's wrong, and
   pick *— ignore —* for columns you don't need. If your selection has no
   header row, untick *The first row is a header*.
4. **Check the customers.** The table lists every customer in your sheet:
   entries, hours, period and projects (new ones marked), and whether it is
   new or already in WorkTimer. For each **new** customer:
   - type its **hourly rate** — it applies from the customer's first
     imported day;
   - untick **Active** for customers you no longer work for. They are created
     disabled — out of the Time Tracker — but their time still counts in
     Reports. It starts ticked for customers with time in the last 90 days.
5. **Press _Import N entries_.** Done: your customers, projects and time are
   in WorkTimer.

## What WorkTimer recognises

| Column | Headers it knows (Swedish or English) | Values it reads |
|---|---|---|
| Date | Datum, Dag, Date, Day | `2026-03-02`, `2026/3/2`, `02.03.2026`, `2/3/26` |
| Customer | Kund, Klient, Uppdragsgivare, Företag, Customer, Client, Company | any text |
| Project | Projekt, Uppdrag, Project, Assignment | any text |
| Hours | Timmar, Tid, Hours, Time, Duration | `7,5` · `7.5` · `7:30` · `7 h` |
| Start / End | Start, Från, From / Slut, Till, End, To | `08:00`, `8.30` |
| Comment | Kommentar, Beskrivning, Notering, Aktivitet, Comment, Description, Task | any text |

Without recognisable headers, the content decides: dates, numbers, times of
day, short repeated text (customers, projects) and varied text (comments).

Dates like `03/02/2026` are read **day first**, as in Sweden — unless a value
in the column only makes sense month first (`03/15/2026`).

## Good to know

- **Nothing is saved until you press Import.**
- **Rows to fix:** a row with a bad date, no customer, hours that can't be
  read, more than 24 hours, or an end before its start is listed with its row
  number — and Import waits until it is fixed. Fix it in Excel, then copy and
  paste again.
- **Rows without time** (empty or 0 hours) are skipped.
- **Names:** customers and projects match the ones you already have, whatever
  their capital letters or spacing; the rest are created. A name written in
  several ways in your sheet is created once, as first written.
- **Times of day:** rows with only hours are placed on their day from 08:00,
  one after another. Only the Time Tracker shows those times — Reports count
  the hours.
- **Pasting again is safe:** entries already in WorkTimer (same customer,
  project, day, hours and comment) are skipped. Paste a longer sheet later and
  only its new rows are added.
- **Rates later:** a rate left empty is 0. Set it under *Customers → Update*,
  from the customer's first day — that re-prices the imported time.
- **Undo:** under *Earlier imports*, **Undo** removes every entry of that
  import at once. The customers and projects it created stay; disable them
  under *Customers* if you don't need them.
- **Size:** up to 20 000 rows per paste — import a longer history in parts,
  e.g. a year at a time.
- **Not supported yet:** sheets with the days as columns (a weekly grid).

---

Ready? [Go to Settings → Data](/settings?tab=data)
