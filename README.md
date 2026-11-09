# Walnuts Roastery

A self-hosted operations app for Walnuts Coffee, Tokyo. It tracks actual roasted stock by batch, location and form, with a movement ledger, reservations, use-specific resting policies, café usage, physical retail sales, online allocations and a dated roast plan.

**Status:** implemented and locally exercised with a real shared SQLite database. Shopify and Roast.World adapters are fixture-tested, not connected to your accounts. Production is hosted at https://walnuts-roasting.fly.dev/. No real business stock or credentials are included.

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
node tests/order-view.mjs
node tests/today-view.mjs
node tests/stock-view.mjs
```

The HTTP tests open a temporary loopback port. All tests use disposable databases. See [TEST-REPORT.md](docs/TEST-REPORT.md) for actual verification and limits.

## Today dashboard

Today starts with **Coffee to roast**: one tile per active coffee and roast profile. The main number is net roasted coffee still needed for all open, eligible customer orders, after suitable physical stock **at the Roastery location** is spent once by deadline. Café, retail wall, packing and other locations do not cover customer orders. Bulk grams can be consolidated before packing; existing packed bags must match the ordered size. Overdue orders use stock suitable for dispatch now, while retaining their original deadline alert. Café forecasts and retail targets are excluded; actual reservations for them still protect their stock. Cancelled, archived, fully fulfilled, unpaid/ineligible orders and wholesale drafts are excluded. Coffee profiles stay distinct, and Espresso remains one finished blend.

Click a tile to see each unfulfilled order, remaining bags, due date and net weight to roast. Approved roasts appear as a scheduled portion of work still to roast, never as physical stock. Their supply must be ready by the order deadline. Unapproved suggestions do not reduce the quantity. Green charges and blend ingredient amounts are estimates shown only inside the expansion. Missing mappings and deadlines remain visible for review; undated orders are not presented as a known zero. The previous Upcoming deadlines and Production priorities panels are replaced, while all stock panels remain below.

The bean overview combines roast profiles linked to the same green bean without duplicating its green balance. Green stock below **5 kg** is highlighted red; unlinked profiles show an unknown green balance. **Rested** means physical roasted stock meeting its batch's café policy. **Ready to ship** means packaged net weight at the Roastery location meeting the dispatch policy, including allocated bags. These columns can overlap; both exclude quality holds, archived batches and out-of-policy stock. Café and retail panels show physical quantities per bean, including overfill, with held/archived quantities labelled. Connections and reconciliation remain in Settings.

## Roasted stock and found coffee

Roasted stock shows only balances with physical coffee on hand by default. Fully packed, transferred, sold or consumed stock disappears from that view while its batch and movement history remain intact. Fully reserved stock stays visible. Choose **Balances → Show empty too** to recount an empty scope; positive counts or reversals bring it back automatically. Filters and **Count stock** apply to the same visible scopes.

Use **Add roasted stock** for previously unrecorded coffee. Add it to an existing batch or create a stock-only batch, choose its location and bulk weight or whole-bag quantity, and record a reason. This creates an audited stock adjustment, never a roast or green-bean deduction, and does not change measured roasting yields or complete a roast plan. Enter the original roast date if known. Unknown dates stay unavailable for use/allocation until an administrator reviews the date in batch details. Existing batch policies and holds remain in force.

For a recount of coffee already recorded, use **Count stock** and enter the actual total remaining, rather than adding that total a second time. Counts can increase or decrease stock without affecting green beans; stale counts and reductions below reserved amounts are rejected.

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

Square is the confirmed POS. Outbound Shopify inventory/fulfillment writes, blend pooling, automatic bundle composition, dose estimates, native scanning and printer integrations are deferred. Manual measured usage, physical sales, returns and counts work now. Multi-batch order fulfillment uses explicit separate allocations/picks; provenance is never pooled away.

## Local live startup (sync fix)

Double-click `Start live.command` to open the hosted production app at https://walnuts-roasting.fly.dev/. The old local database is retained as a migration fallback; keep real operations on the hosted site. Startup now loads the project `.env` automatically; exported process variables take precedence. On this Mac, `SSL_CERT_FILE=/etc/ssl/cert.pem` uses the trusted system certificates. The live launcher is for loopback HTTP (`APP_ORIGIN=http://127.0.0.1:8765`, `COOKIE_SECURE=0`); use HTTPS/secure cookies when deploying remotely. Restart after changing credentials. `Start demo.command` remains isolated and does not sync.

## Manual wholesale orders

Refresh Orders and choose **+ New wholesale order**. Enter customer details, coffee/profile, weight per bag, bag quantity, delivery/pickup deadline, payment terms and notes. Drafts stay out of production demand; confirmed orders count even when payment is due by invoice. Allocate/pack as usual and record actual partial or full dispatch. The Channel filter separates Wholesale and Shopify. See OPERATIONS.md for edits, cancellation and stock rules.

## Square retail-wall integration

Add `SQUARE_ACCESS_TOKEN` privately to `.env`, restart, and open **Settings → Products & POS**.
The read-only connection imports Square catalogue variations and completed receipts.
A single active Square shop is selected in preview mode; multiple locations require
an explicit choice. Existing Shopify coffee/package mappings are reused. Review
Square’s name/weight suggestions and link each coffee bag to the shared product.
Use **Exclude selected items** for café drinks and merchandise.

After establishing packed retail-wall opening stock, choose the deduction start
and enable automatic deductions under **Configure shop & start date**. Every
completed sale deducts whole bags from the oldest eligible, unreserved wall batch,
across batches if needed. Duplicate receipts never deduct twice. Unknown mappings,
insufficient stock, refunds and receipts predating counts stay in reconciliation.
See CONNECTIONS.md and OPERATIONS.md for setup and corrections.

## Fly.io production

Production is running at https://walnuts-roasting.fly.dev/ on one always-running
512 MB shared-CPU Machine in Tokyo with a 1 GB encrypted persistent volume. Volume
snapshots retain 14 days; independent migration/backup copies are also kept locally.
The current database and existing login were migrated on 5 November 2026; copied
sessions were cleared. Shopify, Square and Roast.World passed hosted sync checks.
Square remains in Beans-only preview mode until mappings and physical wall stock
are ready. The local production service is stopped and Start live.command opens
the hosted URL. See docs/FLY.md for future deployments, backup and recovery.

## Commitment status colors

Products and point-of-sale configuration are under **Settings → Products & POS**. Old `#products` bookmarks open the new tab.

Order and production cards use solid headers with a written status: green for covered/on-track commitments and fulfilled orders, yellow for missing information or work needing attention, and red for outstanding orders past their dispatch/pickup deadline. Uncovered production also turns red when its roast deadline is missed. Resting coffee and scheduled supply can be on track if ready by the commitment date. Fulfilled orders stay green after their deadline, except when their actual stock pick still needs recording. Cancelled/draft orders and archived orders with remaining items are marked for review rather than treated as overdue commitments. Colors and written statuses are used on Today, Orders and Roast plan.

Customer-order allocations use Roastery stock only. Existing allocations at other locations remain visible as **Allocation outside roastery**, are excluded from order coverage, and can be reviewed/released in Orders. Packing an order allocation defaults to Roastery. Café/retail forecasts still use their physical stock normally. These calculations never move stock between locations.
