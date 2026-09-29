# Hosted — WorkTimer online behind Cloudflare Access

**What it is:** the server's WorkTimer at `https://worktimer.<your domain>`,
reachable from any browser. Everyone signs in through Cloudflare Access (an
emailed one-time code) and sees only their own data. The server opens nothing
new: `cloudflared` connects *out* to Cloudflare, and the app still verifies
every request's Access token itself ([src/auth.py](../src/auth.py)).

**Before:** the server set up and running per [staging.md](staging.md).

> **No secrets in this file** (the repo is public). The tunnel token and the
> Access values go only into the server's root-only `/opt/worktimer/.env`.

Cloudflare's dashboard moves things around now and then; the names below may
differ slightly.

---

## 1. A domain on Cloudflare (once)

Simplest: buy it at Cloudflare — dash.cloudflare.com → *Domain Registration →
Register Domains*. At-cost prices, and its DNS is already on Cloudflare, so
there is nothing to move. (Not every TLD is sold there — `.se` isn't; `.com`,
`.dev`, `.app` and many others are.)

Bought elsewhere: add it to Cloudflare as a site on the Free plan and set
Cloudflare's two nameservers at the registrar — **disable DNSSEC at the
registrar first** ([server_setup.md](server_setup.md)).

## 2. A Zero Trust team (once)

dash.cloudflare.com → *Zero Trust*. Pick a team name — it becomes
`https://<team>.cloudflareaccess.com`, the **team domain** (note it) — and
the **Free** plan (up to 50 users; it may ask for a card, nothing is charged).

Under *Settings → Authentication → Login methods*, check that **One-time PIN**
is there (it is by default): Cloudflare emails a code, any address works.

## 3. The tunnel

*Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared*, name it
`worktimer`.

- On the install page, copy the **token** — the long `eyJ…` string in the
  install command. Don't run that command; the server runs `cloudflared` in
  Docker.
- *Public hostname*: subdomain `worktimer`, your domain, service **HTTP**,
  URL **`worktimer-pg:8080`** (the app's name inside the server's Docker
  network). Save.

## 4. The login: an Access application

*Zero Trust → Access → Applications → Add an application → Self-hosted*:

- Name `WorkTimer`, hostname `worktimer.<your domain>`.
- **Session duration: 15 minutes for the first test** (to see a login expire),
  then **1 month**.
- Login method: One-time PIN.
- Policy: name `People`, action **Allow**, include **Emails**: your address,
  plus a second one of yours for the test.

Save, open the application, and copy its **Application Audience (AUD) Tag**
from the overview.

## 5. The server

```bash
ssh worktimer
cd /opt/worktimer && git pull
nano .env        # add the five lines below, with your values
scripts/staging.sh up
```

```
CLOUDFLARE_TUNNEL_TOKEN=<the token from step 3>
WORKTIMER_AUTH=cloudflare-access
CF_ACCESS_TEAM_DOMAIN=https://<team>.cloudflareaccess.com
CF_ACCESS_AUD=<the AUD tag from step 4>
WORKTIMER_OWNER_EMAIL=<your email — exactly the one you sign in with>
```

With a tunnel token in `.env`, `staging.sh up` starts `cloudflared` too.

**`WORKTIMER_OWNER_EMAIL` matters:** your data is the single-user install's
(user 1). The first sign-in with that email takes it over, once; any other
address gets an empty WorkTimer of its own. Set it *before* you first sign
in.

## 6. First sign-in, and the two-person test

1. Open `https://worktimer.<your domain>` → Cloudflare's login → your email →
   the emailed code → **WorkTimer with your data**.
2. In a private window, sign in with the second address → an **empty**
   WorkTimer. Add a customer there; back in the first window it must not
   appear, and the second window must show none of your customers, board,
   notes or settings.
3. After 15 minutes, a tab left open shows "reconnecting"; a reload brings
   up the login. Then set the session to 1 month.

## After

- The SSH tunnel (`http://localhost:18080`) now shows "Not signed in" — use
  the domain. Single-user mode can't come back on this database: a
  single-user start refuses it once people have signed in.
- **Colleagues:** add their email to the policy. Each imports their own 5.x
  database through *Settings → Import* (their notes aren't part of that yet).
- **When something is off:** `docker compose --profile postgres --profile hosted
  logs cloudflared` shows the tunnel; the app's log (`… logs worktimer-pg`)
  says why a page was refused ("no valid sign-in: …" — typically a wrong
  `CF_ACCESS_AUD` or team domain).
