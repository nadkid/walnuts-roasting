import unittest,json,os
from unittest.mock import patch
from server.db import rows,one,transaction,settings
from server.domain import stock_id,dt,movement
from server import products,square
from server.adapters import Scheduler,SyncError,Shopify
import test_core

class SquareSales(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
        products.seed_shopify(self.db)
        self.pid=one(self.db,'SELECT id FROM sale_products')['id']
        products.upsert(self.db,'square',{'id':'sq-100','name':'Test coffee','variation':'100g','sku':'DIFFERENT-SQUARE-SKU'})
        self.map('sq-100')
        self.db.execute("INSERT INTO square_locations VALUES ('shop','Fixture shop',1)")
        self.op(square.configure,{'location_id':'shop','start_at':'2026-11-01T00:00:00Z','enabled':True})
    def tearDown(self):self.c.tearDown()
    def op(self,fn,*args):
        with transaction(self.db):return fn(self.db,*args,'Tester')
    def map(self,id,kind='coffee'):
        v=one(self.db,"SELECT * FROM sale_catalog WHERE source='square' AND external_id=?",(id,))
        self.c.runop(products.approve,{'source':'square','external_id':id,'version':v['version'],'kind':kind,'product_id':self.pid},'Tester','map:'+id+':'+str(v['version']))
    def wall(self,day=5,units=4,overfill=0):
        b=self.c.batch(roasted=f'2026-11-{day:02}T00:00:00Z');s=stock_id(self.db,b,'roastery')
        self.c.move(s,'pack',units=str(units),package_id='p',location_id='wall',overfill_g=overfill,reason='Fixture pack')
        return stock_id(self.db,b,'wall','p')
    def order(self,id='sale',qty='2',version=1,**extra):
        return {'id':id,'location_id':'shop','version':version,'state':'COMPLETED','created_at':'2026-11-10T00:00:00Z','updated_at':'2026-11-10T00:00:00Z','closed_at':'2026-11-10T00:00:00Z','line_items':[{'uid':'line','catalog_object_id':'sq-100','name':'Test coffee','quantity':qty,'total_money':{'amount':3000,'currency':'JPY'}}],**extra}
    def ingest(self,r):
        with transaction(self.db):square.import_order(self.db,r);square.retry_sales(self.db)
    def wall_mg(self):return self.db.execute("SELECT COALESCE(SUM(quantity_mg),0) FROM stocks WHERE location_id='wall'").fetchone()[0]
    def status(self,id='sale'):return one(self.db,'SELECT status FROM square_sales WHERE id=?',(id,))['status']
    def test_shared_product_despite_different_platform_ids_and_skus(self):
        mappings=rows(self.db,'SELECT * FROM sale_catalog');self.assertEqual(len({v['product_id'] for v in mappings}),1)
        self.assertEqual({v['source'] for v in mappings},{'shopify','square'})
    def test_duplicate_receipts_and_poll_replay_deduct_once(self):
        self.wall();r=self.order();self.ingest(r);self.ingest(r)
        self.assertEqual(self.wall_mg(),200000);self.assertEqual(self.status(),'posted')
        self.assertEqual(len(rows(self.db,'SELECT * FROM square_sale_picks')),1)
    def test_oldest_batch_first_across_two_batches_and_overfill(self):
        old=self.wall(5,4,2);new=self.wall(6,4,2);self.ingest(self.order(qty='6'))
        ps=rows(self.db,'SELECT * FROM square_sale_picks ORDER BY id');self.assertEqual([p['stock_id'] for p in ps],[old,new]);self.assertEqual([p['quantity_mg'] for p in ps],[400000,200000]);self.assertEqual([p['overfill_mg'] for p in ps],[2000,1000]);self.assertEqual(self.wall_mg(),200000)
    def test_no_wall_stock_does_not_consume_roastery_or_cafe(self):
        self.c.batch();before=self.c.total();self.ingest(self.order());self.assertEqual(self.status(),'pending');self.assertEqual(self.c.total(),before)
    def test_missing_mapping_keeps_all_lines_atomic(self):
        self.wall();r=self.order();r['line_items'].append({'uid':'other','catalog_object_id':'unknown','name':'Drink','quantity':'1'})
        self.ingest(r);self.assertEqual(self.wall_mg(),400000);self.map('unknown','noncoffee')
        with transaction(self.db):square.retry_sales(self.db)
        self.assertEqual(self.wall_mg(),200000)
    def test_reservations_quality_holds_and_immature_stock_are_protected(self):
        old=self.wall(5);new=self.wall(6);self.c.order();self.c.move(old,'reserve',grams=300,line_id='l',use='dispatch',due_at='2026-11-25T03:00:00Z')
        self.ingest(self.order());self.assertEqual(one(self.db,'SELECT quantity_mg FROM stocks WHERE id=?',(old,))['quantity_mg'],300000)
        self.db.execute('UPDATE batches SET held=1 WHERE id=(SELECT batch_id FROM stocks WHERE id=?)',(new,));self.ingest(self.order('sale2',qty='3'));self.assertEqual(self.status('sale2'),'pending')
        self.wall(19);self.ingest(self.order('immature',qty='5'));self.assertEqual(self.status('immature'),'pending')
    def test_insufficient_stock_multiple_lines_has_no_partial_deduction(self):
        self.wall();r=self.order(qty='3');r['line_items'].append({**r['line_items'][0],'uid':'second','quantity':'3'});self.ingest(r)
        self.assertEqual(self.wall_mg(),400000);self.assertEqual(self.status(),'pending');self.assertEqual(len(rows(self.db,'SELECT * FROM square_sale_picks')),0)
    def test_preview_and_cutover_do_not_deduct(self):
        self.wall();self.op(square.configure,{'location_id':'shop','start_at':'2026-11-01T00:00:00Z','enabled':False});self.ingest(self.order());self.assertEqual(self.status(),'preview');self.assertEqual(self.wall_mg(),400000)
        self.op(square.configure,{'location_id':'shop','start_at':'2026-11-11T00:00:00Z','enabled':True});self.ingest(self.order());self.assertEqual(self.status(),'before_start');self.assertEqual(self.wall_mg(),400000)
    def test_late_receipt_before_wall_count_needs_reconciliation(self):
        s=self.wall();v=one(self.db,'SELECT version FROM stocks WHERE id=?',(s,))['version'];self.c.move(s,'count',count_g=300,version=v,reason='Count after sale')
        self.ingest(self.order());self.assertEqual(self.status(),'pending');self.assertEqual(self.wall_mg(),300000)
        self.op(square.acknowledge,{'id':'sale','reason':'Included in measured wall count'})
        self.ingest(self.order(version=2));self.assertEqual(self.status(),'acknowledged');self.assertEqual(self.wall_mg(),300000)
    def test_refunds_and_source_edits_preserve_original_picks(self):
        self.wall();self.ingest(self.order());self.ingest(self.order(qty='3',version=2));self.assertEqual(self.status(),'source_review');self.assertEqual(self.wall_mg(),200000)
        self.ingest(self.order(qty='3',version=3,returns=[{'uid':'refund'}]));self.assertEqual(self.wall_mg(),200000)
        self.assertTrue(any(i['kind']=='return_review' for i in rows(self.db,'SELECT * FROM issues')))
    def test_stale_source_version_is_ignored(self):
        self.wall();self.ingest(self.order(version=5));self.ingest(self.order(qty='3',version=1));self.assertEqual(self.status(),'posted');self.assertEqual(self.wall_mg(),200000)
    def test_fractional_bags_wrong_location_and_fulfillment_need_review(self):
        self.wall()
        for id,extra in [('fraction',{'qty':'1.5'}),('elsewhere',{'location_id':'other'}),('pickup',{'fulfillments':[{'type':'PICKUP'}]})]:
            self.ingest(self.order(id,**extra));self.assertEqual(self.status(id),'pending')
        self.assertEqual(self.wall_mg(),400000)
    def test_completed_in_store_fulfillment_deducts_once(self):
        self.wall();r=self.order(qty='1',fulfillments=[{'type':'IN_STORE','state':'COMPLETED'}])
        self.ingest(r);self.ingest(r)
        self.assertEqual(self.status(),'posted');self.assertEqual(self.wall_mg(),300000)
        self.assertEqual(len(rows(self.db,'SELECT * FROM square_sale_picks')),1)
    def test_incomplete_unknown_and_remote_fulfillments_still_need_review(self):
        self.wall()
        cases=[{'type':'IN_STORE','state':s} for s in (None,'PROPOSED','RESERVED','PREPARED','CANCELED','FAILED')]
        cases += [{'type':t,'state':'COMPLETED'} for t in ('PICKUP','SHIPMENT','DELIVERY','DIGITAL','UNKNOWN',None)]
        cases += [[{'type':'IN_STORE','state':'COMPLETED'},{'type':'PICKUP','state':'COMPLETED'}]]
        for n,case in enumerate(cases):
            with self.subTest(fulfillment=case):
                id='fulfillment-'+str(n)
                self.ingest(self.order(id,qty='1',fulfillments=case if isinstance(case,list) else [case]))
                self.assertEqual(self.status(id),'pending');self.assertEqual(self.wall_mg(),400000)
    def test_legacy_fulfillment_flag_requires_reimport_before_deduction(self):
        self.wall();r=self.order(qty='1',fulfillments=[{'type':'IN_STORE','state':'COMPLETED'}])
        with transaction(self.db):square.import_order(self.db,r)
        legacy=json.loads(one(self.db,'SELECT payload FROM square_sales')['payload']);legacy.pop('fulfillments')
        self.db.execute('UPDATE square_sales SET payload=?',(json.dumps(legacy),))
        with transaction(self.db):square.retry_sales(self.db)
        self.assertEqual(self.status(),'pending');self.assertEqual(self.wall_mg(),400000)
        self.ingest(r);self.ingest(r)
        self.assertEqual(self.status(),'posted');self.assertEqual(self.wall_mg(),300000)
    def test_completed_in_store_sale_respects_start_and_does_not_backfill_earlier_sales(self):
        self.wall();self.op(square.configure,{'location_id':'shop','start_at':'2026-11-11T00:00:00Z','enabled':True})
        r=self.order(qty='1',fulfillments=[{'type':'IN_STORE','state':'COMPLETED'}])
        self.ingest(r)
        self.ingest(self.order('earlier',qty='1',closed_at='2026-11-09T23:59:59Z',fulfillments=[{'type':'IN_STORE','state':'COMPLETED'}]))
        self.assertEqual(self.status(),'before_start');self.assertEqual(self.wall_mg(),400000)
        self.op(square.configure,{'location_id':'shop','start_at':'2026-11-10T00:00:00Z','enabled':True})
        self.ingest(r)
        self.assertEqual(self.status(),'posted');self.assertEqual(self.status('earlier'),'before_start');self.assertEqual(self.wall_mg(),300000)
    def test_completed_in_store_return_is_not_automatically_deducted(self):
        self.wall();self.ingest(self.order(fulfillments=[{'type':'IN_STORE','state':'COMPLETED'}],returns=[{'uid':'return'}]))
        self.assertEqual(self.status(),'pending');self.assertEqual(self.wall_mg(),400000)
    def test_product_weight_change_blocks_deduction_until_review(self):
        self.wall();products.upsert(self.db,'square',{'id':'sq-100','name':'Renamed coffee','variation':'150g'});self.ingest(self.order());self.assertEqual(self.status(),'pending')
        with self.assertRaises(ValueError):self.map('sq-100')
        self.assertEqual(self.wall_mg(),400000)
    def test_name_change_preserves_link_and_does_not_bump_unchanged_versions(self):
        products.upsert(self.db,'square',{'id':'sq-100','name':'New label','variation':'100g'})
        v=one(self.db,"SELECT * FROM sale_catalog WHERE source='square'");products.upsert(self.db,'square',{'id':'sq-100','name':'New label','variation':'100g'})
        n=one(self.db,"SELECT * FROM sale_catalog WHERE source='square'");self.assertEqual(v['version'],n['version']);self.assertEqual(n['product_id'],self.pid);self.assertFalse(n['review'])
    def test_suggestions_are_never_automatically_approved_and_sizes_stay_distinct(self):
        products.upsert(self.db,'square',{'id':'new','name':'Test coffee','variation':'100g'})
        products.upsert(self.db,'square',{'id':'different','name':'Test coffee','variation':'150g'})
        items=products.snapshot(self.db)['catalog'];a=next(i for i in items if i['external_id']=='new');b=next(i for i in items if i['external_id']=='different')
        self.assertTrue(a['suggestions']);self.assertEqual(a['kind'],'unresolved');self.assertEqual(b['suggestions'],[])
    def test_customer_and_payment_details_are_not_stored(self):
        self.ingest(self.order(customer_id='SECRET-CUSTOMER',tenders=[{'card_details':'SECRET-CARD'}],customer={'email':'SECRET-EMAIL'},fulfillments=[{'type':'IN_STORE','state':'COMPLETED','recipient':{'email':'SECRET-RECIPIENT'},'pickup_details':{'note':'SECRET-NOTE'}}]))
        self.assertNotIn('SECRET',one(self.db,'SELECT payload FROM square_sales')['payload'])
    def test_square_sale_cannot_be_generically_reversed(self):
        self.wall();self.ingest(self.order());m=one(self.db,"SELECT id FROM movements WHERE kind='square_sale'")
        with self.assertRaises(ValueError):self.c.runop(movement,{'kind':'reverse','reversal_of':m['id'],'reason':'Refund'},'Tester','reverse-square')
    def test_failed_sync_does_not_advance_watermark_and_preview_does_not_post(self):
        def orders(*args):yield self.order();raise SyncError('Interrupted')
        with patch.dict(os.environ,{'SQUARE_ACCESS_TOKEN':'fixture-only'}),patch.object(square.Square,'categories',return_value=[{'id':'beans','category_data':{'name':'Beans'}}]),patch.object(square.Square,'catalog',return_value=iter([{'id':'sq-100','name':'Test coffee','variation':'100g','category_ids':['beans']}])),patch.object(square.Square,'locations',return_value=[{'id':'shop','name':'Fixture','status':'ACTIVE'}]),patch.object(square.Square,'orders',side_effect=orders):
            result=Scheduler(self.c.path).sync('square')
        self.assertEqual(result['status'],'error');self.assertNotIn('square_watermark',settings(self.db));self.assertEqual(self.status(),'preview')

class SquareClient(unittest.TestCase):
    def test_pagination_version_authorization_and_no_token_in_url(self):
        with patch.dict(os.environ,{'SQUARE_ACCESS_TOKEN':'fixture-token','SQUARE_ENVIRONMENT':'production'}),patch('server.square.request_json',side_effect=[{'objects':[{'id':'1'}],'cursor':'next'},{'objects':[{'id':'2'}]}]) as req:
            self.assertEqual(len(list(square.Square().pages('/catalog/list?types=ITEM','objects'))),2)
            self.assertIn('cursor=next',req.call_args.args[0]);self.assertNotIn('fixture-token',req.call_args.args[0]);self.assertEqual(req.call_args.args[1]['Square-Version'],'2026-09-16')
    def test_order_query_uses_updated_time_and_original_query_on_each_page(self):
        with patch.dict(os.environ,{'SQUARE_ACCESS_TOKEN':'fixture-token'}),patch('server.square.request_json',side_effect=[{'orders':[],'cursor':'next'},{'orders':[]}]) as req:
            list(square.Square().orders('shop','2026-11-05T00:00:00Z'))
            self.assertEqual(req.call_args.args[2]['location_ids'],['shop']);self.assertIn('updated_at',req.call_args.args[2]['query']['filter']['date_time_filter']);self.assertEqual(req.call_args.args[2]['cursor'],'next')
    def test_catalog_flattens_item_variations_with_parent_name(self):
        obj={'id':'item','type':'ITEM','item_data':{'name':'Coffee','variations':[{'id':'variation','item_variation_data':{'item_id':'item','name':'150g','sku':'SQ150'}}]}}
        with patch.dict(os.environ,{'SQUARE_ACCESS_TOKEN':'fixture-token'}),patch('server.square.request_json',return_value={'objects':[obj]}):
            item=list(square.Square().catalog())[0];self.assertEqual(item['name'],'Coffee');self.assertEqual(item['variation'],'150g');self.assertEqual(item['id'],'variation')
    def test_weight_normalization(self):
        for x in ['150g','150 g','０.１５kg','150グラム']:
            self.assertEqual(products.detected_weight(x),150000)
        self.assertIsNone(products.detected_weight('100g and 150g'))

class BagSizes(unittest.TestCase):
    def test_fixed_bag_sizes_100_150_250_deduct_their_own_stock(self):
        case=test_core.Core();case.setUp()
        try:
            db=case.db;db.execute("INSERT INTO square_locations VALUES ('shop','Fixture',1)")
            with transaction(db):square.configure(db,{'location_id':'shop','start_at':'2026-11-01T00:00:00Z','enabled':True},'Tester')
            for size in (100,150,250):
                with self.subTest(size=size):
                    pid='size'+str(size);db.execute('INSERT INTO packages VALUES (?,?,?)',(pid,str(size)+'g',size*1000))
                    b=case.batch();case.move(stock_id(db,b,'roastery'),'pack',package_id=pid,units='2',location_id='wall')
                    with transaction(db):
                        product=products.product(db,'c',pid);vid='square'+pid;products.upsert(db,'square',{'id':vid,'name':'Test coffee','variation':str(size)+'g'})
                        v=one(db,"SELECT * FROM sale_catalog WHERE source='square' AND external_id=?",(vid,))
                        products.approve(db,{'source':'square','external_id':vid,'version':v['version'],'kind':'coffee','product_id':product},'Tester','map'+pid)
                        square.import_order(db,{'id':pid,'location_id':'shop','version':1,'state':'COMPLETED','closed_at':'2026-11-10T00:00:00Z','updated_at':'2026-11-10T00:00:00Z','line_items':[{'uid':'line','catalog_object_id':vid,'name':'Test','quantity':'2'}]});square.retry_sales(db)
                    pick=one(db,'SELECT quantity_mg FROM square_sale_picks WHERE sale_id=?',(pid,));self.assertEqual(pick['quantity_mg'],2*size*1000)
        finally:case.tearDown()


class BeansCategory(unittest.TestCase):
    def setUp(self):
        self.case=SquareSales();self.case.setUp();self.db=self.case.db
        self.db.execute("UPDATE settings SET value='\"beans\"' WHERE key='square_category_id'")
        products.upsert(self.db,'square',{'id':'latte','name':'Café latte','variation':'Hot'})
        self.db.execute("UPDATE sale_catalog SET in_scope=0 WHERE source='square' AND external_id='latte'")
    def tearDown(self):self.case.tearDown()
    def test_mixed_receipt_deducts_only_beans_and_displays_only_bean_lines(self):
        self.case.wall();r=self.case.order();r['line_items'].append({'uid':'drink','name':'Café latte','catalog_object_id':'latte','quantity':'2'})
        self.case.ingest(r);self.assertEqual(self.case.wall_mg(),200000);self.assertEqual(self.case.status(),'posted')
        shown=square.snapshot(self.db)['sales'][0]['receipt']['line_items'];self.assertEqual(len(shown),1);self.assertEqual(shown[0]['catalog_object_id'],'sq-100')
    def test_drink_only_receipt_is_not_imported_or_listed_for_mapping(self):
        r=self.case.order();r['line_items']=[{'uid':'drink','name':'Café latte','catalog_object_id':'latte','quantity':'1'}]
        self.case.ingest(r);self.assertEqual(len(square.snapshot(self.db)['sales']),0)
        self.assertFalse(any(i['external_id']=='latte' for i in products.snapshot(self.db)['catalog']))
    def test_old_nonbean_preview_is_archived_without_touching_stock(self):
        self.db.execute("UPDATE settings SET value='null' WHERE key='square_category_id'")
        r=self.case.order();r['line_items']=[{'uid':'drink','name':'Café latte','catalog_object_id':'latte','quantity':'1'}]
        with transaction(self.db):square.import_order(self.db,r)
        self.db.execute("UPDATE settings SET value='\"beans\"' WHERE key='square_category_id'")
        with transaction(self.db):square.retry_sales(self.db)
        self.assertEqual(self.case.status(),'outside_scope');self.assertEqual(square.snapshot(self.db)['sales'],[])
