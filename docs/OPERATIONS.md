# Using the roastery workspace

## Start with counts, not historical totals

Keep RoasTime controlling the Bullet. Walnuts Roastery does not send roast-control commands.

Configure coffee/profile policies, packages, locations and external bean/variant mappings first. Set the intended cutover timestamp in Settings → Connections. Before cutover, imported roasts become batch history with a zero-balance stock scope. A missing cutover makes all imported roasts history-only. No unknown yield is used to invent stock.

Count the actual remaining coffee by batch. Choose Roasted stock → Balances → Show empty too, then open its row → Historical opening count, record the net weight and a reason. For already packaged coffee, establish the total measured opening bulk equivalent, then use packing and transfers to represent its present form and location. Explain that these are onboarding classifications in the movement reasons. Do not also record the same bags as an additional positive count. The combined opening scopes must reconcile to the actual physical total.

New valid post-cutover source roasts create measured production once. Repeating a source import cannot create it again. Moving the cutover later does not rewrite previously posted stock. Correct any onboarding mistake with a reviewed adjustment/reversal.

If a bean is roasted into multiple different profiles, do not give it an indiscriminate bean mapping. Keep its ambiguous records queued and enter reviewed manual batches until a precise mapping arrangement is established. A source display name is not a stable inventory identity.

## Daily work

**Today** shows net coffee still to roast for customer orders, with expandable tiles per coffee/profile, followed by bean-level green/rested/ready-to-ship balances and café/retail stock. Café forecasts and retail targets stay on Roast plan. Connections and exceptions are managed in Settings.

**Record a roast:** enter the actual time, green input and measured roasted output. Only output becomes stock. The batch snapshots the coffee’s policy. A future roast belongs in the plan. Complete an approved plan from its queue so actual output replaces its expected supply once. For an already imported production batch, open its detail and use “Link completed plan” with a match-confirmation reason; this replaces expected supply without posting production again.

**Roasted stock:** empty physical balances are hidden by default, including bulk that has all been packed. Fully reserved coffee stays visible. Use Balances → Show empty too to find a depleted scope for recounting; history is never deleted. Count stock uses the current page filters.

**Add roasted stock:** use this for already-roasted coffee missed from inventory. Choose an existing batch (including depleted batches) or New / unrecorded batch, enter the additional bulk weight or whole bags and optional measured overfill, choose the physical location, and give a reason. This does not record production, deduct green beans, alter measured roast yields or complete a plan. Use the actual original roast date if known. For unknown dates, the coffee stays unavailable under rest policies until an administrator opens its batch details → Set roast date and records the reviewed date and reason. Existing quality holds remain in place. For a recount of stock already represented, use Count and enter the actual total instead of adding that total again.

**Transfer:** choose a source batch/location/form and a destination. Filling a hopper or moving beans to café storage does not consume coffee. Give individual hoppers/containers their own location names if you will count them separately. Open packaged bags with “Open bags into bulk”; it transfers the actual contents, including recorded overfill, to the selected bulk scope.

**Pack:** choose a package definition and whole bag count. Nominal content plus separately measured overfill and loss leaves bulk. Nominal content and overfill remain physical packaged stock; only loss leaves physical inventory. Packaged overfill is apportioned by the stock scope’s average, with integer remainder retained until the final bag moves. Keep physically distinguishable packing runs in separate named containers if their overfill differs materially.

**Café usage:** record measured consumption, or count actual remaining net weight for that scope. Use one method for the same interval. A count is a reconciliation to the present measured amount, not an extra usage deduction. Counts reject stale versions if a colleague acts while the form is open. Waste/sample/dial-in/staff-use reasons can be typed in the note field.

**Retail sale:** choose the actual packaged batch, oldest eligible first, and a whole bag count. This is a physical deduction. After enabling Square imports, use manual sale entry only for transactions outside the Square import. Confirm the manual/import start to prevent overlap.

