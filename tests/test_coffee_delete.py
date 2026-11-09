import unittest,json
from server import coffees,green
from server.db import uid,one,rows
from server.domain import stock_id
import test_core

class CoffeeDeletion(unittest.TestCase):
 def setUp(self):self.c=test_core.Core();self.c.setUp();self.db=self.c.db
 def tearDown(self):self.c.tearDown()
 def remove(self,archived=True,key=None,id='c'):return self.c.runop(coffees.set_archived,{'id':id,'archived':archived},'Tester',key or uid())
 def test_exhausted_coffee_deleted_and_restored_with_history_intact(self):
  batch=self.c.batch();s=stock_id(self.db,batch,'roastery');self.c.move(s,'waste',grams=850,reason='Actual waste')
  before=rows(self.db,'SELECT * FROM entries');self.remove(key='same');self.assertTrue(self.remove(key='same')['duplicate']);self.assertTrue(coffees.snapshot(self.db)[0]['archived'])
  self.assertEqual(rows(self.db,'SELECT * FROM entries'),before);self.assertEqual(one(self.db,'SELECT id FROM batches')['id'],batch)
  self.remove(False);self.assertFalse(coffees.snapshot(self.db)[0]['archived'])
 def test_stock_prevents_deletion_including_overfill(self):
  self.c.batch()
  with self.assertRaisesRegex(ValueError,'roasted stock'):self.remove()
  self.assertFalse(coffees.snapshot(self.db)[0]['archived'])
 def test_new_stock_restores_automatically(self):
  self.remove();self.c.batch();self.assertFalse(coffees.snapshot(self.db)[0]['archived'])
  self.assertTrue(rows(self.db,"SELECT * FROM audit WHERE action='coffee_restored_for_stock'"))
 def test_open_orders_block_deletion_but_fulfilled_history_does_not(self):
  self.c.order()
  with self.assertRaisesRegex(ValueError,'unfulfilled orders'):self.remove()
  self.db.execute("UPDATE lines SET unfulfilled=0");self.remove();self.assertTrue(coffees.snapshot(self.db)[0]['archived'])
 def test_future_targets_block_but_past_forecasts_allow_deletion(self):
  self.db.execute("INSERT INTO demands VALUES ('d','c','brew','2026-11-25T00:00:00Z',100000,'Forecast')")
  with self.assertRaisesRegex(ValueError,'forecasts'):self.remove()
  self.db.execute("UPDATE demands SET due_at='2026-11-01T00:00:00Z'");self.remove()
 def test_last_green_profile_requires_zero_but_shared_profiles_are_independent(self):
  b=self.c.runop(green.save_bean,{'name':'Green','coffee_ids':['c']},'Tester',uid())['id']
  self.c.runop(green.receive,{'bean_id':b,'grams':1000,'total':5000,'received_at':'2026-11-01T00:00:00Z'},'Tester',uid())
  with self.assertRaisesRegex(ValueError,'linked green'):self.remove()
  self.db.execute("INSERT INTO coffees SELECT 'other',name,'Espresso',brew_days,dispatch_days,retail_days,fresh_days,yield_bp,policy_version FROM coffees WHERE id='c'")
  self.db.execute('INSERT INTO green_coffee_links VALUES (?,?)',('other',b));self.remove()
  with self.assertRaisesRegex(ValueError,'linked green'):self.remove(id='other')
 def test_pending_roasts_prevent_deletion(self):
  self.db.execute("INSERT INTO plans VALUES ('p','c','2026-11-21T00:00:00Z',1000000,850000,'planned','Test','{}')")
  with self.assertRaisesRegex(ValueError,'planned roasts'):self.remove()
