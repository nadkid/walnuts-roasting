import unittest,json,sqlite3
from server import green
from server.db import transaction,one,rows
from server.domain import create_batch,movement,stock_id,dt
from server.imports import roast_import
import test_core

class GreenStock(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
        self.bean=self.op(green.save_bean,{'name':'Test green','currency':'JPY','coffee_ids':['c']},'bean')['id']
    def tearDown(self):self.c.tearDown()
    def op(self,fn,d,key):return self.c.runop(fn,d,'Staff',key)
    def receipt(self,key='purchase',grams='10000',**extra):
        return self.op(green.receive,{'bean_id':self.bean,'grams':grams,'total':'20000','received_at':'2026-11-01T00:00:00Z','supplier':'Fixture','lot':'A',**extra},key)
    def balance(self):return green.snapshot(self.db)['beans'][0]['quantity_mg']
    def count(self,key='count',grams='8000',**extra):
        return self.op(green.count,{'bean_id':self.bean,'grams':grams,'version':one(self.db,'SELECT version FROM green_beans')['version'],'reason':'Physical opening count',**extra},key)
    def test_purchase_prices_and_duplicate_submit(self):
        self.receipt();self.receipt();self.assertEqual(self.balance(),10000000)
        s=green.snapshot(self.db);self.assertEqual(len(s['events']),1);self.assertEqual(s['beans'][0]['last_price_per_kg'],2000)
        with self.assertRaises(ValueError):self.receipt(grams='9000')
        with self.assertRaises(ValueError):self.receipt('bad',total='1.1')
        self.assertEqual(self.balance(),10000000)
    def test_import_deducts_green_once_and_measured_output_is_separate(self):
        self.receipt();r=self.c.roast_record();self.c.runop(roast_import,r);self.c.runop(roast_import,r)
        self.assertEqual(self.balance(),9000000);self.assertEqual(self.c.total(),850000)
        r['weightGreen']=1200;self.c.runop(roast_import,r);self.assertEqual(self.balance(),9000000)
        self.assertTrue(any(i['kind']=='source_edit' for i in rows(self.db,'SELECT * FROM issues')))
    def test_profiles_share_one_bean_and_scheduled_is_only_projected(self):
        self.db.execute("INSERT INTO coffees SELECT 'espresso',name,'Espresso',7,7,7,90,8500,1 FROM coffees WHERE id='c'")
        self.op(green.save_bean,{'id':self.bean,'version':0,'name':'Test green','currency':'JPY','coffee_ids':['c','espresso']},'link')
        self.receipt();self.c.batch();self.op(create_batch,{'coffee_id':'espresso','green_g':'1200','output_g':'1000','roasted_at':'2026-11-05T02:00:00Z'},'espresso')
        self.db.execute("INSERT INTO plans VALUES ('p','espresso','2026-11-22T01:00:00Z',1200000,1000000,'planned','test','{}')")
        b=green.snapshot(self.db)['beans'][0];self.assertEqual(b['quantity_mg'],7800000);self.assertEqual(b['planned_mg'],1200000);self.assertEqual(b['after_plans_mg'],6600000)
    def test_history_does_not_deduct_but_new_roasts_can_show_shortfall(self):
        self.c.runop(create_batch,{'coffee_id':'c','green_g':'1000','output_g':'850','roasted_at':'2026-10-01T00:00:00Z'},'Tester','historical',None,True)
        self.assertEqual(self.balance(),0);self.c.batch();self.assertEqual(self.balance(),-1000000)
    def test_late_import_before_opening_count_is_already_counted(self):
        self.count();self.c.runop(roast_import,self.c.roast_record());self.assertEqual(self.balance(),8000000)
        self.db.execute("UPDATE settings SET value=? WHERE key='demo_clock'",(json.dumps('2026-11-21T03:00:00Z'),))
        self.op(create_batch,{'coffee_id':'c','green_g':'1200','output_g':'1000','roasted_at':'2026-11-21T02:00:00Z'},'new-roast')
        self.assertEqual(self.balance(),6800000)
        self.count('recount','7000');self.assertEqual(self.balance(),7000000)
    def test_counts_reject_stale_version_and_duplicate_does_not_reset_again(self):
        v=one(self.db,'SELECT version FROM green_beans')['version'];self.receipt()
        with self.assertRaises(ValueError):self.count(version=v)
        d={'bean_id':self.bean,'grams':'9000','version':one(self.db,'SELECT version FROM green_beans')['version'],'reason':'Count'}
        self.op(green.count,d,'same');self.op(green.count,d,'same');self.assertEqual(self.balance(),9000000)
    def test_link_reconciles_pending_roasts_once_preserving_physical_count(self):
        self.db.execute('DELETE FROM green_coffee_links');self.c.batch();self.assertEqual(len(green.snapshot(self.db)['unlinked']),1)
        self.count();v=one(self.db,'SELECT version FROM green_beans')['version']
        self.op(green.save_bean,{'id':self.bean,'version':v,'name':'Linked','currency':'JPY','coffee_ids':['c']},'relink')
        self.assertEqual(self.balance(),8000000);self.assertEqual(len(green.snapshot(self.db)['unlinked']),0)
        self.assertEqual(len(rows(self.db,"SELECT * FROM green_events WHERE kind='roast'")),1)
    def test_production_reversal_restores_green_once(self):
        self.receipt();b=self.c.batch();m=one(self.db,"SELECT * FROM movements WHERE kind='production'")
        self.op(movement,{'kind':'reverse','reversal_of':m['id'],'reason':'Wrong batch'},'undo')
        self.assertEqual(self.balance(),10000000);self.assertEqual(self.c.total(),0)
        with self.assertRaises(sqlite3.IntegrityError):self.op(movement,{'kind':'reverse','reversal_of':m['id'],'reason':'Wrong batch'},'undo-again')
        self.assertEqual(self.balance(),10000000)
    def test_reversed_unlinked_roast_is_not_deducted_when_linked_later(self):
        self.db.execute('DELETE FROM green_coffee_links');self.c.batch();m=one(self.db,"SELECT * FROM movements WHERE kind='production'")
        self.op(movement,{'kind':'reverse','reversal_of':m['id'],'reason':'Wrong batch'},'undo')
        self.op(green.save_bean,{'id':self.bean,'version':0,'name':'Linked','currency':'JPY','coffee_ids':['c']},'relink')
        self.assertEqual(self.balance(),0);self.assertEqual(len(green.snapshot(self.db)['unlinked']),0)
    def test_purchase_reversal_preserves_count_baseline_and_immutable_history(self):
        self.receipt();e=one(self.db,'SELECT * FROM green_events');self.count()
        self.op(green.reverse,{'event_id':e['id'],'reason':'Duplicate receipt'},'reverse')
        self.assertEqual(self.balance(),8000000);self.assertIsNone(green.snapshot(self.db)['beans'][0]['last_price_per_kg'])
        with self.assertRaises(sqlite3.IntegrityError):self.op(green.reverse,{'event_id':e['id'],'reason':'Again'},'reverse2')
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM green_events')
    def test_currency_precision_and_invalid_future_purchase(self):
        with self.assertRaises(ValueError):self.receipt('future',received_at='2026-11-21T00:00:00Z')
        self.assertEqual(green.money('12.34','USD'),1234)
        with self.assertRaises(ValueError):green.money('12.345','USD')
        with self.assertRaises(ValueError):self.receipt('negative',grams='-1')
        self.assertEqual(self.balance(),0)
    def test_new_bean_and_first_priced_receipt_save_together_once(self):
        d={'name':'New purchase bean','currency':'JPY','coffee_ids':[],
           'purchase':{'grams':'30000','received_at':'2026-11-19T03:00:00Z','price_basis':'per_kg','price_per_kg':'2400','supplier':'Fixture supplier','reference':'INV-1'}}
        result=self.op(green.save_bean,d,'combined');self.op(green.save_bean,d,'combined')
        e=one(self.db,'SELECT * FROM green_events WHERE bean_id=?',(result['id'],))
        self.assertEqual(e['delta_mg'],30000000);self.assertEqual(e['total_minor'],72000);self.assertEqual(e['reference'],'INV-1')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM green_events WHERE bean_id=?',(result['id'],)).fetchone()[0],1)
    def test_invalid_first_purchase_rolls_back_bean_and_receipt(self):
        before=self.db.execute('SELECT COUNT(*) FROM green_beans').fetchone()[0]
        with self.assertRaises(ValueError):
            self.op(green.save_bean,{'name':'Invalid first receipt','currency':'JPY','coffee_ids':[], 'purchase':{'grams':'1000','total':'1.2','received_at':'2026-11-19T00:00:00Z'}},'invalid-combined')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM green_beans').fetchone()[0],before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM green_events').fetchone()[0],0)
    def test_price_per_kg_rounding_and_total_price_remain_linked(self):
        self.receipt('unit-price',grams='2500',price_basis='per_kg',price_per_kg='100.2')
        e=one(self.db,'SELECT * FROM green_events');self.assertEqual(e['total_minor'],251)
        self.assertEqual(e['bean_id'],self.bean)
        self.receipt('total-price',grams='500',price_basis='total',total='123',price_per_kg='999')
        self.assertEqual(one(self.db,"SELECT * FROM green_events ORDER BY id DESC LIMIT 1")['total_minor'],123)
        with self.assertRaises(ValueError):self.receipt('invalid-unit',price_basis='per_kg',price_per_kg='-1')
