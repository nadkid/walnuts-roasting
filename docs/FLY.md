# Fly.io hosting

`fly.toml` configures one shared-CPU Machine with 512 MB RAM in Tokyo (`nrt`),
a 1 GB `walnuts_data` volume mounted at `/data`, HTTPS and secure session cookies.
The Machine stays running for background imports even when no browser is open.
Fly.io usage is billed to your account. The app name in `fly.toml` is a proposed
name; confirm availability and update both `app` and `APP_ORIGIN` together.

Keep exactly one Machine/volume for this single-writer SQLite deployment. Volumes
are not replicated. Do not enable HA/multiple Machines without implementing data
replication first. Fly snapshots supplement backups; retain independent encrypted
SQLite backups off Fly as well. Provider secrets and databases are excluded from
the Docker build and Git repository.

## Initial deployment

1. Authenticate the official Fly CLI and choose the intended organization.
2. Create the app and its volume in Tokyo:

   ```sh
   fly apps create walnuts-roasting --org YOUR_ORG
   fly volumes create walnuts_data --app walnuts-roasting --region nrt --size 1
   fly deploy --remote-only --ha=false
   ```

3. The initial app has no users or provider credentials. Before migrating, stop the
   local production server so it cannot diverge from the hosted inventory. Create
   a fresh snapshot with the supplied SQLite backup script. Upload only that
   snapshot to `/data/incoming.sqlite` using `fly ssh sftp`.
4. In the hosted machine, run:

   ```sh
   fly ssh console --app walnuts-roasting -C 'python /app/scripts/fly_restore_initial.py /data/incoming.sqlite /data/production.sqlite'
   ```

   The restore refuses an existing operational database or configured provider
   credentials, checks integrity, and clears copied login sessions. Current app
   database migrations have already run on the blank destination; the migration
   snapshot must be made with the same current source/schema.
5. Import only the provider settings securely from the live folder:

   ```sh
   python3 scripts/fly_secrets.py --fly /path/to/flyctl --app walnuts-roasting
   ```

   Values go through stdin to Fly secrets, never command arguments or a source
   file. Local `SSL_CERT_FILE`, HTTP origin, cookie and database paths are not
   copied: the container uses its own trusted certificates and hosted settings.
6. Keep one Machine (`fly scale count 1`), verify health and record counts, then
   sign in at the configured HTTPS URL with the existing account. Confirm Square
   Beans scope, preview/automatic mode, and the Roast.World import start. Do not
   continue logging operations in the old local database after cutover.
7. Remove the incoming snapshot after verification. Configure independent backups
   and test retrieval/restore. The persistent volume protects data across normal
   deployments but is not an independent backup.

The image startup prepares mounted directory ownership then drops to the existing
non-root app user. Migrations run on the attached database at app startup; no Fly
release command is used because release Machines do not mount the app volume.
Subsequent source-only deployments preserve `/data/production.sqlite`.

## Backup retrieval

Run `/app/scripts/backup.py` through `fly ssh console` into a new path on the
volume, then download that consistent snapshot using Fly SFTP to encrypted offsite
storage. Keep the old local database and the pre-migration snapshot until the
hosted counts have been verified. Credentials remain in Fly secrets, not backups
of the source tree.

## Verified production deployment — 5 November 2026

- URL: https://walnuts-roasting.fly.dev/
- App: `walnuts-roasting`; organization: personal / Walnuts Coffee.
- Machine: `80e447b613de48`; region `nrt`; one shared CPU, 512 MB RAM.
- Persistent volume: `walnuts_data`, 1 GB encrypted; snapshot retention 14 days.
- Database transfer checksum and all 33 table counts matched before integrations
  were enabled; account retained and sessions cleared; integrity checks passed.
- Hosted Shopify, Square and Roast.World imports succeeded. Square Beans category
  and preview mode, plus the 5 November JST roast-import start, were preserved.
- HTTPS readiness passed; unauthenticated stock API returned 401.
- Local production server stopped; its launcher now opens the hosted site.

The app is deployed from this live source folder using the official Fly CLI; a
GitHub-triggered deployment pipeline is not configured.