**Return:** an administrator must confirm physical receipt into a quality-held batch with a reason. Set a hold before using the return action; decide separately whether to release it. A Shopify refund does not restore coffee.

**Count:** affects only the chosen batch/location/form. Packaged counts use whole units, bulk counts use grams. A count does not overwrite unrelated scopes. Enter the physical amount after considering already logged usage; do not apply the same interval’s consumption again.

**Correction:** open a batch’s movement history and reverse the incorrect transaction with a reason, or make a scoped count adjustment. Reversals link to the original and are rejected if they would spend committed stock. Shipment corrections require a reviewed physical return/count, not a blind reversal of Shopify fulfillment.

## Orders and allocations

Map every Shopify variant by its stable ID to a coffee/profile and net package definition. Mark merchandise non-coffee. Unspecified sample boxes/bundles remain unresolved and cannot silently disappear from the inbox.

Set a local dispatch/pickup deadline. Paid, uncancelled, unfulfilled coffee is eligible by default; the administrator can change payment eligibility. A line can use several batches. Allocate stock in oldest-roast order, considering readiness and freshness by the actual deadline. The server prevents over-reservation and reservation against a different coffee/package. Bulk may be reserved before packing. The planner counts only complete variant-sized bags per stock scope for online coverage; it conservatively leaves partial remnants available for café/other use. Transfer compatible scopes of the same batch together before packing if you want to use those remnants; do not silently mix different batches. Split-bag allocations are visibly flagged for review. A reserved amount stays on hand and reduces free stock only.

“Pack allocation” converts whole-bag bulk allocations to the variant’s package size and moves the same reservation to the packed scope. For explicit packing loss/overfill, release the allocation, pack with variance, then reallocate. Replace fractional bulk allocations when they cannot become whole bags independently; this release does not increase physical stock.

Shopify order source fields remain read-only. Cancellations/reductions release only excess outstanding commitments, incompatible mappings release affected commitments, and partial fulfillment retains remaining demand. Previously reserved coffee for a now-confirmed shipment can be picked once the remaining-order commitments have been reconciled.

When Shopify reports an external fulfillment, the app creates a task. Record the actual package/batch picks across all coffee fulfillment lines. It checks the exact confirmed units and deducts physical stock once, using the fulfillment ID. It never guesses provenance or sends a customer notification. If the shipment actually violated a quality/rest rule, an administrator must review an audited batch override before reconciling it; do not quietly waive the rule.

## Rest and quality

Café brewing, online dispatch and retail sale have independent elapsed-day policies. Dispatch can be earlier than brew readiness only when explicitly configured. No assumed transit time is added. All display times are Asia/Tokyo; storage uses UTC offsets consistently.

A roast at 5 November, 10:00 JST with five elapsed days of rest becomes ready at 10 November, 10:00 JST. Held and archived stock remains in physical counts but cannot satisfy use/allocation. The freshness window is an operational quality window, not an invented safety expiry.

Coffee policy edits affect new batches only. An administrator can explicitly recalculate an existing batch against the current policy, or override its days with a reason. Review affected reservations; the app flags those made ineligible. Holds/releases and overrides have audit records.

## Planning

Use one-off dated café consumption forecasts and dated **total** desired retail stock, plus online line deadlines. Repeated wall minimums retain earlier target coverage while checking freshness again; they are not fresh daily sales demand. If future retail sales are expected, update the target/forecast after recording those actual sales. There is no automated Square sales forecast.

The planner processes deadlines in chronological order with configurable tie priorities. Each free gram is spent once; owned reservations cover only their requirement. Real resting stock can cover a future deadline if ready then. Approved plans are expected supply. Completed plans are excluded because their actual batch now supplies stock. Held/expired supply is ineligible.

