"""Dispatch timing for fresh coffee, future commitments and overdue orders."""
import json,unittest
from types import SimpleNamespace
import test_core
from server.app import Handler,state
from server.db import one,rows
from server.domain import stock_id,movement,stamp
from server.planner import plan
from server.today import customer_roast
from server.imports import fulfillment_pick


class DispatchAllocation(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
        self.db.execute('UPDATE coffees SET brew_days=45,dispatch_days=0,retail_days=14')
        self.batch=self.c.batch(roasted='2026-11-20T03:00:00Z')
        self.bulk=stock_id(self.db,self.batch,'roastery');self.c.order(2,2)
        self.deadline('2026-11-19T03:00:00Z')
    def tearDown(self):self.c.tearDown()
    def deadline(self,value):self.db.execute('UPDATE orders SET due_at=?',(value,))
    def reserve(self,scope=None):
        return self.c.move(scope or self.bulk,'reserve',grams=200,line_id='l',use='dispatch',due_at=one(self.db,'SELECT due_at FROM orders')['due_at'])
    def snapshot(self):return state(self.db,{'id':'test','name':'Test','role':'staff'},SimpleNamespace(configured=lambda:{}))
    def test_zero_dispatch_rest_allocates_fresh_bulk_to_overdue_order(self):
        before=self.snapshot();scope=next(s for s in before['stocks'] if s['id']==self.bulk)
        self.assertFalse(scope['readiness']['brew']['eligible'])
        self.assertTrue(scope['readiness']['dispatch']['eligible'])
        self.assertEqual(before['planner']['rows'][0]['covered_mg'],200000)
        self.reserve()
        move=one(self.db,"SELECT * FROM movements WHERE kind='reserve'")
        payload=json.loads(one(self.db,"SELECT detail FROM audit WHERE action='reserve'")['detail'])
        payload.pop('movement_id')
        result=self.c.runop(movement,payload,'Tester',move['request_id'])
        self.assertTrue(result['duplicate'])
        self.assertEqual(len(rows(self.db,'SELECT * FROM reservations')),1)
        after=self.snapshot();order=after['orders'][0];line=order['lines'][0]
        self.assertEqual(line['status'],'Ready to pack');self.assertEqual(line['missing_mg'],0)
        self.assertEqual(order['due_at'],'2026-11-19T03:00:00Z')
        self.assertEqual(one(self.db,'SELECT due_at FROM reservations')['due_at'],stamp(order['due_at']))
        self.assertEqual(after['customer_roast']['coffees'][0]['tone'],'red')
        self.assertEqual(after['customer_roast']['coffees'][0]['roast_mg'],0)
        self.assertEqual(after['planner']['rows'][0]['covered_mg'],200000)
        self.assertEqual(self.c.total(),850000,'reservation does not deduct stock')
    def test_packed_fresh_coffee_can_allocate_and_be_picked_for_online_order(self):
        self.c.move(self.bulk,'pack',package_id='p',units='2')
        packed=stock_id(self.db,self.batch,'roastery','p');self.reserve(packed)
        self.assertEqual(self.snapshot()['orders'][0]['lines'][0]['status'],'Packed / allocated')
        self.c.order(0,2,updated='2026-11-20T04:00:00Z',fulfillments=[{'id':'f','status':'SUCCESS','createdAt':'2026-11-20T03:00:00Z','lines':[{'line_id':'l','quantity':2}]}])
        self.c.runop(fulfillment_pick,{'fulfillment_id':'f','picks':[{'line_id':'l','stock_id':packed,'grams':200}]},'Tester','dispatch-pick')
        self.assertEqual(self.c.total(),650000)
    def test_future_order_can_reserve_resting_coffee_only_when_dispatch_ready(self):
        p=json.loads(one(self.db,'SELECT policy FROM batches')['policy']);p['dispatch_days']=2
        self.db.execute('UPDATE batches SET policy=?',(json.dumps(p),))
        self.deadline('2026-11-22T02:59:59Z')
        with self.assertRaisesRegex(ValueError,'Resting'):self.reserve()
        self.assertEqual(plan(self.db)['rows'][0]['covered_mg'],0)
        self.deadline('2026-11-22T12:00:00+09:00');self.reserve()
        self.assertEqual(self.snapshot()['orders'][0]['lines'][0]['status'],'Resting')
        self.assertEqual(plan(self.db)['rows'][0]['covered_mg'],200000)
    def test_overdue_order_does_not_bypass_dispatch_rest(self):
        p=json.loads(one(self.db,'SELECT policy FROM batches')['policy']);p['dispatch_days']=2
        self.db.execute('UPDATE batches SET policy=?',(json.dumps(p),))
        with self.assertRaisesRegex(ValueError,'Resting'):self.reserve()
        self.assertEqual(plan(self.db)['rows'][0]['covered_mg'],0)
        self.assertEqual(rows(self.db,'SELECT * FROM reservations'),[])
    def test_overdue_order_checks_freshness_now_and_future_order_at_deadline(self):
        p=json.loads(one(self.db,'SELECT policy FROM batches')['policy']);p['fresh_days']=1
        self.db.execute('UPDATE batches SET policy=?',(json.dumps(p),))
        self.deadline('2026-11-20T04:00:00Z')
        self.db.execute("UPDATE settings SET value=? WHERE key='demo_clock'",(json.dumps('2026-11-22T03:00:00Z'),))
        with self.assertRaisesRegex(ValueError,'Outside freshness'):self.reserve()
        self.assertEqual(plan(self.db)['rows'][0]['covered_mg'],0)
        self.db.execute("UPDATE settings SET value=? WHERE key='demo_clock'",(json.dumps('2026-11-20T03:00:00Z'),))
        self.deadline('2026-11-22T03:00:00Z')
        with self.assertRaisesRegex(ValueError,'Outside freshness'):self.reserve()
    def test_holds_archives_and_unknown_dates_still_block_dispatch(self):
        for field,value,message in [('held',1,'Quality hold'),('archived',1,'Archived'),('roasted_at',None,'timestamp missing')]:
            with self.subTest(field=field):
                before=one(self.db,'SELECT * FROM batches')[field]
                self.db.execute('UPDATE batches SET '+field+'=?',(value,))
                with self.assertRaisesRegex(ValueError,message):self.reserve()
                self.assertEqual(rows(self.db,'SELECT * FROM reservations'),[])
                self.db.execute('UPDATE batches SET '+field+'=?',(before,))
    def test_policy_review_uses_current_dispatch_readiness_for_overdue_reservation(self):
        self.reserve()
        self.c.runop(lambda db:Handler.mutate(None,db,'/api/batch-policy',{'id':self.batch,'held':False,'reason':'Reviewed fresh dispatch'},'Tester',{'role':'admin'},'review'))
        self.assertEqual(rows(self.db,"SELECT * FROM issues WHERE kind='allocation_at_risk'"),[])
    def test_cafe_forecasts_and_unroasted_plans_do_not_get_late_order_timing(self):
        self.db.execute("INSERT INTO demands VALUES ('d','c','brew','2026-11-19T03:00:00Z',200000,'Cafe forecast')")
        with self.assertRaisesRegex(ValueError,'Resting'):
            self.c.move(self.bulk,'reserve',grams=200,demand_id='d',use='brew',due_at='2026-11-19T03:00:00Z')
        self.c.move(self.bulk,'transfer',grams=850,location_id='cafe')
        p=one(self.db,'SELECT policy FROM batches')['policy']
        self.db.execute("INSERT INTO plans VALUES ('scheduled','c','2026-11-20T02:00:00Z',1000000,850000,'planned','Not yet roasted',?)",(p,))
        customer=next(r for r in plan(self.db)['rows'] if r['type']=='line_id')
        self.assertEqual(customer['covered_mg'],0,'an overdue planned roast is not physical stock')
