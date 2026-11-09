import unittest
from types import SimpleNamespace
import test_core
from server.app import state
from server.db import one,rows
from server.domain import stock_id
from server.planner import plan
from server.today import customer_roast


class OrderStockLocation(unittest.TestCase):
    def setUp(self):
        self.c=test_core.Core();self.c.setUp();self.db=self.c.db
        self.batch=self.c.batch();self.bulk=stock_id(self.db,self.batch,'roastery');self.c.order()
    def tearDown(self):self.c.tearDown()
    def tile(self):return customer_roast(self.db)['coffees'][0]
    def order_line(self):
        s=state(self.db,{'id':'test','name':'Test','role':'admin'},SimpleNamespace(configured=lambda:{}))
        return next(o for o in s['orders'] if o['id']=='o')['lines'][0]
    def legacy_outside_allocation(self,location='cafe'):
        self.c.reserve(self.bulk,200)
        r=one(self.db,'SELECT * FROM reservations')
        # An existing reservation may already have been packed into another location.
        self.c.move(self.bulk,'pack_reserved',reservation_id=r['id'],location_id=location)
        return one(self.db,'SELECT * FROM reservations')
    def test_today_and_order_plan_use_only_roastery_stock(self):
        for location,grams in [('cafe',300),('wall',200),('packing',100)]:
            self.c.move(self.bulk,'transfer',grams=grams,location_id=location)
        before=self.db.total_changes
        self.assertEqual(self.tile()['roast_mg'],750000,'only 250g is still at the roastery')
        p=next(r for r in plan(self.db)['rows'] if r['type']=='line_id')
        self.assertEqual(p['covered_mg'],200000,'order planning can cover only two whole bags from roastery stock')
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.c.total(),850000)
        self.c.move(stock_id(self.db,self.batch,'cafe'),'transfer',grams=100,location_id='roastery')
        self.assertEqual(self.tile()['roast_mg'],650000,'coverage returns only after an actual transfer back')
    def test_packed_floor_stock_does_not_cover_customer_orders(self):
        self.c.move(self.bulk,'pack',package_id='p',units='4',location_id='wall')
        self.c.move(self.bulk,'transfer',grams=450,location_id='cafe')
        self.assertEqual(self.tile()['roast_mg'],1000000)
        self.assertEqual(plan(self.db)['rows'][0]['covered_mg'],0)
        self.c.move(stock_id(self.db,self.batch,'wall','p'),'transfer',grams=200,location_id='roastery')
        self.assertEqual(self.tile()['roast_mg'],800000)
        self.assertEqual(plan(self.db)['rows'][0]['covered_mg'],200000)
    def test_existing_outside_reservations_stay_visible_but_do_not_count(self):
        reservation=self.legacy_outside_allocation()
        before=self.db.total_changes
        line=self.order_line()
        self.assertEqual(line['allocated_mg'],0);self.assertEqual(line['missing_mg'],1000000)
        self.assertEqual(line['excluded_allocation_mg'],200000)
        self.assertEqual(line['status'],'Allocation outside roastery')
        self.assertEqual(line['allocations'][0]['location_id'],'cafe')
        t=self.tile();self.assertEqual(t['roast_mg'],350000)
        self.assertTrue(any('outside the roastery' in n for n in t['notes']))
        p=plan(self.db)['rows'][0];self.assertEqual(p['covered_mg'],600000)
        self.assertTrue(any('outside the roastery' in n for n in p['warnings']))
        self.assertEqual(one(self.db,'SELECT * FROM reservations')['id'],reservation['id'])
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.c.total(),850000)
    def test_new_customer_reservations_reject_every_other_location(self):
        for location in ('cafe','wall','packing'):
            with self.subTest(location=location):
                self.c.move(self.bulk,'transfer',grams=100,location_id=location)
                scope=stock_id(self.db,self.batch,location)
                before=len(rows(self.db,'SELECT * FROM movements'))
                with self.assertRaisesRegex(ValueError,'roastery'):
                    self.c.move(scope,'reserve',grams=100,line_id='l',use='dispatch',due_at='2026-11-25T03:00:00Z')
                self.assertEqual(len(rows(self.db,'SELECT * FROM movements')),before)
                self.assertEqual(rows(self.db,'SELECT * FROM reservations'),[])
        self.assertEqual(self.c.total(),850000)
    def test_cafe_forecast_can_still_use_and_reserve_cafe_stock(self):
        self.c.move(self.bulk,'transfer',grams=850,location_id='cafe')
        self.db.execute("INSERT INTO demands VALUES ('d','c','brew','2026-11-25T03:00:00Z',300000,'Cafe forecast')")
        self.c.move(stock_id(self.db,self.batch,'cafe'),'reserve',grams=300,demand_id='d',use='brew',due_at='2026-11-25T03:00:00Z')
        result=plan(self.db)['rows']
        self.assertEqual(next(r for r in result if r['type']=='line_id')['covered_mg'],0)
        self.assertEqual(next(r for r in result if r['type']=='demand_id')['covered_mg'],300000)
        self.assertEqual(self.tile()['roast_mg'],1000000)
    def test_packing_order_allocation_defaults_to_roastery(self):
        self.c.order(remaining=2,quantity=2);self.c.reserve(self.bulk,200)
        r=one(self.db,'SELECT * FROM reservations')
        self.c.move(self.bulk,'pack_reserved',reservation_id=r['id'])
        line=self.order_line()
        self.assertEqual(line['allocated_mg'],200000);self.assertEqual(line['missing_mg'],0)
        self.assertEqual(line['status'],'Packed / allocated')
        self.assertEqual(line['allocations'][0]['location_id'],'roastery')
        self.assertEqual(self.tile()['roast_mg'],0)
