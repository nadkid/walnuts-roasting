import unittest
from server import green
from server.db import one,rows
from server.domain import add_roasted_stock,movement,stock,stock_id,eligibility
import test_core

class RoastedStock(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
        self.bean=self.op(green.save_bean,{'name':'Green fixture','coffee_ids':['c']},'bean')['id']
        self.op(green.receive,{'bean_id':self.bean,'grams':'10000','received_at':'2026-11-01T00:00:00Z'},'receipt')
    def tearDown(self):self.c.tearDown()
    def op(self,fn,d,key):return self.c.runop(fn,d,'Staff',key)
    def add(self,key='found',**extra):
        return self.op(add_roasted_stock,{'coffee_id':'c','grams':'321.125','location_id':'roastery','reason':'Found a previously uncounted container','roasted_at':'2026-11-05T10:00:00+09:00',**extra},key)
    def green_balance(self):return green.snapshot(self.db)['beans'][0]['quantity_mg']
    def test_new_stock_has_no_production_or_green_deduction_even_after_reconciliation(self):
        r=self.add();b=one(self.db,'SELECT * FROM batches WHERE id=?',(r['batch_id'],))
        self.assertEqual(self.c.total(),321125);self.assertEqual(self.green_balance(),10000000)
        self.assertEqual((b['green_mg'],b['output_mg'],b['history_only']),(0,0,1))
        self.assertTrue(eligibility(b,'brew','2026-11-20T03:00:00Z')[0])
        self.assertEqual(rows(self.db,"SELECT * FROM movements WHERE kind='production'"),[])
        self.c.runop(green.reconcile,'Staff');self.assertEqual(green.snapshot(self.db)['unlinked'],[])
        self.assertEqual(self.green_balance(),10000000)
        self.assertEqual(one(self.db,"SELECT action FROM audit WHERE action='stock_addition'")['action'],'stock_addition')
    def test_replay_does_not_add_again_and_changed_request_is_rejected(self):
        first=self.add();again=self.add()
        self.assertTrue(again['duplicate']);self.assertEqual(first['batch_id'],again['batch_id']);self.assertEqual(first['stock_id'],again['stock_id'])
        self.assertEqual(self.c.total(),321125)
        with self.assertRaises(ValueError):self.add(grams='500')
        self.assertEqual(self.c.total(),321125)
    def test_existing_depleted_scope_can_be_restored_without_another_roast(self):
        batch=self.c.batch(output=800);scope=stock_id(self.db,batch,'roastery')
        self.c.move(scope,'pack',package_id='p',units='8',location_id='wall')
        self.assertEqual(stock(self.db,scope)['quantity_mg'],0)
        before=self.green_balance()
        result=self.add(batch_id=batch,grams='50')
        self.assertEqual(result['stock_id'],scope);self.assertEqual(stock(self.db,scope)['quantity_mg'],50000)
        self.assertEqual(self.c.total(),850000);self.assertEqual(self.green_balance(),before)
        self.assertEqual(len(rows(self.db,'SELECT * FROM batches')),1)
        self.assertEqual(one(self.db,'SELECT output_mg FROM batches')['output_mg'],800000)
    def test_packaged_addition_and_overfill_move_and_count_correctly(self):
        r=self.add(package_id='p',units='3',overfill_g='3.003',location_id='wall')
        s=stock(self.db,r['stock_id']);self.assertEqual(s['quantity_mg'],300000);self.assertEqual(s['overfill_mg'],3003)
        self.c.move(s['id'],'transfer',grams=100,location_id='packing')
        self.assertEqual(self.c.total(),303003)
        self.c.move(s['id'],'count',count_g=0,version=stock(self.db,s['id'])['version'],reason='No bags remaining')
        self.assertEqual(stock(self.db,s['id'])['quantity_mg']+stock(self.db,s['id'])['overfill_mg'],0)
        self.assertEqual(self.c.total(),101001);self.assertEqual(self.green_balance(),10000000)
    def test_unknown_date_stays_unavailable_and_metadata_can_be_reviewed(self):
        r=self.add(roasted_at=None);b=one(self.db,'SELECT * FROM batches')
        for use in ('brew','dispatch','retail'):self.assertFalse(eligibility(b,use,'2026-11-20T03:00:00Z')[0])
        self.assertIsNone(b['roasted_at']);self.assertEqual(self.green_balance(),10000000)
    def test_existing_quality_hold_and_policy_are_preserved(self):
        batch=self.c.batch();self.db.execute("UPDATE batches SET held=1,hold_reason='Cupping review' WHERE id=?",(batch,))
        original=one(self.db,'SELECT * FROM batches WHERE id=?',(batch,))
        self.add(batch_id=batch,grams=50)
        current=one(self.db,'SELECT * FROM batches WHERE id=?',(batch,))
        self.assertEqual(current['policy'],original['policy']);self.assertEqual(current['held'],1)
        self.assertFalse(eligibility(current,'brew','2026-11-20T03:00:00Z')[0])
    def test_invalid_entries_roll_back_everything(self):
        cases=[{'grams':'0'},{'grams':'-1'},{'grams':'0.0001'},{'reason':'  '},{'roasted_at':'2026-12-01T00:00:00Z'},
               {'package_id':'p','units':'1.5'},{'package_id':'p','units':'0'},{'package_id':'p','units':'2','overfill_g':'-1'},
               {'overfill_g':'2'},{'location_id':'missing'},{'coffee_id':'missing'},{'package_id':'missing','units':'1'}]
        for i,payload in enumerate(cases):
            with self.subTest(payload=payload):
                with self.assertRaises((ValueError,KeyError)):self.add('invalid'+str(i),**payload)
                self.assertEqual(self.c.total(),0);self.assertEqual(rows(self.db,'SELECT * FROM batches'),[])
        self.assertEqual(self.green_balance(),10000000)
    def test_archived_batch_rejects_addition(self):
        batch=self.c.batch();self.db.execute('UPDATE batches SET archived=1 WHERE id=?',(batch,))
        before=self.c.total()
        with self.assertRaises(ValueError):self.add(batch_id=batch)
        self.assertEqual(self.c.total(),before)
    def test_addition_is_reversible_and_does_not_return_green(self):
        r=self.add();self.op(movement,{'kind':'reverse','reversal_of':r['movement_id'],'reason':'Duplicate physical container'},'undo')
        self.assertEqual(self.c.total(),0);self.assertEqual(self.green_balance(),10000000)
    def test_recount_increase_and_reservations_remain_protected(self):
        r=self.add();s=stock(self.db,r['stock_id']);self.c.order(remaining=2,quantity=2)
        self.c.reserve(s['id'],grams=200)
        self.c.move(s['id'],'count',count_g=500,version=s['version'],reason='Measured all containers')
        self.assertEqual(self.c.total(),500000);self.assertEqual(self.green_balance(),10000000)
        with self.assertRaises(ValueError):self.c.move(s['id'],'count',count_g=100,version=stock(self.db,s['id'])['version'],reason='Incorrect below allocated stock')
        self.assertEqual(self.c.total(),500000)
