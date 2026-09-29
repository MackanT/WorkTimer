-- v6 Phase 6: the owner's first sign-in takes over the single-user data.
--
-- A single-user install's data belongs to user 1, 'local'. When the install
-- goes online (docs/hosted.md), its owner's first Cloudflare Access sign-in
-- must land in that data, not in a new empty account. So app_sign_in gains a
-- fourth argument: with p_claim_local — the app passes it only for the
-- configured owner's verified email — an identity that has no user yet takes
-- over user 1 while that is still 'local'. Once taken, 'local' is gone and
-- the flag does nothing more; single-user mode then refuses the database
-- (app_signed_in_users counts the owner), as §2 wants.

drop function app_sign_in(text, text, text);

grant update (bk_user, display_name) on users to worktimer_signin;

create function app_sign_in(p_bk_user text, p_email text, p_display_name text,
                            p_claim_local boolean default false)
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
    if p_claim_local and not exists (select from users where bk_user = p_bk_user) then
        update users
        set bk_user = p_bk_user,
            email = coalesce(p_email, email),
            display_name = coalesce(p_display_name, display_name)
        where key_user = 1 and bk_user = 'local';
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

alter function app_sign_in(text, text, text, boolean) owner to worktimer_signin;
revoke execute on function app_sign_in(text, text, text, boolean) from public;
grant execute on function app_sign_in(text, text, text, boolean) to worktimer_app;
