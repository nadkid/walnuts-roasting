"""Financial correctness: no unknown-zero assumptions, no inventory side effects."""
import json,unittest
from decimal import Decimal
from server import profit,green,square,products
from server.db import rows,one,uid,transaction
from server.domain import stock_id
from server.imports import order_import,fulfillment_pick
import test_core

def bag(amount,currency='JPY'):
    return {'shopMoney':{'amount':str(amount),'currencyCode':currency}}

class Profit(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
    def tearDown(self):self.c.tearDown()
    def op(self,fn,data,key=None):return self.c.runop(fn,data,'Tester',key or uid())
    def bean(self,currency='JPY'):
        return self.op(green.save_bean,{'name':'Green test','currency':currency,'coffee_ids':['c']})['id']
    def purchase(self,bean,grams=2000,total=2000,at='2026-11-01T00:00:00Z'):
        return self.op(green.receive,{'bean_id':bean,'grams':grams,'total':total,'received_at':at})
    def shopify(self,net=1800,units=2,net_units=None,refunds=None,currency='JPY',shipping=400):
        net_units=units if net_units is None else net_units
        order={'id':'o','name':'#PROFIT','createdAt':'2026-11-10T01:00:00Z','processedAt':'2026-11-10T01:01:00Z','updatedAt':'2026-11-20T01:00:00Z','currencyCode':currency,'taxesIncluded':False,'displayFinancialStatus':'PAID','displayFulfillmentStatus':'FULFILLED','currentShippingPriceSet':bag(shipping,currency),'shippingLines':[], 'refunds':refunds or [], 'lines':[{'id':'l','title':'Coffee','variant':{'id':'v'},'quantity':units,'currentQuantity':net_units,'unfulfilledQuantity':0,'priceAfterAllDiscountsBeforeTaxesSet':bag(net,currency),'originalTotalSet':bag(2000,currency),'discountAllocations':[{'allocatedAmountSet':bag(200,currency)}],'taxLines':[]}], 'fulfillments':[{'id':'f','createdAt':'2026-11-12T01:00:00Z','status':'SUCCESS','lines':[{'line_id':'l','quantity':units}]}]}
        self.c.runop(order_import,order);return order
    def picked_sale(self,overfill=0):
        bean=self.bean();self.purchase(bean)
        batch=self.c.batch(green=1000,output=800);bulk=stock_id(self.db,batch,'roastery')
        self.c.move(bulk,'pack',package_id='p',units='2',overfill_g=overfill,location_id='packing',reason='Measured packaging overfill')
        self.shopify();packed=stock_id(self.db,batch,'packing','p')
        self.op(fulfillment_pick,{'fulfillment_id':'f','picks':[{'line_id':'l','stock_id':packed,'grams':'200'}]})
        return batch,bean
    def shipping(self,**kw):
        return {'order_id':'o','version':0,'currency':'JPY','mode':'shipping','reason':'Carrier receipt','parcels':[{'carrier':'Japan Post','service':'Parcel','tracking':'TEST-123','shipped_at':'2026-11-12T01:00:00Z','cost':'500','weight_g':'250'}],**kw}
    def report(self):return profit.snapshot(self.db)['rows']
    def test_historical_shipments_preserve_estimated_or_unknown_costs_without_inventory(self):
        from server import shipments
        self.shopify();before=self.report()[0]
        self.op(shipments.reconcile,{'fulfillment_id':'f','reason':'Shipped before batch tracking'})
        after=self.report()[0]
        self.assertIsNone(after['bean_cost_minor']);self.assertEqual(after['cost_basis'],'missing')
        self.assertEqual(before['net_sales_minor'],after['net_sales_minor'])
        self.assertIn('pre-dashboard stock',after['cost_note'])
        bean=self.bean();self.purchase(bean)
        after=self.report()[0];self.assertIsNotNone(after['bean_cost_minor'])
        self.assertEqual(after['cost_basis'],'estimated');self.assertIn('pre-dashboard stock',after['cost_note'])
        self.assertEqual(rows(self.db,'SELECT * FROM fulfillment_picks'),[])
        self.assertEqual(rows(self.db,'SELECT * FROM stocks'),[])
        self.op(shipments.reconcile,{'fulfillment_id':'f','action':'reopen','reason':'Review shipment'})
        self.assertNotIn('pre-dashboard stock',self.report()[0]['cost_note'])
    def test_weighted_average_measured_yield_overfill_and_no_future_price(self):
        b=self.bean();self.purchase(b,2000,2000)
        first=self.c.batch(green=1000,output=800)
        self.purchase(b,1000,3000,'2026-11-06T00:00:00Z')
        second=self.c.batch(green=1000,output=800,roasted='2026-11-07T00:00:00Z')
        costs=profit.batch_costs(self.db)
        self.assertEqual(costs[first]['rate'],Decimal(1000)/800000)
        self.assertEqual(costs[second]['rate'],Decimal(2000)/800000)
        self.assertEqual(profit.pick_cost([{'batch_id':first,'quantity_mg':200000,'overfill_mg':4000}],costs,'JPY',200000),(255,None))
    def test_unknown_opening_count_is_not_free(self):
        b=self.bean();self.op(green.count,{'bean_id':b,'version':0,'grams':2000,'reason':'Opening'})
        self.c.batch();self.assertEqual(profit.batch_costs(self.db),{})
    def test_count_reduction_preserves_price_and_count_gain_is_unknown(self):
        b=self.bean();self.purchase(b)
        self.db.execute("UPDATE settings SET value='\"2026-11-02T03:00:00Z\"' WHERE key='demo_clock'")
        v=one(self.db,'SELECT version FROM green_beans WHERE id=?',(b,))['version']
        self.op(green.count,{'bean_id':b,'version':v,'grams':1500,'reason':'Physical count'})
        self.db.execute("UPDATE settings SET value='\"2026-11-20T03:00:00Z\"' WHERE key='demo_clock'")
        batch=self.c.batch();self.assertIn(batch,profit.batch_costs(self.db))
        self.db.execute("UPDATE settings SET value='\"2026-11-06T03:00:00Z\"' WHERE key='demo_clock'")
        v=one(self.db,'SELECT version FROM green_beans WHERE id=?',(b,))['version']
        self.op(green.count,{'bean_id':b,'version':v,'grams':2500,'reason':'Found green coffee'})
        self.db.execute("UPDATE settings SET value='\"2026-11-20T03:00:00Z\"' WHERE key='demo_clock'")
        later=self.c.batch(roasted='2026-11-07T00:00:00Z');self.assertNotIn(later,profit.batch_costs(self.db))
    def test_unpriced_purchase_and_reversal_do_not_invent_cost(self):
        b=self.bean();self.purchase(b,total=None);batch=self.c.batch();self.assertNotIn(batch,profit.batch_costs(self.db))
        event=one(self.db,"SELECT * FROM green_events WHERE kind='purchase'")
        self.op(green.reverse,{'event_id':event['id'],'reason':'Wrong receipt'})
        self.purchase(b,total=2000);self.assertIn(batch,profit.batch_costs(self.db))
    def test_complete_profit_and_shipping_never_change_stock(self):
        self.picked_sale(overfill=4);before=self.c.total();self.op(profit.save_shipping,self.shipping())
        r=self.report()[0];self.assertEqual(r['net_sales_minor'],1800);self.assertEqual(r['shipping_income_minor'],400)
        self.assertEqual(r['bean_cost_minor'],255);self.assertEqual(r['shipping_cost_minor'],500);self.assertEqual(r['profit_minor'],1445);self.assertEqual(r['status'],'complete')
        self.assertEqual(self.c.total(),before);self.assertEqual(r['sold_at'],'2026-11-10T01:01:00+00:00')
    def test_missing_shipping_and_missing_pick_are_not_zero(self):
        self.shopify();r=self.report()[0];self.assertIsNone(r['bean_cost_minor']);self.assertIsNone(r['shipping_cost_minor']);self.assertIsNone(r['profit_minor'])
        self.assertIn('Green purchase cost missing',r['issues'])
    def test_explicit_pickup_is_zero(self):
        self.picked_sale();self.op(profit.save_shipping,self.shipping(mode='pickup',parcels=[]));r=self.report()[0]
        self.assertEqual(r['shipping_cost_minor'],0);self.assertEqual(r['profit_minor'],1950)
    def test_shipping_multiple_parcels_edits_are_audited_idempotent_and_versioned(self):
        self.shopify();d=self.shipping();d['parcels'].append({**d['parcels'][0],'cost':'200','tracking':'SECOND'})
        self.op(profit.save_shipping,d,'same');self.assertTrue(self.op(profit.save_shipping,d,'same')['duplicate'])
        s=profit.shipping_snapshot(self.db)['o'];self.assertEqual(sum(p['cost_minor'] for p in s['parcels']),700);self.assertEqual(s['version'],1)
        with self.assertRaises(ValueError):self.op(profit.save_shipping,d)
        d['version']=1;d['parcels'][0]['cost']='450';self.op(profit.save_shipping,d)
        self.assertEqual(profit.shipping_snapshot(self.db)['o']['version'],2)
        self.assertEqual(len(rows(self.db,"SELECT * FROM audit WHERE action='shipping_cost'")),2)
        self.assertEqual(len(rows(self.db,'SELECT * FROM entries')),0)
    def test_shipping_rejects_unfulfilled_wrong_currency_invalid_money_and_future_date(self):
        self.c.order()
        with self.assertRaises(ValueError):self.op(profit.save_shipping,self.shipping())
        self.shopify()
        for d in [self.shipping(currency='USD'),self.shipping(parcels=[]),self.shipping(mode='pickup'),self.shipping(reason='')]:
            with self.assertRaises(ValueError):self.op(profit.save_shipping,d)
        for field,value in [('cost','1.5'),('cost','-1'),('cost','NaN'),('cost',''),('carrier',''),('shipped_at','2027-01-01T00:00:00Z'),('shipped_at','2026-01-01T00:00:00Z')]:
            d=self.shipping();d['parcels'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.op(profit.save_shipping,d)
        self.assertFalse(profit.shipping_snapshot(self.db))
    def test_shopify_refunds_not_double_subtracted_and_actual_pick_cost_retained(self):
        self.picked_sale();self.op(profit.save_shipping,self.shipping(mode='pickup',parcels=[]))
        refund={'transactions':[{'status':'SUCCESS','kind':'REFUND'}],'totalRefundedSet':bag(900),'refundLineItems':[{'quantity':1,'subtotalSet':bag(900),'totalTaxSet':bag(0)}]}
        o=self.shopify(net=900,net_units=1,refunds=[refund]);o['displayFinancialStatus']='PARTIALLY_REFUNDED';self.c.runop(order_import,o)
        r=self.report()[0];self.assertEqual(r['net_sales_minor'],900);self.assertEqual(r['bean_cost_minor'],250);self.assertEqual(r['profit_minor'],1050)
    def test_pending_and_unallocated_refunds_block_profit(self):
        self.picked_sale();self.op(profit.save_shipping,self.shipping(mode='pickup',parcels=[]))
        self.shopify(refunds=[{'totalRefundedSet':bag(100),'transactions':[{'status':'PENDING'}],'refundLineItems':[]}])
        r=self.report()[0];self.assertIsNone(r['net_sales_minor']);self.assertIsNone(r['profit_minor']);self.assertIn('Refund allocation needs review',r['issues'])
    def test_tax_included_shipping_after_shipping_refund(self):
        order=self.shopify(shipping=330);order['taxesIncluded']=True;order['shippingLines']=[{'isRemoved':False,'taxLines':[{'priceSet':bag(50)}]}]
        order['refunds']=[{'transactions':[{'status':'SUCCESS'}],'totalRefundedSet':bag(220),'refundShippingLines':[{'subtotalAmountSet':bag(200),'taxAmountSet':bag(20)}]}]
        self.c.runop(order_import,order);r=self.report()[0];self.assertEqual(r['shipping_income_minor'],300);self.assertEqual(r['net_sales_minor'],1800)
    def test_noncoffee_share_of_shipping_not_charged_to_beans(self):
        self.picked_sale();o=self.shopify();o['lines'].append({'id':'m','title':'Mug','variant':{'id':'mug'},'quantity':1,'currentQuantity':1,'unfulfilledQuantity':0,'priceAfterAllDiscountsBeforeTaxesSet':bag(1800),'originalTotalSet':bag(1800),'discountAllocations':[],'taxLines':[]})
        self.c.runop(order_import,o);self.db.execute("UPDATE variants SET kind='noncoffee' WHERE id='mug'")
        self.op(profit.save_shipping,self.shipping());r=self.report()[0]
        self.assertEqual(len(self.report()),1);self.assertEqual(r['shipping_cost_minor'],250);self.assertEqual(r['shipping_income_minor'],200);self.assertEqual(r['profit_minor'],1500)
    def test_currency_mismatch_blocks_cost_not_combined(self):
        self.picked_sale();self.db.execute("UPDATE green_beans SET currency='USD'")
        r=self.report()[0];self.assertIsNone(r['bean_cost_minor']);self.assertIn('Bean cost currency differs',r['issues'])
    def test_fulfillment_replay_is_once_and_stale_source_cannot_replace_prices(self):
        batch,_=self.picked_sale();packed=stock_id(self.db,batch,'packing','p')
        # Already recorded with a new request must fail; old inventory remains intact.
        with self.assertRaises(ValueError):self.op(fulfillment_pick,{'fulfillment_id':'f','picks':[{'line_id':'l','stock_id':packed,'grams':'200'}]})
        self.assertEqual(len(rows(self.db,'SELECT * FROM fulfillment_picks')),1)
        o=self.shopify();o['updatedAt']='2026-11-19T00:00:00Z';o['lines'][0]['priceAfterAllDiscountsBeforeTaxesSet']=bag(99999);self.c.runop(order_import,o)
        self.assertEqual(self.report()[0]['net_sales_minor'],1800)
    def test_unpaid_unfulfilled_and_wholesale_not_in_sales_report(self):
        o=self.shopify();self.assertEqual(len(self.report()),1)
        for changes in [{'displayFinancialStatus':'PENDING'},{'displayFulfillmentStatus':'UNFULFILLED'}]:
            self.c.runop(order_import,{**o,**changes});self.assertFalse(self.report())
        self.db.execute("UPDATE orders SET source='wholesale'");self.assertFalse(self.report())
    def test_allocation_preserves_minor_units_and_zero_value_orders_unknown(self):
        self.assertEqual(sum(profit.allocate(100,{'a':1,'b':1,'c':1}).values()),100)
        self.assertEqual(profit.allocate(1,{'a':1,'b':1}),{'a':1,'b':0})
        self.assertEqual(profit.allocate(100,{'a':None}),{'a':None})
        self.assertEqual(profit.allocate(100,{'a':0}),{'a':None})
        self.assertEqual(profit.allocate(0,{'a':0}),{'a':0})
    def test_square_net_price_after_tax_discount_and_returns_without_restock(self):
        b=self.bean();self.purchase(b);batch=self.c.batch(green=1000,output=800);self.c.move(stock_id(self.db,batch,'roastery'),'pack',package_id='p',units='2',location_id='wall')
        products.seed_shopify(self.db);product=one(self.db,'SELECT id FROM sale_products')['id'];products.upsert(self.db,'square',{'id':'sq','name':'Coffee','variation':'100g'})
        self.op(products.approve,{'source':'square','external_id':'sq','version':1,'kind':'coffee','product_id':product})
        self.db.execute("INSERT INTO square_locations VALUES ('shop','Shop',1)")
        with transaction(self.db):square.configure(self.db,{'location_id':'shop','start_at':'2026-11-01T00:00:00Z','enabled':True},'Tester')
        receipt={'id':'sq-sale','location_id':'shop','version':1,'state':'COMPLETED','created_at':'2026-11-10T00:00:00Z','closed_at':'2026-11-10T00:00:00Z','updated_at':'2026-11-10T00:00:00Z','line_items':[{'uid':'sq-line','catalog_object_id':'sq','quantity':'2','total_money':{'amount':1980,'currency':'JPY'},'total_tax_money':{'amount':180,'currency':'JPY'},'total_discount_money':{'amount':200,'currency':'JPY'}}]}
        with transaction(self.db):square.import_order(self.db,receipt);square.retry_sales(self.db)
        r=self.report()[0];self.assertEqual(r['net_sales_minor'],1800);self.assertEqual(r['profit_minor'],1550)
        returned={'id':'return','location_id':'shop','version':1,'state':'COMPLETED','created_at':'2026-11-11T00:00:00Z','closed_at':'2026-11-11T00:00:00Z','updated_at':'2026-11-11T00:00:00Z','returns':[{'source_order_id':'sq-sale','return_line_items':[{'source_line_item_uid':'sq-line','quantity':'1','total_money':{'amount':990,'currency':'JPY'},'total_tax_money':{'amount':90,'currency':'JPY'}}]}]}
        before=self.c.total()
        with transaction(self.db):square.import_order(self.db,returned);square.import_order(self.db,returned)
        r=next(r for r in self.report() if r['order_id']=='sq-sale');self.assertEqual(r['net_sales_minor'],900);self.assertEqual(r['bean_cost_minor'],250);self.assertEqual(r['net_units'],1);self.assertEqual(r['profit_minor'],650);self.assertEqual(self.c.total(),before)
    def test_json_export_does_not_contain_provider_customers(self):
        o=self.shopify();o['customer']={'email':'PRIVATE'};o['lines'][0]['customAttributes']=[{'key':'customer','value':'PRIVATE'}];self.c.runop(order_import,o)
        self.assertNotIn('PRIVATE',one(self.db,'SELECT payload FROM order_financials')['payload'])

    def test_unmapped_historical_square_line_does_not_break_report(self):
        receipt={'id':'unmapped','location_id':'shop','version':1,'state':'COMPLETED','created_at':'2026-11-10T00:00:00Z','closed_at':'2026-11-10T00:00:00Z','updated_at':'2026-11-10T00:00:00Z','line_items':[{'uid':'line','quantity':'1','name':'Custom coffee','total_money':{'amount':1000,'currency':'JPY'}}]}
        with transaction(self.db):square.import_order(self.db,receipt)
        r=self.report()[0]
        self.assertIsNone(r['profit_minor']);self.assertIn('Product mapping needs review',r['issues'])

    def test_historical_sales_use_entered_price_and_configured_yield_without_picks(self):
        bean=self.bean();self.purchase(bean,2000,3402)
        self.shopify(units=2)
        before=self.c.total();r=self.report()[0]
        self.assertEqual(r['bean_cost_minor'],400) # 200g × 1701 JPY/kg / 85% yield
        self.assertEqual(r['cost_basis'],'estimated');self.assertIn('configured roast yield',r['cost_note'])
        self.assertNotIn('Batch pick missing or changed',r['issues']);self.assertEqual(self.c.total(),before)
        self.assertEqual(len(rows(self.db,'SELECT * FROM fulfillment_picks')),0)

    def test_later_entered_price_can_estimate_unvalued_actual_batch_without_changing_recorded_cost(self):
        from server.profit import sale_cost,estimate_context,batch_costs
        b=self.bean();batch=self.c.batch(green=1000,output=800)
        self.purchase(b,2000,4000,at='2026-11-19T00:00:00Z')
        picks=[{'batch_id':batch,'quantity_mg':100000,'overfill_mg':1000}]
        cost,why,basis,note=sale_cost(picks,batch_costs(self.db),'JPY',100000,'c','2026-11-10T00:00:00Z',estimate_context(self.db))
        self.assertEqual(cost,253);self.assertIsNone(why);self.assertEqual(basis,'estimated');self.assertIn('measured yield',note)
        self.assertNotIn(batch,batch_costs(self.db))

    def test_missing_price_and_foreign_currency_never_generate_estimates(self):
        self.shopify();self.assertIsNone(self.report()[0]['bean_cost_minor'])
        b=self.bean(currency='USD');self.purchase(b)
        r=self.report()[0];self.assertIsNone(r['bean_cost_minor']);self.assertIn('Bean cost currency differs',r['issues'])
