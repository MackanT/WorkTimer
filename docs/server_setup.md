# Server setup — hosted WorkTimer instance

**Status:** in progress · started 2026-09-27
**Context:** first concrete step away from per-user self-hosting toward one
hosted instance. [hosting_decision.md](hosting_decision.md) covers *why*; this
file is the *how*, written as a runbook so the box is reproducible.

> **No secrets in this file.** This repo is public — `update_checker.py` reads
> `raw.githubusercontent.com` without a token. IP addresses, public keys,
> passwords and hostnames stay out on purpose; `<PLACEHOLDERS>` are deliberate.
> Keep the real values in a password manager.

---

## The box

| | |
|---|---|
| Provider | Hetzner Cloud |
| Plan | CX23 — 2 vCPU (Intel), 4 GB RAM, 40 GB NVMe, 20 TB traffic |
| Location | Falkenstein (EU data residency) |
| OS | Ubuntu 26.04 LTS |
| Cost | €5.49/mo + €0.50 IPv4, +25% VAT ≈ **€7.49/mo (~€90/yr)** |

Idle baseline, nothing installed: **~240 MB RAM** (6% of 4 GB), 3.7% of 37 GB
disk. Compare against this when deciding whether 4 GB is enough for ~10 users.

### Buying notes (accurate as of Sept 2026)

- The cheap plans live on the **"Cost-Optimized"** tab (CX / CAX). The "Regular
  Performance" CPX line is 3–4× the price for identical vCPU and RAM — CPX22 was
  €19.49 against CX23's €5.49. Easy trap.
- **CX and CAX are Germany/Finland only.** Select an EU location first or they
  do not appear in the list at all.
- **Stock is scarce.** Through September 2026 CX23 was frequently "sold out".
  The marketing page's availability badges are stale; the console's order flow
  queries live per-datacentre stock. Retry later, or try another DC.
- Because of that scarcity, **never delete the server intending to recreate it.**
  You may not get another for days.
- **Rescale CX23 → CX33** (4 vCPU / 8 GB): power the server off, then choose
  **"CPU and RAM only"** so the disk stays at 40 GB and the change remains
  reversible. The variant that also grows the disk is one-way — disks cannot
  shrink. Either way it needs the target type in stock at that moment.
- Billing is hourly, capped at the monthly rate. **Powering off does not stop
  billing** — only deleting the server does.
- Prices rose twice in 2026 (April, then 15 June); CPX/CCX took +113–173% while
  CX/CAX rose ~35%. Treat any older figures as stale.

---

## SSH access

### Client config (once per machine)

`~/.ssh/config`:

```
Host worktimer
    HostName <SERVER_IP>
    User root
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    # Keeps VS Code Remote-SSH from dropping on idle
    ServerAliveInterval 30
    ServerAliveCountMax 6
    # Browse the server's WorkTimer at http://localhost:18080
    # (not 8080 — that's the local dev instance; 8081 was taken too)
    LocalForward 18080 127.0.0.1:8080
```

A failed `LocalForward` prints a warning but does **not** abort the session —
SSH continues without the tunnel. Pick another local port if it clashes.

### First login and installing the key

Hetzner emails a root password and **forces a password change on first login**,
which `ssh-copy-id` cannot drive. So the order matters:

1. `ssh worktimer` — emailed password, then set a new one. `exit`.
2. `ssh-copy-id -i ~/.ssh/id_ed25519.pub worktimer` — run this **locally**, not
   on the server; it reads the pubkey from your own machine.
3. `ssh worktimer` — should now log in with no password prompt.

Adding an SSH key in the Hetzner console does **not** reach an already-running
server. Account keys are injected at *creation* time only.

### Disabling password authentication — the include-order gotcha

Editing `PasswordAuthentication` in `/etc/ssh/sshd_config` has **no effect** on
Ubuntu cloud images. `sshd_config` begins with
`Include /etc/ssh/sshd_config.d/*.conf`, OpenSSH honours the **first**
occurrence of a setting, and Hetzner's `50-cloud-init.conf` already sets
`PasswordAuthentication yes`. The main file loses.

