# Release verification — 5 November 2026

**Final result: 41 automated tests passed, 0 failed, 0 skipped.**

The final suite ran on Python 3.12.0 / SQLite 3.42.0. Production should use a currently patched Python/OS runtime. JavaScript syntax validation also passed. The persisted local demo database passed `PRAGMA integrity_check` with all four migrations applied.

## What was exercised

| Brief acceptance checks | Evidence / outcome |
|---|---|
| 1: actual output and repeat import | 1,000 g green → 850 g stock, exactly once per source UID. Passed. |
| 2–4: pack, transfer, reserve, sell, release | Four 100 g bags, 300 g café transfer and 150 g reservation preserve 850 g; one bag sale leaves 750 g; reservation release does not add physical stock. Passed. |
| 5: simultaneous actions and duplicate submit | Two threads compete for insufficient stock/reservation capacity; one succeeds. Repeated request IDs do not double-post and conflicting payload reuse fails. Passed. |
| 6–8: rest, hold and Tokyo boundaries | Separate dispatch/brew rules; held stock remains physical but ineligible; 5 Nov 10:00 JST + five elapsed days = 10 Nov 10:00 JST. Passed. |
| 9: packing mass and units | Whole bags only; explicit loss/overfill; overfill follows transfers, sales and unpacking with ledger conservation. Passed. |
| 10: mapping and merchandise | Unknown variant produces a task; non-coffee contributes no roast demand; no name-only matching. Passed. |
| 11: order changes and fulfillment | Reduction/cancellation/stale update handling, partial remaining demand, whole-bag reservations after edits, duplicate fulfillment pick prevention. Passed. |
| 12: refund | Does not restore physical stock. Passed. |
| 13: historical and missing output | Historical imports stay zero-balance until explicit opening count; missing/zero output stays unresolved. Passed. |
| 14: source edits/deletion | Changed source after consumption and a missing record after complete sync produce review tasks; inventory remains unchanged. Passed with fixtures. |
| 15: scoped counts | Only the selected stock scope changes; actor/reason recorded; stale count version rejected. Passed. |
| 16: planning | Future readiness, oldest eligible stock, no cross-channel reuse, measured yield, capacities/slots, target carryover with freshness recheck, completed/import-linked plans counted once, no fictitious cross-batch partial bags. Passed. |
| 17: failure/security | Provider errors visible/redacted, manual work continues, hostname checks, role restrictions, CSRF/origin checks, session cookie flags, no password fields in state, raw-byte HMAC and persistent delivery deduplication. Passed with local HTTP and fixtures. |
| 18: persistence/recovery | Reopened database keeps balances; online backup restores into a clean test path with balances/history and integrity intact. Passed. |

Additional checks include policy snapshots, immutable ledger triggers, linked reversal protection, CSV preview/duplicates and reserved-bulk packing that preserves commitment.

## Browser verification

Used the actual running app through its UI, not a static mockup:

- Signed in to the isolated demonstration workspace.
- Created `UI-SMOKE-850` with 1,000 g green input and 850 g measured output.
- Packed four 100 g bags into the wall, moved 300 g bulk to the café, and verified the three scopes still totaled 850 g.
- Sold one bag and verified three wall bags plus 300 g café and 150 g roastery stock: 750 g total.
- Packed an existing 200 g online reservation and verified the order still displayed that allocation, now packed.
- Restarted the server and verified the saved batch/order state remained.
- Inspected Today, Stock, Orders, Roast plan and Settings. Checked 390 × 844 phone and 1440 × 1000 desktop layouts. Both dashboard layouts fit their viewport without page-level horizontal overflow; wide stock/order tables scroll within their panels.

Screenshots are delivered alongside the source. The persistent demo includes the fictional browser-check batch; fresh demo files recreate the original seed. A full browser automation suite is not bundled; the reproducible automated end-to-end test operates through authenticated HTTP and exercises real DB-backed staff operations.

## Verification boundaries

