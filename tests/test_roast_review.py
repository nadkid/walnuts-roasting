import json,unittest
from server import roast_review,green
from server.db import rows,one,uid,transaction
from server.imports import roast_import
import test_core

class RoastReview(unittest.TestCase):
 def setUp(self):self.c=test_core.Core();self.c.setUp();self.db=self.c.db
 def tearDown(self):self.c.tearDown()
 def ingest(self,**kw):return self.c.runop(roast_import,self.c.roast_record(**kw))
 def pending(self):return roast_review.pending_roasts(self.db)
 def complete(self,**kw):
  r=self.pending()[0] if self.pending() else {'external_id':'r1','source_version':''}
  d={'external_id':r['external_id'],'source_version':r['source_version'],'coffee_id':'c','roasted_at':'2026-11-05T01:00:00Z','green_g':'1000','output_g':'850','reason':'Reviewed roast label',**kw}
  return self.c.runop(roast_review.complete_roast,d,'Tester',uid())
 def test_missing_bean_visible_with_source_values_and_no_stock_until_completed(self):
  self.ingest(beanId=None);self.ingest(beanId=None);r=self.pending()[0]
  self.assertEqual(len(self.pending()),1);self.assertEqual(r['green_mg'],1000000);self.assertIn('Bean assignment missing',r['missing']);self.assertEqual(self.c.total(),0)
  bean=self.c.runop(green.save_bean,{'name':'Green','coffee_ids':['c']},'Tester',uid())['id']
  self.c.runop(green.receive,{'bean_id':bean,'grams':2000,'total':4000,'received_at':'2026-11-01T00:00:00Z'},'Tester',uid())
  done=self.complete();self.assertFalse(self.pending());self.assertEqual(self.c.total(),850000)
  self.assertEqual(green.snapshot(self.db)['beans'][0]['quantity_mg'],1000000)
  self.assertTrue(self.complete()['duplicate']);self.assertEqual(self.c.total(),850000)
  self.ingest(beanId=None);self.assertEqual(self.c.total(),850000)
  self.assertFalse(rows(self.db,"SELECT * FROM issues WHERE kind='source_edit'"))
 def test_shared_mapping_optional_and_only_real_external_ids_can_be_mapped(self):
  self.ingest(beanId='new-bean');self.complete(map_bean=True)
  self.assertEqual(one(self.db,"SELECT coffee_id FROM bean_mappings WHERE external_id='new-bean'")['coffee_id'],'c')
  self.ingest(uid='r2',beanId='new-bean');self.assertFalse(self.pending());self.assertEqual(self.c.total(),1700000)
 def test_missing_bean_cannot_create_null_mapping(self):
  self.ingest(beanId=None)
  with self.assertRaises(ValueError):self.complete(map_bean=True)
  self.assertEqual(self.c.total(),0);self.assertEqual(len(self.pending()),1)
 def test_source_updates_and_invalid_details_reject_without_partial_post(self):
  self.ingest(beanId=None);old=self.pending()[0]['source_version'];self.ingest(beanId=None,weightRoasted=825)
  for data in [{'source_version':old},{'green_g':0},{'output_g':1000},{'reason':''},{'roasted_at':'2027-01-01T00:00:00Z'}]:
   with self.subTest(data=data),self.assertRaises(ValueError):self.complete(**data)
   self.assertEqual(self.c.total(),0)
  self.complete(output_g=825);self.assertEqual(self.c.total(),825000)
 def test_historical_completion_preserves_cutover_and_pre_start_records_stay_excluded(self):
  self.db.execute("UPDATE settings SET value='\"2026-11-10T00:00:00Z\"' WHERE key='cutover_at'")
  self.ingest(beanId=None);r=self.complete();self.assertTrue(r['history_only']);self.assertEqual(self.c.total(),0)
  self.ingest(uid='old',beanId=None);self.db.execute("UPDATE settings SET value='\"2026-11-06T00:00:00Z\"' WHERE key='roastworld_start_at'")
  self.assertFalse(self.pending())
  with self.assertRaises(ValueError):self.complete(external_id='old',source_version=roast_review.version(self.c.roast_record(uid='old',beanId=None)))
 def test_invalid_weights_and_date_can_be_completed_locally(self):
  self.ingest(beanId=None,dateTime=None,weightRoasted=0);r=self.pending()[0]
  self.assertIsNone(r['roasted_at']);self.assertIsNone(r['output_mg']);self.complete();self.assertEqual(self.c.total(),850000)
 def test_mapping_conflict_does_not_rewrite_other_profiles(self):
  self.ingest(weightRoasted=0);self.db.execute("INSERT INTO coffees SELECT 'other',name,'Other',brew_days,dispatch_days,retail_days,fresh_days,yield_bp,policy_version FROM coffees WHERE id='c'")
  with self.assertRaises(ValueError):self.complete(coffee_id='other',map_bean=True)
  self.complete(coffee_id='other',map_bean=False);self.assertEqual(one(self.db,"SELECT coffee_id FROM bean_mappings WHERE external_id='bean'")['coffee_id'],'c')
