-- v6 Phase 6: sign-in (docs/v6_plan.md §2).
--
-- In hosted mode the user comes from a verified Cloudflare Access identity:
-- users.bk_user holds its subject (`sub`), and a first sign-in creates the
-- user. Row-level security shows the app role only the user it is acting as,
-- and it may not insert users — so one function finds or creates the user and
-- returns the key the connection layer then acts as.
--
-- The function runs as a role of its own, worktimer_signin: NOLOGIN, nobody's
-- member, allowed only users' rows — so no everyday role, the owner included,
-- ever sees another user without app.user_id (every table still fails
-- closed). Only the app role may call it; the query editor's role may not.
-- 'local' is the single-user install's user and never a sign-in.

do $$
begin
    if not exists (select from pg_roles where rolname = 'worktimer_signin') then
        create role worktimer_signin nologin;
    end if;
    if exists (select from pg_roles where rolname = 'worktimer_signin'
               and (rolsuper or rolbypassrls or rolcanlogin)) then
        raise exception 'worktimer_signin must not log in, be a superuser or bypass row-level security';
    end if;
end
$$;

grant usage on schema public to worktimer_signin;
grant select, insert, update (email) on users to worktimer_signin;
create policy sign_in on users to worktimer_signin using (true) with check (true);

create function app_sign_in(p_bk_user text, p_email text, p_display_name text)
    returns integer
    language plpgsql
    security definer
    set search_path = pg_catalog, public
    as $$
declare
    k integer;
    enabled boolean;
begin
    if coalesce(btrim(p_bk_user), '') = '' or p_bk_user = 'local' then
        raise exception 'a sign-in needs an identity' using errcode = 'invalid_parameter_value';
    end if;
    insert into users (bk_user, email, display_name)
    values (p_bk_user, p_email, p_display_name)
    on conflict (bk_user) do nothing;
    update users set email = p_email
    where bk_user = p_bk_user and p_email is not null and email is distinct from p_email;
    select key_user, is_enabled into strict k, enabled from users where bk_user = p_bk_user;
    if not enabled then
        raise exception 'user % is disabled', k using errcode = 'insufficient_privilege';
    end if;
    return k;
end
$$;

-- How many users have signed in (everyone but 'local'): a single-user start
-- refuses a database that has them (§2 — multi-user can't be turned off).
create function app_signed_in_users() returns integer
    language sql stable
    security definer
    set search_path = pg_catalog, public
    as $$ select count(*)::integer from users where bk_user <> 'local' $$;

alter function app_sign_in(text, text, text) owner to worktimer_signin;
alter function app_signed_in_users() owner to worktimer_signin;
revoke execute on function app_sign_in(text, text, text), app_signed_in_users() from public;
grant execute on function app_sign_in(text, text, text), app_signed_in_users() to worktimer_app;