For uncovered demand, measured historical yield wins over the labeled fallback estimate. Whole working-charge batches are proposed within maximum capacity. Rounding excess is carried into later suggestions. Start slots and weekdays constrain suggested roast dates; an expired deadline is flagged, never silently waived. A reviewed suggestion can depend on the proposed earlier suggestions/carryover, so approve and recheck the queue after each batch. Plans are not reservations or inventory.

This is a straightforward reviewable planner, not global optimization. It does not infer recipe doses, sales growth, transport times or a roast schedule for you.

## Order sorting and filters

Orders defaults to all imported orders, newest placement first. Use Sort by for oldest/newest placement or earliest/latest local deadline. Order status (Open/Archived/Cancelled), fulfillment, payment and production state can be combined. Search by order number/item, check the visible/total count, or Clear filters. Dates display in JST and filters remain selected during automatic refresh. Shopify ordinary order access is limited to its recent-order permission window; older history still requires approved access and a deliberate backfill.

## Manual wholesale orders

Choose Orders → New wholesale order. Enter the business/customer name, optional contact/email/phone and address, PO/reference, payment terms, delivery method and deadline in JST. Add one or more configured coffees, actual weight per bag in grams, whole bag quantity and grind/preparation. Custom bag sizes become package definitions that can be used for packing. Configure the actual coffee/profile and dispatch-rest rules under Settings first.

Save a draft to keep it out of production demand. Confirmed wholesale orders enter the same rest-aware allocation and roast-planning calculation as online orders, including pending invoice/credit-term orders. Use the Channel filter or customer/reference search to find them. Wholesale records remain local and never create Shopify orders or notifications.

Edit customer/deadline/status details from Edit wholesale order. Release allocations before changing a committed line’s coffee, size or quantity. Keep dispatched lines in the order; total quantity cannot drop below already dispatched units. Cancelling releases outstanding reservations without returning shipped coffee to stock. Concurrent edits are rejected using an order version.

Allocate and pack using the existing actions, then Record dispatch with the actual packed batches. Partial dispatches deduct only the selected bags and leave the remaining demand open. Own allocations can be consumed by the dispatch; other orders’ commitments remain protected. Confirm physical dispatch only after delivery/handover has actually occurred. Payment status tracking and terms are operational fields; invoicing/accounting is outside this screen.

## Roast.World fresh start — 5 November 2026

The live import start and production cutover are set to 5 November 2026, 00:00 Asia/Tokyo (4 November 15:00 UTC). Unposted source roasts before that time are skipped before bean/weight validation. The 2,092 historic import-review exceptions were resolved with an audit entry and a consistent database backup; original source snapshots remain retained. Replaying all 2,092 cached source records leaves those reviews resolved. Shopify exceptions and physical stock history were preserved. Existing posted batches still receive source-edit reconciliation checks even if their source dates move earlier than the cutoff.

New on/after-cutoff roasts require an exact bean-to-coffee mapping, a credible timestamp and actual positive green and roasted weights. Valid new production posts once, using measured output and the configured rest policy. Missing data on new records remains an actionable exception. Any roasted coffee already on hand requires a separate confirmed opening count; weighing green stock alone does not establish roasted stock. Adjust the import start or opening-stock cutover under Settings → Connections → Configure if deliberately reviewing this policy later.

### Green beans, purchases and roast consumption
Open **Green beans** in the navigation. Add each physical green bean (name, origin,
variety, process, notes, currency), then select every roast coffee/profile using
that stock. Multiple profiles, such as espresso and filter, can share one balance.
Roast.World external bean IDs still need to be mapped to those coffee profiles
under Settings; green stock links do not replace source import mappings.

For beans already here, weigh all remaining green stock and use **Count stock**.
For new arrivals, use **Record purchase**: kilograms received, receipt time in JST,
total bean price, supplier, invoice and lot references. Price can be left blank;
blank is different from a zero-cost receipt. JPY uses whole yen; other supported
currencies use cents. Pricing is recorded in the selected bean's currency without
currency conversion, taxes or valuation assumptions. Purchases record physical
receipts, not unreceived purchase orders or payments to suppliers.

