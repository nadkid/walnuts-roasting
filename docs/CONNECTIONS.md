# Connecting the external systems

Documentation was checked on **5 November 2026**. No live account credentials were provided. The clients and reconciliation logic have been tested against representative documented fixtures, not your store or roaster account. Keep the status distinction visible until a real successful sync and sample reconciliation have occurred.

## Roast.World / RoasTime

Official references: [RoasTime](https://aillio.com/app/roastime), [Roast.World](https://aillio.com/app/roast-world), [Aillio Public API](https://api.roast.world/api-docs).

The currently documented API uses `x-api-key` and plural endpoints:

```text
GET https://api.roast.world/api/v3/public/roasts?page=1&size=100
GET https://api.roast.world/api/v3/public/beans?page=1&size=100
GET https://api.roast.world/api/v3/public/roasts/{id}
GET https://api.roast.world/api/v3/public/beans/{id}
```

The list response has `page`, `size`, `total`, `totalPages`, `data`. Documented units are grams for weights and epoch milliseconds for roast timestamps. Old singular-path examples must not be used. The app traverses the list without an invented updated-since filter. It reads raw source records separately from operational stock. The documented detail endpoints are noted for troubleshooting; the current adapter uses the list fields needed by operations.

Setup:

1. Obtain official public-API access for the correct Roast.World account through Aillio’s current access process. The authenticated token-issuance UI was not available to verify here; confirm it with Aillio rather than using a guessed private endpoint.
2. Add `ROASTWORLD_API_KEY` to the protected server environment file and restart the app. Do not paste it into the app UI or chat.
3. Set and review the cutover timestamp first. A first import can safely run with cutover unset: all valid roasts become history-only.
4. Run Sync now. Unmapped beans and missing/noncredible output weights become review tasks. Add exact bean-ID → coffee/profile mappings in Settings; retry pending records after review. If one external bean is used for several profiles, leave ambiguous records queued and use reviewed manual entry rather than pretending a bean-only mapping distinguishes them.
5. Check several source UIDs, Tokyo roast times, actual output weights and opening counts before depending on live production imports.

The docs list 401/403 auth errors and 429 daily token/user limits but do not publish numeric quotas. Polling defaults to 15 minutes and is configurable; increase it if account limits require. The adapter respects a numeric `Retry-After` when supplied and bounds retries. It does not deduct green inventory or control the Bullet.

Historical records do not add all their output to current stock. Later source edits and missing source records create reconciliation issues; they do not erase sales or rewrite movements. Manual notes, holds and policy snapshots survive imports.

### CSV fallback

`fixtures/roasts.csv` is this app’s explicit import schema, **not a claim of native RoasTime export compatibility**. Inspect any actual RoasTime export before converting it.

Required columns: `external_id,bean_id,roasted_at,green_g,output_g`. Timestamps must include a timezone. IDs must remain stable. Preview validates rows, weights, mappings and duplicates; commit reruns validation transactionally. Duplicate IDs cannot repost production. If a real source output is missing, leave it unresolved and enter only verified physical quantities; do not invent yield.

## Shopify

References: [Admin GraphQL overview](https://shopify.dev/docs/api/admin-graphql/latest), [Order](https://shopify.dev/docs/api/admin-graphql/latest/objects/Order), [LineItem](https://shopify.dev/docs/api/admin-graphql/latest/objects/LineItem), [pagination](https://shopify.dev/docs/api/usage/pagination-graphql), [API limits](https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits).

The app pins `2026-10`, the supported stable version shown in the official docs at verification. Review the supported version before future annual upgrades; do not silently use a moving `latest` endpoint.

### App and authentication

Create/install an appropriate Shopify app for your actual store through the current Shopify developer setup. Grant read access for orders and products (`read_orders`, `read_products`) and complete any required order-data access review. No inventory or fulfillment write scope is needed for this implementation.

For an app and store in the same eligible Shopify organization, the official [client-credentials grant](https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant?lang=node) is supported. Configure `SHOPIFY_SHOP`, `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` privately on the server. The server posts the documented client-credentials request to `https://{shop}/admin/oauth/access_token`; tokens are held only in memory and requested for each synchronization run. This avoids persisting expiring tokens in the database.

If your app/store arrangement requires installation OAuth instead, complete that supported authorization flow and supply its Admin API token as `SHOPIFY_ACCESS_TOKEN`. A client ID/secret alone does not authorize unrelated merchants. This app does **not** implement a multi-merchant OAuth installation portal or interactive token-refresh UI. Renew the supplied token using its actual grant/expiry rules; the error state remains visible if it expires.

The canonical `SHOPIFY_SHOP` value is `your-shop.myshopify.com`, not a custom storefront domain. Hostnames are restricted to that pattern. Requests use `X-Shopify-Access-Token` over HTTPS. Secrets never appear in URLs, browser responses or logs.

### Initial import and mappings

1. Restart with the server variables set and select Sync now.
2. Review last-attempt, last-success and exceptions. An enabled/configured credential does not prove a successful live import.
3. Map stable variant IDs to coffee/profile and nominal package size. Classify merchandise as non-coffee. Bundles with unknown composition remain unresolved.
4. Set local dispatch/pickup deadlines. The ordinary view does not collect addresses, customer contact fields or payment details. Shipping-method titles and delivery categories are imported via the paginated shipping-lines connection; missing delivery/pickup details remain an explicit local confirmation.
5. Allocate eligible stock, pack, then reconcile Shopify-confirmed fulfillments against actual picks. No app action sends a customer notification or changes Shopify fulfillment.

Initial sync requests the recent 59-day window; standard order access is limited to recent orders. Older open orders require approved `read_all_orders` access and a deliberate backfill. The app’s watermark overlaps by ten minutes, advances only after complete success, and preserves local deadlines/notes. A server administrator can perform a reviewed normalized import for older permitted records. `fixtures/order.json` documents the normalized fallback format used by the manual importer, not a promise of compatibility with Shopify’s raw CSV export.

Line quantities distinguish original/current/unfulfilled units. Partial fulfillment keeps remaining demand. Cancellations and reductions release excess outstanding reservations, while shipment reconciliation remains explicit. Refunds never create stock. Duplicate fulfillment IDs cannot consume a second time.

### Signed webhooks on the hosted server

Polling works on its own. For the hosted setup, add webhook subscriptions through the installed app’s supported configuration to:

```text
https://YOUR-DOMAIN/api/webhook/shopify
```

Use the appropriate JSON order creation/update/cancellation, refund creation and fulfillment creation/update subscriptions. Their delivery header topics are `orders/create`, `orders/updated`, `orders/cancelled`, `refunds/create`, `fulfillments/create`, `fulfillments/update`. Use the corresponding official topic enums/configuration documented for your app, rather than inventing a REST registration endpoint.

Set `SHOPIFY_WEBHOOK_SECRET` to the installed app secret used for webhook signatures and set the exact `SHOPIFY_SHOP`. The endpoint is disabled without the secret and rejects demo mode. It computes HMAC-SHA256 over the **raw bytes**, constant-time compares the base64 signature, validates the shop/topic, then persists a unique delivery ID and hash. Customer payloads are not retained. Its durable queue wakes the background reconciler; the reconciler fetches latest source state so delayed webhook bodies do not overwrite newer orders. Periodic polling continues for reconciliation. The 2 MB body limit is explicit; unusually large deliveries can be rejected while periodic order polling still provides recovery.

Official guidance: [verify webhook deliveries](https://shopify.dev/docs/apps/build/webhooks/verify-deliveries), [webhook topics](https://shopify.dev/docs/api/admin-graphql/latest/enums/WebhookSubscriptionTopic).

Actual webhook registration, real HMAC deliveries and network reachability were not exercised without your live app/server.

## Source ownership and later writes

Roast.World supplies roast source records; Shopify owns orders/payment/fulfillment; this app owns batch physical movements and local operational commitments. Repeated synchronization never decrements the same shipment automatically.

Outbound Shopify stock writes are not enabled. Before adding them, define owned locations/SKUs, reconcile physical counts, handle Shopify’s committed quantities and avoid subtracting reservations twice. A roast/pack event must never auto-fulfill an order. See the official [inventory quantities/states guide](https://shopify.dev/docs/apps/build/inventory-management-apps/manage-quantities-states) and [inventory state definitions](https://help.shopify.com/en/manual/inventory-and-locations/fundamentals/inventory-states) when implementing that later phase.

Square automatic imports are also deferred. The adapter boundary requires stable event IDs and a reviewed manual/import overlap cutover. Do not retroactively import Square sales on top of the same manually recorded physical deductions.
