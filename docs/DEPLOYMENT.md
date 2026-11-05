# Hosted deployment and recovery

## Chosen arrangement

You requested access away from the shop, so the target is **one small hosted Linux server** with durable local storage, HTTPS, a continuously running app process and offsite backups. No provider or server account was supplied, so no server has been rented, no domain/DNS changed and no production URL published.

An always-on café computer is cheaper if already owned and can poll Shopify/Roast.World without exposing inbound webhooks. It depends on shop power/internet and normally limits access to the local network (or an independently configured VPN). A hosted server simplifies away-from-shop access and signed webhook reception, at the cost of server rental and maintenance. Both still need backups and OS updates. There is no promise of permanent free hosting.

The Sites hosting runtime available during development is a Cloudflare Worker environment; it cannot run this Python process with a persistent local SQLite file and its scheduler. Publishing only the interface there would not be a functioning shared operations app. The full source, migrations, working local database and server deployment files are preserved instead.

## Native Linux service (smallest runtime)

Use a maintained Linux distribution, patched Python 3.12+, SQLite/OpenSSL support, system timezone data and Caddy installed from its official package channel. Run as an unprivileged `walnuts` service user. The example paths are `/opt/walnuts-roastery` for source and `/var/lib/walnuts` for durable data; create and assign those directories to that user.

1. Copy the source folder to `/opt/walnuts-roastery`. It needs no pip/npm install.
2. Create `/etc/walnuts.env` from `.env.example`. Set the actual `APP_ORIGIN=https://your-domain` and `COOKIE_SECURE=1`. Restrict this file to the service administrator (`0600`). Do not put secrets in shell arguments, Git or chat.
3. As the service user, from the source directory, initialize the administrator privately:

   ```sh
   python3 -m server.app --db /var/lib/walnuts/production.sqlite --init-admin
   ```

4. Install `deploy/walnuts.service` into the systemd service directory. It binds the app only to `127.0.0.1:8765`. Enable and start the service.
5. Point your domain to the server. Adapt `deploy/Caddyfile` for that domain. Caddy forwards HTTPS to the loopback app. Expose only HTTPS/HTTP for certificate handling and restricted administration ports; never expose port 8765 directly.
6. Open the HTTPS URL, sign in, confirm the secure cookie and start with real settings/opening counts. Set server-side integration variables only after reviewing cutover.
7. Install the backup service/timer, make an initial backup and restore it into a new test path before depending on the app.

Caddy reverse-proxy syntax is based on its [official reference](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). Certificate issuance requires a real reachable domain and correct DNS. Deployment files were prepared but were not installed on a remote server during this build.

## Optional Docker Compose

The container runs the same app as UID 10001, with a persistent named volume at `/data`. It has no host-published app port; only Caddy publishes ports 80 and 443. The service count must stay at one.

```sh
cp .env.example .env
# Edit .env privately: real APP_DOMAIN, APP_ORIGIN and COOKIE_SECURE=1.
docker compose build
docker compose run --rm -it app python -m server.app --db /data/production.sqlite --init-admin
docker compose up -d
```

Do not run `docker compose down -v` unless you intentionally want to remove persistent volumes. Ordinary rebuild/restart keeps the database. Container recipes are supplied; a Docker daemon was not available/used for a deployment verification in this task. The Python image is constrained to 3.12 but intentionally receives patched image updates; pin your chosen tested image digest in your deployment system if bit-for-bit container reproducibility is required. There are no unlocked application-package dependencies.

## Environment reference

| Variable | Purpose |
|---|---|
| `DATABASE_PATH` | Optional default SQLite path; command-line `--db` takes precedence. |
| `APP_ORIGIN` | Exact hosted HTTPS origin, without a trailing slash. |
| `COOKIE_SECURE` | Set `1` on HTTPS; leave `0` only for loopback demo/development. |
| `APP_DOMAIN` | Compose/Caddy hostname, e.g. your actual roastery subdomain. |
| `ROASTWORLD_API_KEY` | Official Aillio public API key; server only. |
| `SHOPIFY_SHOP` | Canonical `shop-name.myshopify.com`, without protocol/path. |
| `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` | Same-organization app client-credentials flow, where eligible. |
| `SHOPIFY_ACCESS_TOKEN` | Alternative installed-app Admin API token; takes precedence over client credentials. |
| `SHOPIFY_WEBHOOK_SECRET` | App secret used to verify Shopify webhook HMAC; omit to disable reception. |

The app loads the project `.env` automatically at startup, preserving variables already exported by the process. Systemd can also load `EnvironmentFile`; Compose loads `env_file`. Keep credentials in a private environment file or secret manager. An OAuth access token supplied directly must be renewed according to its actual authentication scheme. Client-credentials mode exchanges for a token at each synchronization run.

## Backups, restore and updates

The included backup script uses [SQLite’s online backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup), which creates a consistent snapshot while other clients can use the source. It runs an integrity check and sets file mode 0600. Do not replace this with a plain live file copy; WAL files can contain committed data.

Daily schedule example: the supplied systemd timer runs at 03:00 Asia/Tokyo and catches up after downtime. Its local backup is only the first copy. Configure encrypted offsite storage and a retention policy appropriate for the business. Check backup failures and available disk space; do not rely on files kept only beside the live database.

For Compose, run the script inside the app container with a separately mounted backup destination, or arrange the same consistent backup API through a maintenance container. Do not copy only the live `.sqlite` file from a running volume.

Restore procedure:

1. Stop the app; keep the old database untouched.
2. Run `scripts/restore.py` with the backup and a new destination path. It verifies the snapshot and invalidates restored sessions.
3. Point the service’s `--db` to that restored path, preserving restricted ownership/permissions.
4. Start once; append-only migrations apply automatically. Check total physical stock, reservations, recent movement history and unresolved issues before resuming.
5. Record the recovery time and any operations after the backup that need reconstruction. Do not run live sync in the isolated restore test.

For an update: make a backup, stop the service, replace source with a tested version, start the service once, run a small smoke check and verify sync. Applied migrations are immutable; add a new migration to change the schema. If rollback requires an older schema, restore the matching pre-update backup rather than deleting migration history.

## Costs and remaining activation

No paid AI, roasting platform or paid authentication provider is required. Budget for hosted compute/disk, offsite backups, a domain if needed, internet and maintenance time. No specific provider price or free-tier entitlement is assumed.

Activation still needs: an actual server/domain and secure access for deployment, a private first-admin password, real coffee/package mappings, initial counts, confirmed max charge and slots, and integration credentials. Only after actual API reads, sample reconciliation and a real backup/restore should the live connections be marked verified.