Expected stock is receipts minus measured green roast charges, reconciled to the
latest physical count. Counts apply as of saving. Late imports dated before that
count are retained in history but do not subtract green beans already accounted
for in the count. Deductions use green input, never roasted output; manual and
imported production use the same path. Duplicate imports never deduct twice.
Historical batches and roasted opening counts do not consume current green stock.
Source edits remain reconciliation tasks and do not silently rewrite deductions.

Unlinked production is displayed on the green screen. Linking a profile deducts
unposted green charges at the original roast times. Already-posted deductions
retain their original bean if the profile is relinked. A count opened before any
new purchase, roast, link or correction is rejected as stale. Negative expected
balances are displayed for review so missing opening counts or receipts do not
block valid roast imports. Plans show projected needs and stock after plans;
scheduling alone never consumes physical green stock. These needs include linked
profiles only, so finish the links before using the projection.

History keeps purchases, counts, roast batch codes and corrections. Administrators
can reverse an incorrect purchase from **History**, then enter the corrected
receipt. Correct a physical count with a new count. Reversing production through
the batch ledger reverses its green charge too; a later physical count remains the
baseline. History is immutable, and green records are included in ledger exports
and normal SQLite backups. No sample beans or purchases are added to production.

### Entering purchase prices with a green bean
**Add green bean** and the first **Record purchase** (when no beans exist) now open
one form with the bean, currency, quantity received, price per kg and total price.
Enter either price; the other is calculated. A quantity saves a dated receipt in
the same transaction as the bean. Leave purchase details blank to create just the
bean. **Edit / link** can also append a received purchase without replacing past
prices. For later arrivals, **Purchase** opens the same price-entry fields.
Prices, quantities, supplier, invoice reference and currency are kept per receipt,
linked to the physical green bean. Total prices use the currency's minor units;
unit-price entries calculate a receipt total rounded half up to those units.
Unknown prices remain unknown. This preserves purchase data for future costing
and margin reports; the current latest price is not a calculated sales margin.


### Product mapping and Square retail-wall sales
Open **Settings → Products & POS**. Existing Shopify mappings appear under shared products.
Filter catalogue entries to Square and Needs mapping; review each coffee’s
suggested shared product, roast profile and bag size. A 150g bag must point to the
150g product even when source names/SKUs differ. Select and exclude drinks and
merchandise in batches. Mapping decisions persist by source item identity across
renames. Catalogue edits that change weight require review. Bundles need an
explicit composition model and must remain unresolved.

Before enabling deductions, establish actual packaged wall balances using the
existing batch opening/count, pack and transfer actions. Under **Configure shop &
start date**, choose the cutover after the last manually covered sale and enable
automatic oldest-batch deductions. Staff should sell oldest eligible wall coffee
first. The first configured shop is in preview mode until this setup is done.

Each receipt deducts whole bags only from compatible, ready, unreserved wall
stock, preserving batch provenance and measured overfill. Other locations/bulk
are never guessed as substitutes. Pending receipts are atomic: no partial stock
is deducted while another line remains unresolved. Review the receipt’s reason,
fix mapping or physical stock, then **Retry pending deductions**. A receipt dated
before a wall count needs manual reconciliation. **Already covered by a count**
is available only for unposted receipts and requires a reason/reference. It
acknowledges a sale already counted/logged without making another stock movement.
Refunds/returns do not add physical stock. A posted receipt changed in Square
retains its original batch picks and raises an exception.

### Square Beans category scope
Square mapping and receipt processing are limited to the category named **Beans**.
The first sync resolves its exact category ID and saves it; later syncs follow that
identity. Modern category memberships, legacy category IDs and reporting category
IDs are read from the parent item. Other variations stay outside the mapping
screen and never consume bean stock. Mixed receipts retain and deduct only the
Bean-category lines in the dashboard. Existing unrelated previews are archived as
outside scope without deleting history or reversing physical stock. If the category
cannot be resolved, syncing stops visibly rather than including the whole catalogue.

