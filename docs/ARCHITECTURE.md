# Architecture and invariants

One process serves a responsive browser interface, a JSON API, and a background synchronization thread. A single SQLite database on a durable local disk is shared by all authenticated users. Browser storage is not used for inventory, queues, credentials or authoritative state. Browser forms wait for server confirmation; there is no offline write queue.

The small Python/SQLite/native-JavaScript stack removes third-party runtime packages. `requirements.lock` is intentionally empty of packages. System Python/OpenSSL/SQLite/timezone data must remain patched; OS/container dependencies are documented separately. The frontend is buildless and uses no CDN assets or external fonts. This is a deliberate alternative to the brief’s suggested React stack, reducing deployment cost and maintenance surface.

## Ownership and identities

| Information | Authority | Identity |
|---|---|---|
| Batch stock and physical movement | This app | batch ID, stock scope, movement/request ID |
| Roast source fields | Roast.World | external `uid` |
| Local notes, holds, overrides, deadlines | This app | batch/order IDs and audit records |
| Orders/payment/confirmed fulfillment | Shopify | GraphQL order/line/variant/fulfillment IDs |
| Physical POS sale | Manual here initially; Square later | future stable source event ID, reconciled cutover |

No Shopify variants are created per roast. No external write is implemented. A refund is not a stock receipt. A missing source roast is not a delete request. An imported historical output is not a present balance.

## Precision and conservation

Weights are integer **milligrams (0.001 g precision)**. Public operations accept decimal gram strings and parse with `Decimal`; fractional milligrams, nonfinite values and excessive magnitudes fail. Yield and safety percentages use basis points. Planner weight rounding uses integer ceiling division. Dates normalize to UTC and display in Asia/Tokyo. Rest uses elapsed durations. Bag counts are whole integers.

`stocks.quantity_mg` means bulk measured content or packaged **nominal net content**. `stocks.overfill_mg` tracks additional measured package content. Physical mass is their sum; nominal stock remains divisible by package weight. Demand and reservations use nominal SKU content; overfill is not promised as extra bags. The UI labels physical on-hand separately from nominal reserved/free content. Bulk has no overfill column balance. On unpacking, nominal plus overfill becomes measured bulk.

Ledger entries hold both nominal changes and overfill changes. Production adds measured output; transfer nets to zero; packing nets only the explicit loss; sale/usage/waste removes actual content. Package overfill is apportioned in integer milligrams over units; remainders remain with the final units. Counts of packages use unit counts and the existing average extra-content amount; perform a separate measured correction if actual contents differ.

`BEGIN IMMEDIATE` serializes the read/validate/write sequence. Every movement posts balance changes and immutable entries in one transaction. DB constraints prevent negative balances and duplicate source/request identities. Reservations are checked under the same lock. A repeated request returns its existing movement; the same key with a different payload fails. Counts compare the stock version before applying a scoped delta. Reversals reference the original, and uniqueness prevents reversal twice.

SQLite triggers prevent UPDATE/DELETE of ledger entries and movements. Projections are inspectable against ledger sums. Direct edits to SQLite bypass application policies and must not be used for routine operations.

## Source imports

Roast.World list pagination traverses documented `page` and `size` only. Interrupted imports retain already committed batches and retry safely. No undocumented incremental filter, private endpoint or scraping is used. Mapping/weight/date exceptions stay queued. Production posts once per UID. Later source differences create issues rather than rewriting physical history. Full-list missing records create review tasks, not deletions. Raw roast/bean source records remain separate from operational notes and policy snapshots.

Shopify is pinned to Admin GraphQL 2026-10. It paginates outer orders and nested line items/fulfillment lines, retrieves latest data with an overlapping `updated_at` watermark, and advances the watermark only after success. Earlier updates cannot overwrite newer records. An order hitting the explicit 250-fulfillment retrieval safety limit stops sync for review, rather than silently truncating. Initial ordinary order access covers the recent permission window; older open orders require additional approved access and a reviewed backfill.

Webhook HMAC is checked against raw bytes before parsing. Only delivery metadata and a payload hash are persisted, not addresses or customer payloads. Duplicate delivery IDs do not enqueue duplicate state changes. The durable pending delivery queue wakes the server’s regular latest-state synchronization. It also works after restart. A successful Shopify sync acknowledges pending deliveries received before that sync began; source timestamps protect against delayed/out-of-order delivery. Periodic polling reconciles even without webhooks.

Retries are bounded; 401/403 errors fail visibly; 429 and transient server failures back off. Numeric Aillio daily quotas are unpublished; tune the poll interval with actual account limits. Unknown exceptions are redacted. All credentials come from server environment variables, not database rows or browser bundles. The app is usable manually if an integration fails.

## Security boundary

Production accounts have scrypt password hashes; server-side session records contain token hashes and separate CSRF secrets. Cookies are HttpOnly, SameSite=Strict, and Secure in hosted configuration. Sessions last 12 hours. Mutations enforce origin/CSRF and server-side roles. Initial admin creation is a local CLI operation and refuses an existing user database. Login attempts are bounded per app-observed connection address (behind a proxy this conservatively limits shared attempts).

Use an HTTPS reverse proxy and expose only it. The app’s lightweight HTTP listener is designed for low-volume internal operations behind that proxy; it is not a general-purpose public web server. Environment files, database files and backups need restricted permissions. No credentials or raw customer payloads are logged. Server request logging is deliberately minimal; monitor the service, disk and backup jobs separately.

## Deliberate limits

- One database and one app process; no clustered/shared-filesystem SQLite or ephemeral serverless disk.
- Simple app-level roles, not SSO, MFA, tenant isolation or per-location permissions.
- One coffee/profile per batch. No blending or cross-batch pooling; use explicit multiple allocations/picks to preserve provenance.
- Bundles stay unresolved until components are explicitly modeled; automatic bundle composition is not supplied.
- Square is a declared adapter boundary, not a live integration. No automatic café dose or retail forecasts.
- English interface; shared labels are organized for localization, but full Japanese translation is not implemented.
- Readable printable batch labels include a direct batch URL. No camera scanner, generated QR code or proprietary printer dependency.
- Shopify shipping-method titles and delivery categories are imported when supplied; missing pickup details and operational deadlines are locally confirmed. Full addresses/payment details are intentionally not collected.
- Configured brand color is a source CSS variable; the wordmark is a placeholder, not a claim about established branding.