**Implemented and locally tested:** database/migrations, manual staff operations, authentication/roles, policies/holds, counts/corrections, mappings/allocations, dated planner, CSV preview, webhook verification/queue, backup/restore and responsive UI.

**Fixture-tested, not live-verified:** Aillio pagination/import behavior, Shopify query transport and nested pagination, delivery metadata, rate-limit/error paths, source update reconciliation, fulfillment IDs and webhook deliveries. Official documentation was checked; representative mocked responses do not establish that the installed merchant app has the correct permissions or that its live payloads match every assumption.

**Prepared, not deployed/tested on infrastructure:** Docker Compose, Caddy certificates/reverse proxy, systemd service/timer, offsite encrypted backup storage, real browser devices and public internet access. No server, domain or live credentials were supplied. The local listener was bound to loopback only. This is not a claim of a completed security audit or high-load test.

**Deferred:** automatic Square imports, outbound Shopify inventory/fulfillment writes, multi-merchant OAuth installation UI, blends/cross-batch pooling, bundle-component modeling, automated recipe-dose forecasts, Japanese translation, QR scanning and label-printer integration.

## Reproduce

From the project directory:

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```

The suite creates temporary databases and a temporary loopback HTTP listener. It requires no live credentials or network API access. Keep production data outside tests and demo mode.

## Order completeness and filtering fix — 5 November 2026

Fixed an unquoted Shopify `updated_at` timestamp: the original live query returned 9 orders while the quoted query returned 31. Added a one-time import-version backfill that advances only after complete success. Live reconciliation completed with 31 orders; all orders walnut1237–walnut1256 are present and all imported orders have source creation dates. Local deadlines remain preserved.

The updated suite passed 46 Python tests plus the Node order-view tests (chronological/timezone sorting, missing dates, combined status filters and non-mutating results). An isolated browser demo confirmed payment filtering, combined-filter empty results and Clear filters. The live server was restarted with the corrected source.

## Manual wholesale orders — 5 November 2026

57 Python tests pass, plus the order-view checks. Added coverage for staff HTTP creation, invoice-pending demand, drafts, idempotent submission, custom bag sizes, stale edits, cancellation/release, partial dispatch and duplicate dispatch, rollback on quality holds, protecting other orders’ reservations, and preventing edits to Shopify orders through the wholesale endpoint. Browser verification used a separate demo database: created and edited a two-coffee customer order, checked line totals and channel filtering, and reloaded the saved form. Live migration 006 was applied after a consistent backup; existing Shopify orders were preserved and no fictional customer orders were inserted into production.

## Roast import cutoff — 5 November 2026

60 automated tests pass. Added coverage for filtering older invalid records before validation, preventing their exceptions from reopening, including the exact midnight JST boundary, keeping validation active for new records, and preserving source-edit reconciliation on already posted batches. Live maintenance archived 2,092 historical import reviews; a replay skipped all 2,092 and left zero active roast exceptions. Seven Shopify exceptions were preserved. Physical balances were unchanged.

## Green inventory update — 5 November 2026
- 72 Python tests pass, including authenticated staff purchase/count/export coverage.
- Green coverage: receipt and roast idempotency; currency precision; measured input
  versus output; shared profiles; plan projections; historical batch exclusion;
  late imports before a physical count; stale counts; backfilled links; production
  and purchase reversals; immutable history; source edits; and negative balances.
- JavaScript syntax and existing order sorting/filter checks pass.
- Isolated browser QA: add a green bean and link its roast profile, receive 30 kg
  at JPY 72,000 (JPY 2,400/kg), verify 2.4 kg in actual roast deductions, reconcile
  a 27.5 kg opening count, and reload to verify persistence. Sample data only.

### Purchase price entry correction
The empty green catalogue previously redirected Record purchase to metadata-only
bean creation. Both creation and repeat-purchase forms now expose unit and total
prices. Added transaction/idempotency, rollback and unit-price rounding checks.
Isolated browser QA verified the empty-catalogue path: 30 kg at JPY 2,400/kg saves
one linked JPY 72,000 receipt, displays its price in history, and preserves it
through reload. No sample purchases were entered into production.