### Square in-store receipts and scheduled starts

Completed Square sales with no fulfillment record, or only completed `IN_STORE`
fulfillments, deduct approved Bean items from eligible retail-wall stock. Pickup,
delivery, shipping, unknown or incomplete fulfillments and returns remain for
review. Only fulfillment type/state is retained; recipient details are discarded.
Older receipts with only a generic fulfillment flag need a fresh import before
classification. Repeat imports preserve the existing once-only deduction.

An enabled Square connection with a future deduction start is shown as scheduled.
Earlier receipts are imported as “before start” and leave stock unchanged. Choose
the exact operational cutover when sales begin counting, avoiding any interval
already covered by manual entries or physical counts.

## Profit reporting and shipping

Open **Profit** for completed Square bean receipts and fulfilled, paid Shopify
orders. Select dates (inclusive JST), day/week/month groups, channel, bean/profile,
package, currency and cost coverage; search or sort the detail and export the
filtered lines as CSV. Refunds restate the original sale date. Shopify processing
and Square completion timestamps determine dates. Initial financial imports refresh
the accessible recent 59-day window; older records without prices remain missing.

On **Orders**, dispatched/fulfilled orders expose **Add shipping details**. Record
one or more parcels with carrier, service, tracking, dispatch date, optional weight,
and actual cost **excluding tax**, in the order currency. Choose pickup for an
explicit zero cost. Edits require a note, check the record version and retain audit
history. Saving shipping never adjusts inventory or writes back to Shopify.

Bean COGS uses moving weighted-average green inventory cost at the roast date,
measured roast yield and actual picked weight (including overfill). Unknown opening
valuations, count gains, unpriced receipts and missing batch picks remain unknown.
Counts reducing green stock preserve average price. Purchase corrections replay
costs; historical profit can change. Historical fulfillment picks are not guessed.
Customer shipping income and carrier costs are allocated by discounted item value
before refunds, including the non-coffee share; only the bean share is reported.
All amounts are integer currency minor units; allocation preserves totals.

Packaging, payment fees, labor and overhead are intentionally excluded from this
first version. They can be added as distinct cost categories later. Packing waste,
manual stock losses, local wholesale sales, café drinks and manual retail stock
movements are not represented as sale profits. Missing values display a dash,
never zero; complete-line profit is shown separately when totals are incomplete.
Refunds do not restore physical coffee or automatically reverse its cost. Ambiguous,
amount-only or unconfirmed refunds require review and block the profit figure.

Migration 011 adds only reporting/shipping tables and immutable fulfillment pick
references. Export includes those records. Existing Square deduction cutoffs and
idempotency protections remain active during the financial backfill.

### Estimated COGS for historical sales

Where full batch costing is unavailable, Profit uses the latest non-reversed priced green receipt linked to the coffee profile. Without batch picks it divides that green cost by the configured roast yield and applies it to sold bag weight. With recorded picks but missing valuation it uses the actual batch yield and includes overfill. These values are labelled Estimated COGS, identified in details and CSV, and can be selected using the cost coverage filter. Estimates can revise with newly entered green prices. Recorded batch costing remains preferred. Known COGS subtotals are shown even when other sale lines still need mapping or price information. Missing currencies or unapproved product mappings are never guessed. This is reporting only and creates no stock movements.

## Imported roasts needing information

Roast.World records needing a bean assignment, valid date or measured weights appear
as red **Needs information** rows in **Roast batches**, including existing saved
imports. Import-review messages are managed there instead of the exceptions inbox.
Administrators use **Add missing information** to confirm the coffee/profile, date
and measured weights with a note. A real external bean ID can optionally be mapped
for future imports; absent IDs allow only a per-roast assignment. Existing conflicting
mappings require separate review. Completion rejects stale source versions.
Incomplete imports do not create usable stock or planner supply. Completion posts a
normal batch once per source ID and respects import-start and inventory-cutover
settings. Historical roasts require opening counts. The original source snapshot is
retained; later source edits still require review. Other issues remain in Settings.

