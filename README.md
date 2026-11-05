# Walnuts Roastery

A self-hosted operations app for Walnuts Coffee, Tokyo. It tracks green-bean purchases, receipt prices and expected balances; actual roasted stock by batch, location and form; wholesale and online orders; reservations, rest policies, café usage, physical retail sales and a dated roast plan.

**Status:** implemented and locally exercised with a real shared SQLite database. Includes Shopify and Roast.World adapters, with fixture and local workflow checks. A hosted server/domain has not been provisioned. Credentials, databases, user accounts and real customer/stock records are excluded from this repository.

## Open the isolated demo

Requires Python 3.12+ with SQLite, OpenSSL and system timezone data. There are no third-party Python or JavaScript packages to install and no frontend build step.

On macOS, you can double-click `Start demo.command` and then open the local URL it prints. Keep its terminal open while using the demo. Or, from this folder:

```sh
python3 -m server.app --demo --db data/demo.sqlite --port 8765
```

Open [Walnuts Roastery locally](http://127.0.0.1:8765). The demo sign-in is prefilled (`demo` / `walnuts-demo-only`). Demo mode refuses non-loopback binding and disables live integrations. Its explicit clock is **5 November 2026, 12:00 JST**. Do not use the demo database for production.

Demo changes persist across restarts. To get a fresh example dataset, choose a different database filename; the existing one is not overwritten.

## Start real operations

```sh
python3 -m server.app --db data/production.sqlite --init-admin
python3 -m server.app --db data/production.sqlite
```

The first command prompts privately for a username and a password of at least 12 characters. There is no default production account or public setup endpoint. Create staff accounts in Settings → Access after signing in. Keep this initial setup on loopback until HTTPS is configured.

Before recording real operations:

1. Add your actual coffees/profiles, package sizes and physical locations or containers.
2. Set per-coffee café, dispatch and retail rest policies. Your guidance is 45 days for pour-over and 7 days for espresso café use; the app allows individual bean policies. Dispatch/retail policies remain unconfirmed. Rest means elapsed 24-hour periods, not midnight boundaries.
3. Review freshness windows and fallback yield. These are quality policies and planning assumptions, not food-safety expiry dates or recommendations.
4. Confirm the actual Bullet maximum charge, weekdays and start slots. Working charge defaults to your approximately 1.2 kg; the default slot/schedule is an example. One approved batch occupies one start slot.
5. Follow the physical-count/cutover workflow in [OPERATIONS.md](docs/OPERATIONS.md), then enable imports. Do not count every historical roast as current stock.

## What you own

- `server/domain.py`: inventory rules, fixed-precision weights, rest eligibility and audited operations.
- `server/db.py` and `migrations/`: SQLite persistence and append-only schema migrations.
- `server/imports.py`: idempotent roast/order reconciliation and CSV validation.
- `server/planner.py`: chronological demand coverage, yield, batch rounding and roast slots.
- `server/adapters.py`: server-side API clients, bounded retries and background synchronization.
- `server/app.py` and `server/auth.py`: HTTP endpoints, sessions, roles and signed webhook reception.
- `static/`: responsive interface; navigation/common labels are isolated in `i18n.js` for future localization.
- `tests/`: conservation, concurrency, imports, timing, planner, security, backup and HTTP staff-workflow checks.

The implementation uses Python’s standard library and native browser modules instead of React/TypeScript. This keeps the deployable dependency tree empty and avoids a build toolchain for a small internal app. Business logic remains server-side. It is intended for a few authenticated staff behind an HTTPS reverse proxy, not a general-purpose high-traffic public service.

## Run tests

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js  # optional syntax check; Node is not a runtime requirement
```

The HTTP tests open a temporary loopback port. All tests use disposable databases. See [TEST-REPORT.md](docs/TEST-REPORT.md) for actual verification and limits.

## Deploy, connect and maintain

- [DEPLOYMENT.md](docs/DEPLOYMENT.md): hosted-server choice, HTTPS, accounts, service/container setup, updates and costs.
- [CONNECTIONS.md](docs/CONNECTIONS.md): official API setup, secure environment variables, polling/webhooks, scopes and live verification.
- [OPERATIONS.md](docs/OPERATIONS.md): routine staff actions, rest policies, planning, corrections and reconciliation.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md): precision, ownership, transaction boundaries and supported limitations.

Back up consistently using the SQLite backup API, even while the app is running:

```sh
python3 scripts/backup.py data/production.sqlite backups/production-2026-11-05.sqlite
```

Restore into a **new** path with the app stopped:

```sh
python3 scripts/restore.py backups/production-2026-11-05.sqlite data/restored.sqlite
python3 -m server.app --db data/restored.sqlite
```

Backup/restore refuse to overwrite files; restore clears sessions so users sign in again. Store backups encrypted off the server and test recovery regularly. A ledger JSON export is useful for review but is **not** a full database backup.

## Remaining deployment inputs

A server and domain, actual coffee/SKU mapping and opening counts, confirmed dispatch/retail/freshness rules, actual maximum Bullet capacity and roast start slots, and credentials entered privately into the server environment. No paid AI calls, inventory subscription or paid authentication provider is required. Hosting, backups, electricity/internet and maintenance may still cost money.

Square is the confirmed POS. Automatic Square sales imports, outbound Shopify inventory/fulfillment writes, blend pooling, automatic bundle composition, dose estimates, native scanning and printer integrations are deferred. Manual measured usage, physical sales, returns and counts work now. Multi-batch order fulfillment uses explicit separate allocations/picks; provenance is never pooled away.

## Local live startup (sync fix)

Double-click `Start live.command` to use the existing production database. Startup now loads the project `.env` automatically; exported process variables take precedence. On this Mac, `SSL_CERT_FILE=/etc/ssl/cert.pem` uses the trusted system certificates. The live launcher is for loopback HTTP (`APP_ORIGIN=http://127.0.0.1:8765`, `COOKIE_SECURE=0`); use HTTPS/secure cookies when deploying remotely. Restart after changing credentials. `Start demo.command` remains isolated and does not sync.

## Manual wholesale orders

Refresh Orders and choose **+ New wholesale order**. Enter customer details, coffee/profile, weight per bag, bag quantity, delivery/pickup deadline, payment terms and notes. Drafts stay out of production demand; confirmed orders count even when payment is due by invoice. Allocate/pack as usual and record actual partial or full dispatch. The Channel filter separates Wholesale and Shopify. See OPERATIONS.md for edits, cancellation and stock rules.

## Green beans and purchase prices

Use **Green beans → Add green bean** to enter the bean, currency and optional first
purchase together. Enter kilograms received and either **Price per kg** or
**Total purchase price**; the other calculates automatically. Each receipt keeps
its quantity, cost, supplier, invoice and lot references linked to the bean.
For later arrivals use **Record purchase**. Costs are retained for future margin
reports; sales-margin calculation is not yet implemented.

Link every relevant roast profile to its physical green bean. Actual production
deducts its measured green charge exactly once; multiple profiles can share one
balance. Use **Count stock** for an opening physical balance. Late source imports
dated before a count are already covered by that count. Roast.World source bean
mappings are configured separately under Settings. See OPERATIONS.md for full
count, correction and import-cutover rules.
