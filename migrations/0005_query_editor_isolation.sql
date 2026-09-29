-- v6 Phase 6 security review: what one query-editor user can learn of, or
-- do to, the others. Every user's editor queries run as worktimer_readonly on
-- one shared pool, so:
--
-- * Other sessions' running queries (pg_stat_activity shows a role's own
--   sessions in full — and all users share that role), a connection's
--   prepared statements and per-table statistics are closed to everyone but
--   the admin, in this database.
-- * Its sorts and hashes get a small working memory and its temp files a
--   cap, so one query can't exhaust the server's memory or disk.

revoke select on pg_catalog.pg_stat_activity from public;
revoke execute on function pg_catalog.pg_stat_get_activity(integer) from public;
revoke select on pg_catalog.pg_prepared_statements from public;
revoke execute on function pg_catalog.pg_prepared_statement() from public;
revoke select on pg_catalog.pg_stat_all_tables, pg_catalog.pg_stat_user_tables,
                 pg_catalog.pg_stat_xact_all_tables, pg_catalog.pg_stat_xact_user_tables,
                 pg_catalog.pg_statio_all_tables, pg_catalog.pg_statio_user_tables
    from public;

do $$
begin
    execute format('alter role worktimer_readonly in database %I set work_mem = %L',
                   current_database(), '16MB');
    execute format('alter role worktimer_readonly in database %I set temp_file_limit = %L',
                   current_database(), '512MB');
end
$$;
