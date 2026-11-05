# Integration research — verified 5 November 2026

## Aillio Roast.World

Primary reference: [Aillio Public API](https://api.roast.world/api-docs), inspected through its live rendered Scalar documentation because web text extraction was empty. Version shown: 1.0.0, OpenAPI 3.0.3. Its displayed API-client link identifies `https://api.roast.world/openapi.json` as the specification URL; that JSON was not independently retrieved.

Verified contract:

- Header: `x-api-key`. Resources belong to the token owner.
- GET `/api/v3/public/roasts` and `/api/v3/public/beans`.
- GET `/api/v3/public/roasts/{id}` and `/api/v3/public/beans/{id}`.
- List parameters: `page` integer >=1, default 1; `size` integer 1–100, default 20.
- List envelope: `page`, `size`, `total`, `totalPages`, `data`.
- Roast list examples: `uid`, `roastName`, `preheatTemperature`, `totalRoastTime`, `weightGreen`, `weightRoasted`, `deviceType`, `dateTime`, `firstCrackTime`, `firstCrackTemp`, `beanId`. Some example roasts omit weights and bean association: require review instead of assuming zero.
- Units: temperatures °C; weights grams; total roast time seconds; `dateTime`/detail `updatedAt` epoch milliseconds. Detail measurement arrays have two samples/second.
- Bean list examples use `beanId`, `name`, `country`, `process`, `farm`, `varieties`, `tags`, `inStock` (grams). Bean detail example instead exposes `uid` and adds `region`, `description`.
- Errors include 401, revoked/expired-token 403, detail 404, 429 for daily token/user limits, and 500.

Unknown/unpublished: numeric daily quotas; guaranteed ordering; updated-since filter; webhook support; automatic expiration policy; response headers for retry/reset; required-field schema beyond rendered examples. Do not invent these capabilities. Current reference lists plural paths; older community posts contain singular routes and are obsolete for implementation planning.

Implementation recommendation (our design): server-only adapter, fixed host, authenticated GETs, configurable conservative polling, `totalPages` traversal, upsert on `(connection_id, uid)`, retain original JSON and payload hash. Stage imports before stock posting. Map external `beanId` to a local coffee, and require staff to select the exact green lot before deducting stock. Fetch detail only for changed/new records or explicit inspection. Store integer grams internally; convert to kg only for display. Deduplicate stock posting by roast source ID and local immutable posting revision. Do not equate external bean `inStock` with a second authoritative local ledger.

Do not mark API integration operational until a real token and successful request have been verified. Token generation UI was not inspected in an authenticated account.

## Shopify

### Transport and authentication

[Official Admin GraphQL reference](https://shopify.dev/docs/api/admin-graphql/latest) currently selects **2026-10**. Pin POST `https://{shop}.myshopify.com/admin/api/2026-10/graphql.json`, JSON body `{query,variables}`, `X-Shopify-Access-Token` header. Keep tokens server-side and validate the shop hostname; do not accept arbitrary request destinations.

For an app and store in the same Shopify organization, [client credentials grant](https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant?lang=node) is supported. Token response includes `access_token`, `scope`, `expires_in` (86399 seconds). An app for another merchant needs the appropriate install/OAuth flow; do not assume a client ID/secret alone authorizes every store. No credentials are available in this task, so this remains a setup prerequisite.

### Orders and demand

[Order schema](https://shopify.dev/docs/api/admin-graphql/latest/objects/Order): useful verified fields are `id`, `createdAt`, `updatedAt`, `cancelledAt`, `displayFinancialStatus`, `displayFulfillmentStatus`, `lineItems`, and `fulfillmentOrders`. Requires order read access, normally `read_orders`. Only the last 60 days are accessible by default; older-order access needs approval and `read_all_orders` in addition to appropriate ordinary order scopes.

[Orders query](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders) accepts `first`, `after`, `query`, `sortKey`, `reverse`. `updated_at:>...` is a documented search filter. Use an overlap window around the last successful watermark and upsert by shop+GraphQL ID. Do not advance the watermark until the complete import succeeds.

[LineItem schema](https://shopify.dev/docs/api/admin-graphql/latest/objects/LineItem) verifies `id`, `title`, `sku`, `quantity`, `currentQuantity`, `unfulfilledQuantity`, `variant`, `variantTitle`, `requiresShipping`, and `weight`. `currentQuantity` excludes refunded/removed units. `unfulfilledQuantity` is units not yet fulfilled. `fulfillableQuantity` is deprecated. Keep these distinctions; do not multiply original quantity forever after partial fulfillment/refund. Map variant ID to the local product/package definition, with SKU as a reviewed fallback; a shipping weight is not proof of coffee net weight.

[Pagination](https://shopify.dev/docs/api/usage/pagination-graphql): use cursor connections and pageInfo (`hasNextPage`, `endCursor`). Paginate nested line-item and fulfillment-order connections too; an initial nested page is not the entire order. Fetch small outer pages to avoid multiplying nested query cost.

### Fulfillment writeback

[fulfillmentCreate](https://shopify.dev/docs/api/admin-graphql/latest/mutations/fulfillmentCreate) is the supported mutation. Input includes `lineItemsByFulfillmentOrder` with `fulfillmentOrderId` and selected `fulfillmentOrderLineItems`, plus `notifyCustomer` and optional `trackingInfo`. Fulfillment orders in one call must share order and assigned location. Omitting line items fulfills all remaining items, so the app should always send explicit selected quantities. Check returned `userErrors`; HTTP 200 alone is not success. Needs the matching write fulfillment-order scope and the user's fulfill-and-ship permission.

[FulfillmentOrderLineItem](https://shopify.dev/docs/api/admin-graphql/latest/objects/FulfillmentOrderLineItem) is a separate identity from order LineItem. Read the live fulfillment order and remaining quantities before dispatch, and map selected order lines to those fulfillment-line IDs. For merchant-managed fulfillment, provision `read_merchant_managed_fulfillment_orders` and its write counterpart only when writeback is enabled. Keep local allocation/packing state separate from confirmed external fulfillment state. On ambiguous timeouts, reconcile remotely before retrying to prevent double fulfillment.

### Webhooks and rate limits

[Delivery verification](https://shopify.dev/docs/apps/build/webhooks/verify-deliveries): HMAC-SHA256 the raw request bytes with the app client secret and constant-time compare against decoded `X-Shopify-Hmac-SHA256`. Verify before JSON parsing. Deduplicate deliveries in persistent storage using `X-Shopify-Webhook-Id`. `X-Shopify-Event-Id` correlates multiple subscriptions for the same merchant action; it is not interchangeable with delivery ID. Enqueue durably, acknowledge quickly, process idempotently, and periodically reconcile source records.

[Topic reference](https://shopify.dev/docs/api/admin-graphql/latest/enums/WebhookSubscriptionTopic) is the authoritative enum catalog. Proposed subscriptions: order creation/update/cancellation, refunds, and fulfillment creation/update; verify exact selected topic names during registration against this pinned version. This research did not create registrations.

[GraphQL rate limits](https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits): cost-based, separately per app/store. Documented restore rates: Standard 100, Advanced 200, Plus 1000, Enterprise 2000 points/sec. Read response cost/throttle metadata dynamically and back off on throttling. Do not model this as a fixed requests-per-second quota.

## Proposed local persistence (design, not vendor schema)

`integration_connections`: provider, shop/account identity, encrypted secret reference, API version, connection state, last successful sync, last error (redacted).

`sync_runs`: connection, trigger, status, started/completed, watermark, processed/created/updated/rejected counts; `sync_errors`: run, external ID, safe error, retry eligibility.

`external_roasts`: connection+external UID unique, source time, weights, bean ID, raw JSON, payload hash, mapping/review status, local roast ID; `external_orders` and `external_order_lines`: source IDs, update timestamp, current/unfulfilled quantities, mapped product, raw snapshots.

`webhook_deliveries`: connection+delivery ID unique, topic, payload hash, processing state; `fulfillment_outbox`: local idempotency key, explicit line IDs/quantities, pending/sending/confirmed/reconciliation_required/failed state, external fulfillment ID, redacted errors.

Read-only sync can be shipped before fulfillment writeback. All connected/last-sync counters must describe observed results; demo/sample mode must be explicitly labeled.
