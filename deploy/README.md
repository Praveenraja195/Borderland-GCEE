# Deploying to a Google Compute Engine VM

One VM runs everything: Caddy (HTTPS reverse proxy) → API (+ both web apps)
→ Postgres + Redis, plus the scheduler worker. Defined in
`docker-compose.prod.yml`; `deploy/setup-gcp-vm.sh` does the whole install.

## 1. Create the VM

Compute Engine → Create instance:

- **e2-small** (2 vCPU / 2 GB) is plenty for one event; e2-medium if you
  expect 100+ phones.
- Boot disk: **Debian 12** or **Ubuntu 22.04 LTS**, 20 GB.
- Firewall: tick **Allow HTTP traffic** and **Allow HTTPS traffic**.
- (Optional) reserve a **static external IP** so the address never changes.

## 2. Put the project on the VM and run the setup

SSH in (the "SSH" button in the console works), then:

```bash
git clone <your repo url> borderland && cd borderland
sudo bash deploy/setup-gcp-vm.sh
```

or copy the folder up with `gcloud compute scp --recurse` / `scp` and run the
same command inside it. The script installs Docker, writes a `.env` with
generated secrets (JWT, DB password, admin password), builds the image,
starts the stack, waits for it to be healthy, installs a daily DB backup,
and prints the URLs and the admin login.

With **HTTPS** (recommended — the "Add to Home Screen" full-screen mode on
Android needs it): point a hostname at the VM's external IP (a free
[DuckDNS](https://www.duckdns.org) name is fine) and run

```bash
sudo DOMAIN=your-name.duckdns.org bash deploy/setup-gcp-vm.sh
```

Caddy obtains and renews the certificate automatically. Without `DOMAIN`
the site is served over plain HTTP on the VM's IP.

## 3. Use it

- Team app: `https://<host>/team-app/`
- Admin app: `https://<host>/admin-app/` — user `admin`, password is
  `ADMIN_PASSWORD` in `.env` on the VM (the account is created on the first
  start only; change it afterwards from Admin Accounts).

## Everyday operations (run inside the project folder on the VM)

| Task | Command |
|---|---|
| Status | `docker compose -f docker-compose.prod.yml ps` |
| Live API log | `docker compose -f docker-compose.prod.yml logs -f api` |
| Restart | `docker compose -f docker-compose.prod.yml restart` |
| Deploy an update | `git pull && sudo bash deploy/setup-gcp-vm.sh` |
| Backup now | `./deploy/backup-db.sh` (daily at 03:15 automatically, 14 kept) |
| Restore | see the comment at the top of `deploy/backup-db.sh` |
| Change the hostname | `sudo DOMAIN=new.host bash deploy/setup-gcp-vm.sh` |

## What the production stack changes vs. development

- Only Caddy is reachable from outside (80/443). Postgres, Redis and the
  API port are internal to the Docker network.
- Code is baked into the image; rebuild (`setup-gcp-vm.sh`) to deploy.
- Secrets come from `.env` (never commit it). The app refuses to start in
  production with a placeholder `JWT_SECRET`.
- A failed database migration stops the container instead of starting a
  broken app; the health check (`/api/v1/health`) verifies DB + Redis.
- Redis persists to disk (it holds the scheduled sub-round close jobs).
- Interactive API docs (`/docs`) are disabled.
- Container logs are size-capped; everything restarts on reboot.

`docker-compose.yml` (no `.prod`) remains the local development stack and
must not be used on the VM: it exposes the database with a fixed password.
