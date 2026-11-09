import unittest,json,sqlite3
from decimal import Decimal
from server import blends,green,profit
from server.imports import roast_import
from server.roast_review import pending_roasts,complete_roast
from server.domain import stock_id,one,uid,movement
from server.db import rows,transaction
import test_core

class Blends(unittest.TestCase):
 def setUp(self):
  self.c=test_core.Core();self.c.setUp();self.db=self.c.db;self.beans=[]
  for n in range(3):
   b=self.op(green.save_bean,{'name':['Gisha','Nigusse','Ichigo'][n],'currency':'JPY','coffee_ids':[]})['id'];self.beans.append(b)
   self.op(green.receive,{'bean_id':b,'grams':'5000','price_basis':'per_kg','price_per_kg':str(1000*(n+1)),'received_at':'2026-10-01T00:00:00Z'})
  self.op(blends.save_profile,{'coffee_id':'c','source_tag':'Espresso','version':0})
 def tearDown(self):self.c.tearDown()
 def op(self,fn,data,key=None):return self.c.runop(fn,data,'Tester',key or uid())
 def save(self,percent=(75,20,5),at='2026-11-01T00:00:00Z',version=0,key=None):
  return self.op(blends.save_recipe,{'coffee_id':'c','version':version,'effective_at':at,'notes':'Reviewed blend','ingredients':[{'bean_id':b,'percent':str(p)} for b,p in zip(self.beans,percent) if p]},key)
 def roast(self,uid='blend1',at='2026-11-05T01:00:00Z',**kw):
  from server.domain import dt
  r=self.c.roast_record(uid=uid,beanId=None,roastName='  esPRESSo  ',dateTime=int(dt(at).timestamp()*1000),weightGreen=1200,weightRoasted=1020,**kw)
  return self.c.runop(roast_import,r)
 def quantities(self):return {b['name']:b['quantity_mg'] for b in green.snapshot(self.db)['beans']}
 def test_component_deductions_saved_snapshot_single_roasted_output_and_replay(self):
  self.save();result=self.roast();self.assertEqual(self.c.total(),1020000)
  self.assertEqual(self.quantities(),{'Gisha':4100000,'Nigusse':4760000,'Ichigo':4940000})
  saved=blends.batch_snapshot(self.db)[result['batch_id']];self.assertEqual([i['quantity_mg'] for i in saved['ingredients']],[900000,240000,60000])
  self.assertEqual(len(rows(self.db,'SELECT * FROM batch_green_components')),3)
  self.roast();self.assertEqual(self.c.total(),1020000);self.assertEqual(len(green.snapshot(self.db)['unlinked']),0)
  self.assertEqual(len([e for e in green.snapshot(self.db)['events'] if e['batch_code']]),3)
 def test_recipe_time_is_roast_time_and_later_changes_do_not_rewrite_batch(self):
  first=self.save();b=self.roast()['batch_id'];before=blends.batch_snapshot(self.db)[b]
  self.save((50,50,0),'2026-11-10T00:00:00Z',1)
  self.assertEqual(blends.batch_snapshot(self.db)[b],before)
  delayed=self.roast('late','2026-11-06T00:00:00Z')['batch_id'];self.assertEqual(blends.batch_snapshot(self.db)[delayed]['recipe_id'],first['id'])
  later=self.roast('later','2026-11-11T00:00:00Z')['batch_id'];self.assertEqual(blends.batch_snapshot(self.db)[later]['version'],2)
 def test_missing_recipe_stays_pending_without_partial_stock(self):
  result=self.roast();self.assertTrue(result['pending']);self.assertEqual(self.c.total(),0)
  p=pending_roasts(self.db)[0];self.assertEqual(p['coffee_id'],'c');self.assertTrue(any('recipe' in x for x in p['missing']))
  self.save();self.roast();self.assertEqual(self.c.total(),1020000)
 def test_short_component_blocks_whole_roast_and_can_be_completed_after_receipt(self):
  self.save();before=self.quantities();self.db.execute('UPDATE settings SET value=\'"2026-11-02T00:00:00Z"\' WHERE key=\'demo_clock\'')
  bean=next(b for b in green.snapshot(self.db)['beans'] if b['id']==self.beans[1]);self.op(green.count,{'bean_id':bean['id'],'version':bean['version'],'grams':0,'reason':'Empty'})
  self.db.execute('UPDATE settings SET value=\'"2026-11-20T03:00:00Z"\' WHERE key=\'demo_clock\'')
  result=self.roast();self.assertTrue(result['pending']);self.assertEqual(self.c.total(),0);self.assertFalse(rows(self.db,'SELECT * FROM batch_green_components'))
  self.assertIn('Nigusse',pending_roasts(self.db)[0]['missing'][0])
  self.op(green.receive,{'bean_id':self.beans[1],'grams':500,'total':1000,'received_at':'2026-11-03T00:00:00Z'});self.roast();self.assertEqual(self.c.total(),1020000)
 def test_cost_sums_all_components_and_reversal_restores_every_green_bean(self):
  self.save();b=self.roast()['batch_id'];rate=profit.batch_costs(self.db)[b]['rate'];self.assertEqual(rate,Decimal(1560)/1020000)
  bulk=stock_id(self.db,b,'roastery');original=one(self.db,"SELECT m.id FROM movements m JOIN entries e ON e.movement_id=m.id WHERE e.stock_id=? AND m.kind='production'",(bulk,))['id']
  self.c.move(bulk,'reverse',reversal_of=original,reason='Test correction');self.assertEqual(self.c.total(),0);self.assertEqual(set(self.quantities().values()),{5000000})
  self.assertNotIn(b,profit.batch_costs(self.db));green.reconcile(self.db,'Tester');self.assertEqual(set(self.quantities().values()),{5000000})
 def test_rounding_conserves_integer_mass(self):
  items=[{'bean_id':str(n),'bp':p} for n,p in enumerate([3333,3333,3334])];parts=blends.split(1000001,items)
  self.assertEqual(sum(i['quantity_mg'] for i in parts),1000001);self.assertTrue(all(type(i['quantity_mg']) is int for i in parts))
 def test_invalid_percent_duplicate_stale_and_fractional_values_rejected(self):
  for p in [(70,20,5),(101,-1,0),(75.001,20,4.999),(0,0,0)]:
   with self.subTest(p=p),self.assertRaises(ValueError):self.save(p)
  self.save(key='same');self.assertTrue(self.save(key='same')['duplicate'])
  with self.assertRaisesRegex(ValueError,'Another recipe'):self.save()
  with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable'):self.db.execute('DELETE FROM blend_recipes')
 def test_tag_match_exact_and_can_override_single_component_mapping(self):
  self.save();self.assertEqual(blends.route(self.db,{'roastName':'Espresso Roast'})[0],None)
  self.assertEqual(blends.route(self.db,{'tags':['ESPRESSO'],'beanId':'bean'})[0],'c')
  self.assertEqual(blends.route(self.db,{'roastName':' espresso '})[0],'c')
  self.assertEqual(blends.route(self.db,{'roastName':'Other','beanId':'bean'})[0],'c') # existing explicit bean mapping
 def test_cancel_unused_recipe_but_never_used_snapshot(self):
  r=self.save();self.op(blends.cancel_recipe,{'id':r['id'],'reason':'Wrong start date'});self.assertIsNone(blends.recipe(self.db,'c','2026-11-05T00:00:00Z'))
  r=self.save(at='2026-11-01T00:00:00Z',version=1);self.roast()
  with self.assertRaisesRegex(ValueError,'batch already'):self.op(blends.cancel_recipe,{'id':r['id'],'reason':'Do not change old batch'})
 def test_historical_cutover_snapshot_but_no_green_charge(self):
  self.save();self.db.execute('UPDATE settings SET value=\'"2026-11-10T00:00:00Z"\' WHERE key=\'cutover_at\'');b=self.roast()['batch_id']
  self.assertIn(b,blends.batch_snapshot(self.db));self.assertEqual(self.c.total(),0);self.assertEqual(set(self.quantities().values()),{5000000})
 def test_later_physical_count_avoids_double_charging_late_roast(self):
  self.save();bean=next(b for b in green.snapshot(self.db)['beans'] if b['id']==self.beans[0]);self.op(green.count,{'bean_id':bean['id'],'version':bean['version'],'grams':0,'reason':'Later count includes roast'})
  self.roast();self.assertEqual(self.quantities()['Gisha'],0)
 def test_planned_green_requirements_and_blend_cannot_link_as_single_origin(self):
  self.save();self.db.execute("INSERT INTO plans VALUES ('planned','c','2026-11-21T00:00:00Z',1200000,1020000,'planned','Blend','{}')")
  g={b['name']:b for b in green.snapshot(self.db)['beans']};self.assertEqual(g['Gisha']['planned_mg'],900000)
  b=g['Gisha']
  with self.assertRaisesRegex(ValueError,'blend draws'):self.op(green.save_bean,{**b,'coffee_ids':['c']})
 def test_estimated_blend_cost_uses_frozen_recipe_and_requires_all_component_prices(self):
  self.save();b=self.roast()['batch_id'];self.save((50,50,0),'2026-11-10T00:00:00Z',1)
  c=profit.estimate_context(self.db);p=[{'batch_id':b,'quantity_mg':100000,'overfill_mg':1000}]
  result=profit.sale_cost(p,{},'JPY',100000,'c','2026-11-20T00:00:00Z',c)
  self.assertEqual(result[0],154);self.assertEqual(result[2],'estimated');self.assertIn('saved batch recipe v1',result[3])
  c['bean_prices'].pop(self.beans[2]);self.assertIsNone(profit.sale_cost(p,{},'JPY',100000,'c','2026-11-20T00:00:00Z',c)[0])

 def test_out_of_order_import_cannot_spend_green_already_used_by_later_roasts(self):
  self.save()
  for n in range(5):self.assertIn('batch_id',self.roast('later'+str(n),'2026-11-'+str(10+n)+'T00:00:00Z'))
  before=self.quantities();r=self.roast('older','2026-11-05T00:00:00Z')
  self.assertTrue(r['pending']);self.assertEqual(self.quantities(),before)
