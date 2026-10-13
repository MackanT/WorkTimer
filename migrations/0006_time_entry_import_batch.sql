-- The Excel import: time pasted from a spreadsheet lands as ordinary time
-- entries, each carrying its import's id, so a whole import can be undone in
-- one step. NULL for every entry not made by an import. The table's grants
-- cover the new column.

set local role worktimer_owner;

alter table time_entries add column import_batch uuid;

create index time_entries_by_import on time_entries (fk_user, import_batch)
    where import_batch is not null;

reset role;
