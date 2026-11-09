# Profit update validation — 8 November 2026

- 139-test full suite passed, followed by 20 profit tests after the historical unmapped-line fix and authenticated shipping HTTP tests.
- Five JavaScript suites passed (profit, Today, orders, stock, products).
- Read-only Shopify production query confirmed the new price fields against the connected account.
- Isolated browser preview: missing-cost filter, saved carrier cost, refreshed profit, persisted shipping entry on Orders, weekly charts and 390 px mobile form (no document horizontal overflow).
- No production inventory was used in UI tests; all preview sales are fictional.

Provider field references:
- https://shopify.dev/docs/api/admin-graphql/latest/objects/LineItem#field-LineItem.fields.priceAfterAllDiscountsBeforeTaxesSet
- https://shopify.dev/docs/api/admin-graphql/latest/objects/Order#field-Order.fields.currentShippingPriceSet
- https://shopify.dev/docs/api/admin-graphql/latest/objects/Refund
- https://developer.squareup.com/reference/square/objects/OrderLineItem
- https://developer.squareup.com/reference/square/objects/OrderReturn

Live deployment: migration applied, database integrity OK, HTTPS healthy. Square refreshed 2,338 receipts with the existing deduction cutoff preserved. Historical rows lacking actual batch picks or costs remain incomplete.
