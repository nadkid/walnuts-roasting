import unittest,json
import test_core
from server.db import one,rows
from server.domain import stock_id,order_eligible
from server.wholesale import save_order,dispatch_order
from server.planner import plan

class Wholesale(unittest.TestCase):
 def setUp(self):self.c=test_core.Core();self.c.setUp();self.db=self.c.db
 def tearDown(self):self.c.tearDown()
 def payload(self,**overrides):
  return {'customer':{'business':'Fictional Café','contact':'Demo buyer','email':'buyer@example.invalid','address':'Example address'},'status':'CONFIRMED','payment':'PENDING','terms':'Net 14','due_at':'2026-11-25T03:00:00Z','method':'delivery','lines':[{'coffee_id':'c','unit_g':'100','quantity':'4','grind':'Whole bean'}],**overrides}
 def create(self,**overrides):return self.c.runop(save_order,self.payload(**overrides),'staff','create')['order_id']
 def setup_stock(self):
  id=self.create();batch=self.c.batch();bulk=stock_id(self.db,batch,'roastery');self.c.move(bulk,'pack',package_id='p',units='4',location_id='packing');packed=stock_id(self.db,batch,'packing','p');line=one(self.db,'SELECT * FROM lines WHERE order_id=?',(id,));self.c.move(packed,'reserve',grams=400,line_id=line['id'],use='dispatch',due_at='2026-11-25T03:00:00Z');return id,packed,line
 def test_create_pending_invoice_plans_without_inventing_stock(self):
  id=self.create();self.assertTrue(order_eligible(self.db,id));self.assertEqual(self.c.total(),0);self.assertEqual(plan(self.db)['rows'][0]['quantity_mg'],400000);self.assertEqual(one(self.db,'SELECT * FROM wholesale_orders')['terms'],'Net 14')
 def test_repeated_submit_creates_one_order_and_custom_size(self):
  d=self.payload(lines=[{'coffee_id':'c','unit_g':'1000','quantity':'2'}]);a=self.c.runop(save_order,d,'staff','same');b=self.c.runop(save_order,d,'staff','same');self.assertEqual(a['order_id'],b['order_id']);self.assertEqual(len(rows(self.db,'SELECT * FROM orders')),1);self.assertEqual(plan(self.db)['rows'][0]['quantity_mg'],2000000)
 def test_draft_is_excluded_and_confirmation_adds_demand(self):
  id=self.create(status='DRAFT',due_at=None);self.assertEqual(plan(self.db)['rows'],[]);d=self.payload(id=id,version=1);d['lines'][0]['id']=one(self.db,'SELECT * FROM lines')['id'];self.c.runop(save_order,d,'staff','confirm');self.assertEqual(len(plan(self.db)['rows']),1)
 def test_cancel_releases_allocations_without_adding_physical_stock(self):
  id,s,l=self.setup_stock();total=self.c.total();d=self.payload(id=id,version=1,status='CANCELLED');d['lines'][0]['id']=l['id'];self.c.runop(save_order,d,'staff','cancel');self.assertEqual(self.c.total(),total);self.assertEqual(rows(self.db,'SELECT * FROM reservations'),[]);self.assertEqual(plan(self.db)['rows'],[])
 def test_partial_dispatch_consumes_own_reservation_once(self):
  id,s,l=self.setup_stock();d={'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':200}]};self.c.runop(dispatch_order,d,'staff','send');self.c.runop(dispatch_order,d,'staff','send');self.assertEqual(self.c.total(),650000);self.assertEqual(one(self.db,'SELECT * FROM lines')['unfulfilled'],2);self.assertEqual(one(self.db,'SELECT * FROM reservations')['quantity_mg'],200000);self.assertEqual(plan(self.db)['rows'][0]['quantity_mg'],200000)
  d['version']=2;self.c.runop(dispatch_order,d,'staff','send-rest');self.assertEqual(self.c.total(),450000);self.assertEqual(one(self.db,'SELECT * FROM orders')['fulfillment'],'FULFILLED');self.assertEqual(plan(self.db)['rows'],[])
 def test_dispatch_failure_rolls_back_released_allocations(self):
  id,s,l=self.setup_stock();self.db.execute('UPDATE batches SET held=1');d={'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':100}]}
  with self.assertRaises(ValueError):self.c.runop(dispatch_order,d,'staff','held-pick')
  self.assertEqual(one(self.db,'SELECT * FROM reservations')['quantity_mg'],400000);self.assertEqual(rows(self.db,'SELECT * FROM fulfillment_events'),[]);self.assertEqual(self.c.total(),850000)
 def test_stale_edits_and_reserved_quantity_changes_rejected(self):
  id,s,l=self.setup_stock();d=self.payload(id=id,version=0);d['lines'][0]['id']=l['id']
  with self.assertRaises(ValueError):self.c.runop(save_order,d,'staff','stale')
  d['version']=1;d['lines'][0]['quantity']='2'
  with self.assertRaises(ValueError):self.c.runop(save_order,d,'staff','reduce')
  self.assertEqual(one(self.db,'SELECT * FROM lines')['quantity'],4)
 def test_invalid_quantities_and_customer_fields_are_atomic(self):
  for d in [self.payload(customer={'business':''}),self.payload(lines=[{'coffee_id':'c','unit_g':'100','quantity':'1.5'}]),self.payload(due_at=None)]:
   with self.assertRaises(ValueError):self.c.runop(save_order,d,'staff','invalid')
  self.assertEqual(rows(self.db,'SELECT * FROM orders'),[]);self.assertEqual(rows(self.db,'SELECT * FROM movements'),[])
 def test_shopify_order_cannot_be_edited_as_wholesale(self):
  self.c.order()
  with self.assertRaises(ValueError):self.c.runop(save_order,self.payload(id='o',version=1),'staff','bad-source')
  self.assertEqual(one(self.db,"SELECT * FROM orders WHERE id='o'")['source'],'shopify')

 def test_dispatch_cannot_consume_another_orders_commitment(self):
  id,s,l=self.setup_stock();reservation=one(self.db,'SELECT * FROM reservations');self.c.move(s,'release',reservation_id=reservation['id'])
  self.c.move(s,'reserve',grams=300,line_id=l['id'],use='dispatch',due_at='2026-11-25T03:00:00Z')
  other=self.c.runop(save_order,self.payload(customer={'business':'Other fixture customer'}),'staff','other')['order_id'];otherline=one(self.db,'SELECT * FROM lines WHERE order_id=?',(other,))
  self.c.move(s,'reserve',grams=100,line_id=otherline['id'],use='dispatch',due_at='2026-11-25T03:00:00Z')
  with self.assertRaises(ValueError):self.c.runop(dispatch_order,{'order_id':id,'version':1,'picks':[{'line_id':l['id'],'stock_id':s,'grams':400}]},'staff','overspend')
  self.assertEqual(self.c.total(),850000);self.assertEqual(sum(r['quantity_mg'] for r in rows(self.db,'SELECT * FROM reservations')),400000)
