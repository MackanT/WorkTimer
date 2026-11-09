-- Several tracker projects per customer (Azure DevOps, one org): a customer
-- keeps its main project (customers.tracker_project) and may link more; each
-- cached work item records the project it lives in, so the Board can show one
-- tab per project and per-item calls reach the right one. The tables' grants
-- cover the new columns.

set local role worktimer_owner;

alter table customers add column extra_tracker_projects text[] not null default '{}';

alter table work_items add column tracker_project text;

reset role;
