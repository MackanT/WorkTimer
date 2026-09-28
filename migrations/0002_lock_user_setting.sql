-- The query editor runs users' own SELECTs (v6 Phase 3). Row-level security
-- compares every row with app.user_id — a setting any role may change with
-- set_config(), even inside a SELECT, which would switch the transaction to
-- another user. So no role may call it; the connection layer sets the user
-- with SET LOCAL, which a single SELECT cannot issue. (Superusers keep it.)
--
-- The other way to reach set_config is pg_settings, whose update rule calls
-- it. The revoke above already refuses that (the call is checked for the
-- caller), the query editor's READ ONLY transactions refuse it too, and a
-- data-modifying WITH doesn't run the rule — but nothing needs to update
-- pg_settings, so that route is closed outright as well.

revoke execute on function pg_catalog.set_config(text, text, boolean) from public;
revoke update on pg_catalog.pg_settings from public;