Add a drop-in that sorts earlier, so it is read first and wins:

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
  > /etc/ssh/sshd_config.d/01-no-password.conf
systemctl restart ssh
sshd -T | grep -iE 'passwordauthentication|kbdinteractive'
```

`sshd -T` prints the *effective* config and is the only thing worth trusting.
`50-cloud-init.conf` will still read `yes` afterwards — that is expected and
harmless. `KbdInteractiveAuthentication no` matters too: without it PAM can
still offer a password prompt by another path.

**Always verify from a second terminal before closing the working session.**

With key-only auth, `fail2ban` adds little — brute force has nothing to guess.

### Authorising another machine

One key per line in `/root/.ssh/authorized_keys`. From a machine that already
has access:

```bash
ssh worktimer 'echo "<PUBKEY_LINE>" >> /root/.ssh/authorized_keys'
```

Use **per-machine keys**, not one key copied around: a lost laptop is then one
line to delete rather than a full rotation. This works at any time — password
auth does not need to be re-enabled to add a key.

### Break-glass

Hetzner's web console (VNC) is out-of-band and still accepts the root password
even with SSH password auth disabled. That is the recovery path if every key is
lost, so keep the root password in a password manager.

---

## VS Code

Install **Remote - SSH** (`ms-vscode-remote.remote-ssh`). It reads the same
`~/.ssh/config`, so `worktimer` appears under *Remote-SSH: Connect to Host* with
no extra configuration. The first connection installs ~200 MB of VS Code Server
on the box.

VS Code Server uses **~150–400 MB of RAM on the remote** with extensions loaded.
Disconnect before measuring the app's own memory, or the numbers are skewed.

---

## Still to do

- [ ] Hetzner Cloud Firewall — inbound port 22 only (once cloudflared is up, the
      app itself needs no inbound ports at all)
- [x] `unattended-upgrades` for security patches — active out of the box
- [x] Docker + Compose — Ubuntu's own packages (`docker.io` 29.1,
      `docker-compose-v2` 2.40, `docker-buildx` 0.30), installed 2026-09-28
- [x] Postgres container + volume — the Phase 5 staging stack in
      `/opt/worktimer` ([staging.md](staging.md)), with daily `pg_dump`s and
      notes/settings archives to `backups-pg/` on the server (14 days, and
      monthly for 12 months)
- [x] Domain — on Cloudflare (2026-09-29). Originally planned: registered at Hetzner (~€4.90/yr; check the **renewal** price,
      cheap TLDs often jump after year one)
- [x] Move the domain's DNS to Cloudflare (bought there, so nothing to move): add it as a site on the Free plan,
      then set Cloudflare's two nameservers at Hetzner. **If DNSSEC is enabled
      at Hetzner, disable it first** — a stale DS record makes the domain
      unresolvable after the switch. Re-enable DNSSEC from Cloudflare once
      the zone is active.
- [x] `cloudflared` named tunnel → the app container (compose profile `hosted`)
- [x] Cloudflare Access application + allow-list policy (by email) — [hosted.md](hosted.md)
  - Zero Trust **Free plan: up to 50 users**, no time limit
  - Login method: **One-time PIN** to start — Cloudflare emails a code, any
    address works, nothing to set up. A Google or Microsoft identity provider
    can be added later to make re-login one click.
  - **Session duration: 1 month** on both the application and the global
    session (default is 24 h; the maximum is one month), so colleagues log in
    roughly monthly.
  - When a session expires with a tab open, NiceGUI's reconnect is redirected
    to the login page and the tab shows "reconnecting" — a reload brings up
    the login. Rare with a one-month session.
- [x] Hetzner Backups — enabled 2026-09-29 (7 daily images of the whole disk)
- [ ] Copy the nightly backups to a PC with `scripts/pull_backups.py` on a
      schedule ([staging.md](staging.md), Backups); object storage later if wanted
- [ ] Non-root admin user (currently root-only, acceptable for a single admin)
