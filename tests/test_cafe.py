"""Cafe requests share production demand and fulfil via conserved transfers."""
import json,unittest
from types import SimpleNamespace
import test_core
from server import cafe,profit,products
from server.app import state,Handler
from server.db import one,rows,uid
from server.domain import stock_id,stock,order_eligible,policy
from server.order_rules import order_lines
from server.planner import plan
from server.today import customer_roast


class Cafe(unittest.TestCase):
    def setUp(self):self.c=test_core.Core();self.c.setUp();self.db=self.c.db
    def tearDown(self):self.c.tearDown()
    def op(self,fn,data,key=None):return self.c.runop(fn,data,'Cafe staff',key or uid())
    def payload(self,**changes):return {'due_at':'2026-11-25T03:00:00Z','notes':'For the next service','lines':[{'coffee_id':'c','form':'bulk','kg':'4'}],**changes}
    def create(self,**changes):return self.op(cafe.save_order,self.payload(**changes))['order_id']
    def line(self,id):return order_lines(self.db,id)[0]
    def snapshot(self):return state(self.db,{'id':'staff','name':'Cafe staff','role':'staff'},SimpleNamespace(configured=lambda:{}))
    def test_bulk_kilos_and_bags_enter_orders_and_today_without_stock_mutations(self):
        before=self.c.total();id=self.create(lines=[{'coffee_id':'c','form':'bulk','kg':'4'},{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}])
        ls=order_lines(self.db,id);self.assertEqual([l['required_mg'] for l in ls],[4000000,300000])
        self.assertEqual([l['use'] for l in ls],['brew','retail']);self.assertEqual(ls[0]['package_id'],'bulk')
        self.assertTrue(order_eligible(self.db,id));self.assertEqual(self.c.total(),before)
        self.assertEqual(customer_roast(self.db)['coffees'][0]['roast_mg'],4300000)
        order=next(o for o in self.snapshot()['orders'] if o['id']==id)
        self.assertEqual(order['source'],'cafe');self.assertEqual(order['cafe']['requested_by'],'Cafe staff')
        self.assertEqual(order['lines'][0]['required_mg'],4000000)
    def test_roast_deadline_and_stock_coverage_use_brew_or_retail_rest(self):
        self.db.execute('UPDATE coffees SET brew_days=7,dispatch_days=0,retail_days=3')
        b=self.c.batch(roasted='2026-11-19T03:00:00Z')
        bulk=stock_id(self.db,b,'roastery');id=self.create(due_at='2026-11-22T03:00:00Z')
        self.assertEqual(customer_roast(self.db)['coffees'][0]['roast_mg'],4000000)
        p=next(r for r in plan(self.db)['rows'] if r['id']==self.line(id)['id'])
        self.assertEqual(p['channel'],'brew');self.assertEqual(p['covered_mg'],0)
        with self.assertRaisesRegex(ValueError,'Resting'):
            self.c.move(bulk,'reserve',grams=100,line_id=self.line(id)['id'],use='brew',due_at='2026-11-22T03:00:00Z')
        # Same coffee may cover a retail commitment once its shorter rest is met.
        bag=self.create(due_at='2026-11-22T03:00:00Z',lines=[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}])
        self.assertEqual(next(r for r in plan(self.db)['rows'] if r['id']==self.line(bag)['id'])['covered_mg'],300000)
    def test_customer_and_cafe_orders_spend_roastery_stock_once(self):
        self.c.batch();self.c.order(2,2);self.create(lines=[{'coffee_id':'c','form':'bulk','kg':'1'}])
        before=self.db.total_changes;t=customer_roast(self.db)['coffees'][0]
        self.assertEqual(t['roast_mg'],350000);self.assertEqual(sum(o['stock_mg'] for o in t['orders']),850000)
        self.assertEqual(self.db.total_changes,before)
    def test_floor_stock_is_excluded_and_two_retail_requests_are_additive(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');self.c.move(s,'transfer',grams=850,location_id='cafe')
        self.create(lines=[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}])
        self.create(lines=[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}])
        self.assertEqual(customer_roast(self.db)['coffees'][0]['roast_mg'],600000)
        self.assertEqual(sum(r['quantity_mg'] for r in plan(self.db)['rows'] if r['type']=='line_id'),600000)
        self.assertFalse(any(a['kind'] in ('physical','reserved','target carryover') for r in plan(self.db)['rows'] for a in r['allocations']))
        self.c.move(stock_id(self.db,b,'cafe'),'transfer',grams=300,location_id='roastery')
        self.assertEqual(customer_roast(self.db)['coffees'][0]['roast_mg'],300000)
        # Unapproved suggestion excess must never become real Today stock.
        self.assertEqual(self.c.total(),850000)
    def test_partial_bulk_delivery_conserves_mass_and_updates_remaining_demand(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create(lines=[{'coffee_id':'c','form':'bulk','kg':'1'}]);l=self.line(id)
        self.c.move(s,'reserve',grams=600,line_id=l['id'],use='brew',due_at='2026-11-25T03:00:00Z')
        data={'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':'250.125'}]}
        self.op(cafe.deliver,data,'bulk-transfer');self.assertTrue(self.op(cafe.deliver,data,'bulk-transfer')['duplicate'])
        self.assertEqual(self.c.total(),850000);self.assertEqual(stock(self.db,stock_id(self.db,b,'cafe'))['quantity_mg'],250125)
        self.assertEqual(self.line(id)['required_mg'],749875);self.assertEqual(stock(self.db,s)['reserved_mg'],349875)
        o=one(self.db,'SELECT * FROM orders WHERE id=?',(id,));self.assertEqual(o['fulfillment'],'PARTIALLY_FULFILLED')
        self.assertEqual(customer_roast(self.db)['coffees'][0]['roast_mg'],150000)
        self.assertEqual(rows(self.db,'SELECT * FROM fulfillment_events'),[])
    def test_retail_delivery_moves_whole_bags_and_their_overfill_to_wall(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');self.c.move(s,'pack',package_id='p',units='3',overfill_g='3',reason='Measured overfill')
        packed=stock_id(self.db,b,'roastery','p');id=self.create(lines=[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}]);l=self.line(id)
        self.c.move(packed,'reserve',grams=300,line_id=l['id'],use='retail',due_at='2026-11-25T03:00:00Z')
        self.op(cafe.deliver,{'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':packed,'grams':300}]})
        wall=stock(self.db,stock_id(self.db,b,'wall','p'));self.assertEqual(wall['quantity_mg'],300000);self.assertEqual(wall['overfill_mg'],3000)
        self.assertEqual(self.c.total(),850000);self.assertEqual(self.line(id)['required_mg'],0)
        self.assertEqual(one(self.db,'SELECT * FROM orders WHERE id=?',(id,))['fulfillment'],'FULFILLED')
        self.assertEqual(profit.snapshot(self.db)['rows'],[],'internal requests never create sales')
    def test_allocated_bags_can_be_packed_at_roastery_before_delivery(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create(lines=[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}]);l=self.line(id)
        self.c.move(s,'reserve',grams=300,line_id=l['id'],use='retail',due_at='2026-11-25T03:00:00Z')
        r=one(self.db,'SELECT * FROM reservations');self.c.move(s,'pack_reserved',reservation_id=r['id'])
        self.assertEqual(one(self.db,'SELECT * FROM reservations')['use'],'retail')
        self.assertEqual(next(o for o in self.snapshot()['orders'] if o['id']==id)['lines'][0]['status'],'Ready to transfer')
    def test_delivery_rejects_resting_wrong_location_other_reservations_and_overdelivery_atomically(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create(lines=[{'coffee_id':'c','form':'bulk','kg':'0.2'}]);l=self.line(id)
        self.c.order(2,2);self.c.reserve(s,200)
        for grams in (201,700):
            with self.assertRaises(ValueError):self.op(cafe.deliver,{'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':grams}]})
        self.db.execute('UPDATE batches SET held=1')
        with self.assertRaisesRegex(ValueError,'Quality hold'):self.op(cafe.deliver,{'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':100}]})
        self.db.execute('UPDATE batches SET held=0');self.c.move(s,'transfer',grams=100,location_id='cafe')
        with self.assertRaisesRegex(ValueError,'roastery'):self.op(cafe.deliver,{'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':stock_id(self.db,b,'cafe'),'grams':100}]})
        self.assertEqual(self.line(id)['required_mg'],200000);self.assertEqual(rows(self.db,'SELECT * FROM cafe_deliveries'),[])
        self.assertEqual(stock(self.db,s)['reserved_mg'],200000)
    def test_cancel_releases_allocations_and_removes_only_remaining_demand(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create();l=self.line(id)
        self.c.move(s,'reserve',grams=300,line_id=l['id'],use='brew',due_at='2026-11-25T03:00:00Z')
        self.op(cafe.cancel_order,{'order_id':id,'version':1,'reason':'No longer needed'})
        self.assertEqual(self.c.total(),850000);self.assertEqual(rows(self.db,'SELECT * FROM reservations'),[])
        self.assertEqual(customer_roast(self.db)['order_count'],0);self.assertFalse(order_eligible(self.db,id))
    def test_creation_replay_edits_and_stale_versions(self):
        data=self.payload();a=self.op(cafe.save_order,data,'create');self.assertTrue(self.op(cafe.save_order,data,'create')['duplicate'])
        id=a['order_id'];l=self.line(id);data=self.payload(id=id,version=1);data['lines'][0].update(id=l['id'],kg='3')
        self.op(cafe.save_order,data);self.assertEqual(self.line(id)['required_mg'],3000000)
        with self.assertRaisesRegex(ValueError,'changed'):self.op(cafe.save_order,data)
        self.assertEqual(len(rows(self.db,'SELECT * FROM orders')),1)
    def test_invalid_requests_roll_back_without_phantom_orders(self):
        for changes in ({'due_at':None},{'lines':[]},{'lines':[{'coffee_id':'c','form':'bulk','kg':'-1'}]},{'lines':[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'1.5'}]}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):self.create(**changes)
                self.assertEqual(rows(self.db,'SELECT * FROM orders'),[])
        self.db.execute('UPDATE coffees SET retail_days=NULL')
        with self.assertRaisesRegex(ValueError,'retail rest'):self.create(lines=[{'coffee_id':'c','form':'bags','package_id':'p','quantity':'3'}])
    def test_internal_variants_never_become_shopify_catalogue_items(self):
        self.create();products.seed_shopify(self.db)
        self.assertFalse(any(r['external_id'].startswith('cafe:') for r in rows(self.db,'SELECT * FROM sale_catalog')))
    def test_delivery_before_brewing_rest_is_rejected_despite_zero_dispatch_rest(self):
        self.db.execute('UPDATE coffees SET dispatch_days=0')
        b=self.c.batch(roasted='2026-11-19T03:00:00Z');s=stock_id(self.db,b,'roastery');id=self.create();l=self.line(id)
        with self.assertRaisesRegex(ValueError,'Resting'):self.op(cafe.deliver,{'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':100}]})
        self.assertEqual(self.c.total(),850000);self.assertEqual(rows(self.db,'SELECT * FROM cafe_deliveries'),[])
    def test_invalid_second_pick_rolls_back_the_entire_delivery(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create(lines=[{'coffee_id':'c','form':'bulk','kg':'1'},{'coffee_id':'c','form':'bags','package_id':'p','quantity':'2'}]);ls=order_lines(self.db,id)
        before=rows(self.db,'SELECT * FROM stocks')
        with self.assertRaisesRegex(ValueError,'requested form'):self.op(cafe.deliver,{'order_id':id,'version':1,'picks':[{'line_id':ls[0]['id'],'stock_id':s,'grams':100},{'line_id':ls[1]['id'],'stock_id':s,'grams':100}]})
        self.assertEqual(rows(self.db,'SELECT * FROM stocks'),before);self.assertEqual(rows(self.db,'SELECT * FROM cafe_deliveries'),[])
        self.assertEqual([l['required_mg'] for l in order_lines(self.db,id)],[1000000,200000])
    def test_cafe_allocation_requires_its_brewing_policy_and_cannot_be_packed_as_bags(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create();l=self.line(id)
        with self.assertRaisesRegex(ValueError,'brew rest'):self.c.move(s,'reserve',grams=100,line_id=l['id'],use='dispatch',due_at='2026-11-25T03:00:00Z')
        self.c.move(s,'reserve',grams=100,line_id=l['id'],use='brew',due_at='2026-11-25T03:00:00Z')
        with self.assertRaisesRegex(ValueError,'do not need packing'):self.c.move(s,'pack_reserved',reservation_id=one(self.db,'SELECT * FROM reservations')['id'])
    def test_payment_policy_changes_do_not_release_cafe_allocations(self):
        b=self.c.batch();s=stock_id(self.db,b,'roastery');id=self.create();l=self.line(id)
        self.c.move(s,'reserve',grams=100,line_id=l['id'],use='brew',due_at='2026-11-25T03:00:00Z')
        before=rows(self.db,'SELECT * FROM reservations')
        self.c.runop(lambda db:Handler.mutate(None,db,'/api/settings',{'eligible_payments':['PAID']},'Admin',{'role':'admin'},'policy'))
        self.assertEqual(rows(self.db,'SELECT * FROM reservations'),before)