## Deleting exhausted coffees

Administrators can use **Delete coffee** under **Settings → Coffees**. This removes
the profile from the active list, new coffee selectors and Today. **Deleted coffees**
on the same tab offers Restore. Stable coffee identities, green price links, batch
policies, movements and sales history remain available for reporting.

Deletion requires zero roasted stock (including held stock and package overfill),
no allocations, no open unfulfilled orders, no planned roasts and no upcoming café
forecasts or retail targets. The last active profile for a green bean also requires
its green balance to be zero. Shared beans remain visible while another profile is
active. Standalone green stock is not deleted by removing a coffee profile.

Past forecasts for removed coffees are retained but excluded from planning. If a
stock movement later creates a positive balance for a removed coffee, its profile
is restored automatically and this is audited. Explicit Restore does not create
stock. Source mappings remain intact. Migration 012 adds only coffee_archives;
no historical inventory or financial records are removed. Deletion/restore and
automatic restoration events appear in audit and export.

## Espresso recipes: mix and roast per batch

At the top of **Settings → Coffees**, use **Set up espresso blend** and select the
existing finished Espresso coffee. The default import label is Espresso. The
current Roast.World list exposes `roastName` (confirmed against live imports), so
use **Espresso as the roast name** in RoasTime. Explicit roast tags are supported
when present in the source response; bean tags are not used as a substitute for
roast tags. Matching is exact after trimming and case folding, never a partial-name
match. Ambiguous blend matches stay pending in Roast batches.

Create a recipe by choosing real Green beans, entering percentages totalling
exactly 100%, and setting **Use for roasts from (JST)**. The charge preview shows
integer-milligram weigh-outs and preserves the total through largest-remainder
rounding. The entered recipe is green-input proportions, not roasted-output
proportions. Actual roasted output remains one finished Espresso batch. The
Espresso coffee must not also have a single-bean green link.

Recipe changes create immutable versions. Import chooses the latest non-cancelled
version effective at the original roast timestamp, not import time. Every batch
stores its recipe ID, ingredient names, proportions and exact input weights.
Existing batches never adopt a later recipe. An explicit per-roast recipe override
requires a note. Unused recipe versions may be cancelled; used versions remain
part of history. The next version must start later than existing active versions.

Missing recipes, invalid weights and insufficient recorded components remain red
pending roasts. Enter actual receipts/counts or explicitly review the roast; no
automatic recipe substitutions occur. All component deductions and the roasted
output post in one transaction and are once-only per source roast identity. A
production reversal returns every component. Existing cutover and later-physical-
count treatment remains in effect. Historical pre-cutover batches do not post
physical stock or component deductions. Stock-only additions do not consume green.

Green beans shows ingredient requirements from approved blend roast plans. Roast
plan suggestions show their proposed ingredients. Today tracks the finished blend
as Espresso while green stock remains under the individual ingredients. Batch
details show the recipe snapshot and weigh-out.

Recorded batch COGS sums moving-average costs of every green component and divides
by the measured finished output. A missing component price prevents a recorded
cost; labelled estimates can use component purchase prices with the batch's frozen
recipe and actual yield. Without batch picks, estimates use the recipe effective
at the sale timestamp and the configured yield; they identify that the actual batch
is unknown. They never use a recipe effective after that timestamp. Component
currencies must match; no automatic currency conversion is supplied.

Migration 013 adds recipe/profile/snapshot/component tables without rebuilding or
rewriting the immutable green ledger. Legacy single-bean events retain their batch
reference. Blend component events use the separate batch_green_components
references, allowing multiple component deductions per roast. Export includes all
new recipe and component records. No recipe is activated automatically on deploy.
