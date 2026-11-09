import json,unittest
import test_core
from server.today import customer_roast
from server.db import one,rows
from server.domain import stock_id,policy
from server.imports import order_import
from server.wholesale import save_order


class CustomerRoast(unittest.TestCase):
    def setUp(self):
        self.core=test_core.Core();self.core.setUp();self.db=self.core.db
    def tearDown(self):self.core.tearDown()
    def order(self,id='o',units=10,due='2026-11-25T03:00:00Z',**changes):
        o={'id':id,'name':'#'+id,'updatedAt':'2026-11-20T03:00:00Z','displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','lines':[{'id':'l'+id,'variant':{'id':'v'},'title':'Coffee','quantity':units,'currentQuantity':units,'unfulfilledQuantity':units}],**changes}
        self.core.runop(order_import,o)
        self.db.execute('UPDATE orders SET due_at=? WHERE id=?',(due,id))
        return o
    def tile(self):return customer_roast(self.db)['coffees'][0]
    def plan(self,at='2026-11-22T03:00:00Z',expected=500000,id='plan'):
        c=one(self.db,"SELECT * FROM coffees WHERE id='c'")
        self.db.execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?,?)',(id,'c',at,1200000,expected,'planned','Test plan',json.dumps(policy(c))))
    def test_customer_orders_spend_stock_once_in_deadline_order(self):
        self.core.batch(output=850);self.order('later',units=6,due='2026-11-26T03:00:00Z');self.order('first',units=6)
        before=self.db.total_changes;t=self.tile()
        self.assertEqual(t['roast_mg'],350000)
        self.assertEqual([(o['number'],o['roast_mg']) for o in t['orders']],[('#first',0),('#later',350000)])
        self.assertEqual(self.db.total_changes,before,'summary must never change inventory, allocations or plans')
        self.assertEqual(self.core.total(),850000)
    def test_forecasts_and_suggested_batch_excess_do_not_reduce_customer_totals(self):
        self.order('a',units=1);self.order('b',units=1)
        self.db.execute("INSERT INTO demands VALUES ('d','c','brew','2026-11-21T03:00:00Z',90000000,'Forecast')")
        self.assertEqual(self.tile()['roast_mg'],200000,'only physical stock can reduce still-to-roast')
        self.core.batch(output=850)
        self.assertEqual(self.tile()['roast_mg'],0,'unreserved forecasts do not consume customer stock in this work list')
    def test_approved_plans_are_a_subset_of_still_to_roast(self):
        self.order(units=10);self.plan()
        t=self.tile();self.assertEqual((t['roast_mg'],t['scheduled_mg'],t['unplanned_mg']),(1000000,500000,500000))
        self.assertEqual(t['green_mg'],1177000)
        self.plan(expected=500000,id='second');t=self.tile();self.assertEqual(t['status'],'Scheduled');self.assertEqual(t['roast_mg'],1000000)
    def test_plans_spent_once_and_late_or_unready_plans_flagged(self):
        self.order('a',units=5);self.order('b',units=5);self.plan(expected=500000)
        self.assertEqual(self.tile()['scheduled_mg'],500000)
        self.db.execute("UPDATE plans SET roast_at='2026-11-24T03:00:00Z'")
        self.assertEqual(self.tile()['scheduled_mg'],0,'plan must rest by deadline')
        self.db.execute("UPDATE plans SET roast_at='2026-11-19T03:00:00Z'")
        t=self.tile();self.assertEqual(t['tone'],'yellow');self.assertIn('A scheduled roast is overdue.',t['notes'])
    def test_reserved_stock_cannot_cover_another_order_or_forecast(self):
        b=self.core.batch();s=stock_id(self.db,b,'roastery');self.order('a',units=6);self.order('b',units=6)
        self.core.move(s,'reserve',grams=600,line_id='lb',use='dispatch',due_at='2026-11-25T03:00:00Z')
        t=self.tile();self.assertEqual(t['roast_mg'],350000)
        self.assertEqual({o['id']:o['roast_mg'] for o in t['orders']},{'a':350000,'b':0})
        r=one(self.db,'SELECT * FROM reservations');self.core.move(s,'release',reservation_id=r['id'])
        self.db.execute("INSERT INTO demands VALUES ('d','c','brew','2026-11-25T03:00:00Z',600000,'Forecast')")
        self.core.move(s,'reserve',grams=600,demand_id='d',use='brew',due_at='2026-11-25T03:00:00Z')
        self.assertEqual(self.tile()['roast_mg'],950000,'actual forecast reservations remain unavailable')
    def test_stock_must_match_profile_bag_size_rest_and_quality(self):
        b=self.core.batch()
        s=stock_id(self.db,b,'roastery');self.core.move(s,'pack',package_id='p',units='8',overfill_g=3,reason='Test')
        self.db.execute("INSERT INTO packages VALUES ('big','200 g',200000)")
        self.db.execute("UPDATE variants SET package_id='big'")
        self.order(units=2)
        self.assertEqual(self.tile()['roast_mg'],353000,'100g bags do not satisfy 200g orders; 47g bulk remains after the measured 3g overfill')
        self.db.execute('UPDATE batches SET held=1');self.db.execute("UPDATE variants SET package_id='p'")
        self.assertEqual(self.tile()['roast_mg'],200000,'held coffee and packaging overfill are not eligible supply')
        self.db.execute('UPDATE batches SET held=0,archived=1');self.assertEqual(self.tile()['roast_mg'],200000)
        self.db.execute("UPDATE batches SET archived=0,roasted_at='2026-11-24T03:00:00Z'")
        self.assertEqual(self.tile()['roast_mg'],200000,'resting stock must be ready by the deadline')
    def test_only_open_eligible_customer_orders_including_confirmed_wholesale(self):
        self.order('paid',units=2)
        self.order('unpaid',displayFinancialStatus='PENDING')
        self.order('cancelled',cancelledAt='2026-11-20T03:00:00Z')
        self.order('archived',closedAt='2026-11-20T03:00:00Z')
        self.order('fulfilled',displayFulfillmentStatus='FULFILLED')
        self.core.runop(save_order,{'customer':{'business':'Test cafe'},'due_at':'2026-11-25T03:00:00Z','status':'CONFIRMED','terms':'Net 14','lines':[{'coffee_id':'c','unit_g':'100','quantity':'3'}]},'staff','wholesale')
        t=self.tile();self.assertEqual(t['roast_mg'],500000);self.assertEqual(len(t['orders']),2)
    def test_undated_and_unmapped_orders_are_visible_without_false_zero(self):
        self.order('missing-date',units=2,due=None)
        self.order('unmapped',lines=[{'id':'unknown-line','variant':{'id':'unknown'},'title':'Unknown','quantity':1,'unfulfilledQuantity':1}])
        result=customer_roast(self.db);t=result['coffees'][0]
        self.assertEqual(t['unknown_lines'],1);self.assertIsNone(t['orders'][0]['roast_mg']);self.assertEqual(t['tone'],'yellow');self.assertEqual(result['unmapped_orders'],1)
    def test_all_dates_profiles_and_archived_lineup(self):
        self.order(due='2027-01-01T03:00:00Z');self.assertEqual(self.tile()['roast_mg'],1000000,'not limited to the planner 14-day window')
        self.db.execute("INSERT INTO coffees VALUES ('other','Same bean','Espresso',7,2,2,90,8500,1)")
        result=customer_roast(self.db);self.assertEqual(len(result['coffees']),2);self.assertEqual(result['coffees'][1]['roast_mg'],0)
        self.db.execute("INSERT INTO coffee_archives VALUES ('other','2026-11-20T03:00:00Z','staff')")
        self.assertEqual(len(customer_roast(self.db)['coffees']),1)
    def test_overdue_and_missing_policy(self):
        self.order(due='2026-11-19T03:00:00Z');self.assertEqual(self.tile()['tone'],'red')
        self.db.execute("UPDATE orders SET due_at='2026-11-21T03:00:00Z'")
        self.assertEqual(self.tile()['status'],'Roast overdue')
        self.db.execute('UPDATE coffees SET dispatch_days=NULL');self.assertEqual(self.tile()['tone'],'yellow');self.assertIsNone(self.tile()['roast_by'])

    def test_bulk_is_net_weight_not_a_whole_bag_per_stock_scope(self):
        b=self.core.batch(output=850);s=stock_id(self.db,b,'roastery')
        self.core.move(s,'transfer',grams=425,location_id='cafe')
        self.order(units=9)
        self.assertEqual(self.tile()['roast_mg'],50000,'two 425g scopes contribute all 850g, rather than rounding each down to 400g')
        self.plan(expected=50000)
        self.assertEqual(self.tile()['scheduled_mg'],50000)
    def test_blend_stays_one_finished_coffee_with_estimated_components(self):
        from server import blends,green
        self.order(units=10)
        self.core.runop(blends.save_profile,{'coffee_id':'c','source_tag':'Espresso','version':0},'staff','profile')
        self.assertEqual(self.tile()['status'],'Needs recipe')
        beans=[self.core.runop(green.save_bean,{'name':name,'currency':'JPY','coffee_ids':[]},'staff',name)['id'] for name in ('One','Two')]
        self.core.runop(blends.save_recipe,{'coffee_id':'c','version':0,'effective_at':'2026-11-01T00:00:00Z','notes':'Test','ingredients':[{'bean_id':beans[0],'percent':'75'},{'bean_id':beans[1],'percent':'25'}]},'staff','recipe')
        before=self.db.total_changes;result=customer_roast(self.db);t=result['coffees'][0]
        self.assertEqual(len(result['coffees']),1);self.assertEqual(t['roast_mg'],1000000)
        self.assertEqual(sum(i['quantity_mg'] for i in t['blend_components']),t['green_mg'])
        self.assertEqual(self.db.total_changes,before)
    def test_pending_stock_pick_marks_coverage_for_review(self):
        self.order();self.core.batch()
        self.db.execute("INSERT INTO fulfillment_events VALUES ('f','o','2026-11-20T03:00:00Z','{}',0)")
        self.assertEqual(self.tile()['status'],'Needs attention')
        self.assertTrue(any('actual stock pick' in n for n in self.tile()['notes']))

    def test_matching_packed_bags_are_used_before_bulk_for_other_sizes(self):
        b=self.core.batch(output=850);s=stock_id(self.db,b,'roastery')
        self.core.move(s,'pack',package_id='p',units='4')
        self.order('small',units=4)
        self.db.execute("INSERT INTO packages VALUES ('big','200 g',200000)")
        self.db.execute("INSERT INTO variants VALUES ('big-v','','c','big','coffee','Whole bean')")
        self.order('large',units=2,lines=[{'id':'big-line','variant':{'id':'big-v'},'title':'200g coffee','quantity':2,'unfulfilledQuantity':2}])
        self.assertEqual(self.tile()['roast_mg'],0,'matching bags leave 450g of bulk available for 200g orders')

    def test_recording_actual_roast_replaces_scheduled_work(self):
        self.order(units=10);self.plan()
        self.assertEqual(self.tile()['roast_mg'],1000000)
        self.core.batch(green=1200,output=1000,roasted='2026-11-20T03:00:00Z',plan_id='plan')
        t=self.tile();self.assertEqual(t['roast_mg'],0);self.assertEqual(t['scheduled_mg'],0)
        self.assertEqual(t['status'],'Stock covered')

    def test_overdue_orders_use_coffee_ready_now_without_re_roasting_it(self):
        self.core.batch(roasted='2026-11-18T03:00:00Z')
        self.order(units=8,due='2026-11-19T03:00:00Z')
        t=self.tile();self.assertEqual(t['roast_mg'],0)
        self.assertEqual(t['status'],'Order overdue','original deadline stays visible, but ready stock is not roasted again')
