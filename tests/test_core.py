import unittest,tempfile,json,threading,sqlite3,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from server.db import migrate,connect,transaction,one,rows,settings,uid
from server.domain import *
from server.imports import roast_import,order_import,fulfillment_pick,csv_preview
from server.planner import plan
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from backup import backup
from restore import restore

class Core(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=str(Path(self.temp.name)/'test.sqlite');migrate(self.path);self.db=connect(self.path)
        with transaction(self.db):
            for key,val in {'demo_clock':'2026-11-20T03:00:00+00:00','cutover_at':'2026-11-01T00:00:00+00:00','max_charge_mg':1500000}.items():self.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(val),key)) if key!='demo_clock' else self.db.execute('INSERT INTO settings VALUES (?,?)',(key,json.dumps(val)))
            self.db.execute("INSERT INTO coffees VALUES ('c','Test coffee','Filter',5,2,2,90,8500,1)")
            self.db.execute("INSERT INTO packages VALUES ('p','100 g',100000)")
            self.db.execute("INSERT INTO bean_mappings VALUES ('bean','c')")
            self.db.execute("INSERT INTO variants VALUES ('v','sku','c','p','coffee','Whole bean')")
    def tearDown(self):self.db.close();self.temp.cleanup()
    def runop(self,fn,*args,**kwargs):
        with transaction(self.db):return fn(self.db,*args,**kwargs)
    def batch(self,green=1000,output=850,roasted='2026-11-05T10:00:00+09:00',key=None,**extra):
        r=self.runop(create_batch,{'coffee_id':'c','green_g':green,'output_g':output,'roasted_at':roasted,**extra},'Tester',key or uid());return r['batch_id']
    def move(self,s,kind,key=None,**data):return self.runop(movement,{'stock_id':s,'kind':kind,**data},'Tester',key or uid())
    def total(self):return self.db.execute('SELECT COALESCE(SUM(quantity_mg+overfill_mg),0) FROM stocks').fetchone()[0]
    def order(self,remaining=10,quantity=10,payment='PAID',cancelled=False,updated='2026-11-20T03:00:00Z',fulfillments=None):
        o={'id':'o','name':'#1','displayFinancialStatus':payment,'displayFulfillmentStatus':'UNFULFILLED','cancelledAt':updated if cancelled else None,'updatedAt':updated,'lines':[{'id':'l','variant':{'id':'v'},'title':'Test','quantity':quantity,'currentQuantity':quantity,'unfulfilledQuantity':remaining}],'fulfillments':fulfillments or []}
        self.runop(order_import,o);self.db.execute("UPDATE orders SET due_at='2026-11-25T03:00:00+00:00' WHERE id='o'");return o
    def reserve(self,s,grams=150,key=None):return self.move(s,'reserve',key,grams=grams,line_id='l',use='dispatch',due_at='2026-11-25T03:00:00Z')
    def roast_record(self,**extra):return {'uid':'r1','beanId':'bean','dateTime':int(dt('2026-11-05T10:00:00+09:00').timestamp()*1000),'weightGreen':1000,'weightRoasted':850,**extra}
    def test_shopify_creation_and_archive_dates_preserve_local_deadline(self):
        o=self.order();o['createdAt']='2026-10-01T10:00:00+09:00';o['closedAt']='2026-11-20T01:00:00Z'
        self.runop(order_import,o);saved=one(self.db,"SELECT * FROM orders WHERE id='o'")
        self.assertEqual(saved['created_at'],'2026-10-01T01:00:00+00:00');self.assertIsNotNone(saved['closed_at']);self.assertEqual(saved['due_at'],'2026-11-25T03:00:00+00:00')
    def test_01_roast_actual_output_idempotent(self):
        r=self.roast_record();self.runop(roast_import,r);self.runop(roast_import,r);self.assertEqual(self.total(),850000);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
    def test_02_03_04_ledger_conservation_sales_release(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.order()
        self.move(s,'pack',package_id='p',units='4',location_id='wall')
        self.move(s,'transfer',grams=300,location_id='cafe')
        self.reserve(s);self.assertEqual(self.total(),850000);self.assertEqual(stock(self.db,s)['reserved_mg'],150000)
        wall=stock_id(self.db,b,'wall','p');self.move(wall,'sale',grams=100)
        self.assertEqual(self.total(),750000);self.assertEqual(stock(self.db,wall)['quantity_mg'],300000);self.assertEqual(stock(self.db,s)['reserved_mg'],150000)
        r=one(self.db,'SELECT * FROM reservations');self.move(s,'release',reservation_id=r['id'])
        self.assertEqual(self.total(),750000);self.assertEqual(stock(self.db,s)['reserved_mg'],0)
        for scope in rows(self.db,'SELECT * FROM stocks'):
            ledger=self.db.execute('SELECT COALESCE(SUM(delta_mg),0) FROM entries WHERE stock_id=?',(scope['id'],)).fetchone()[0];self.assertEqual(ledger,scope['quantity_mg'])
    def test_05_concurrent_consumption_duplicate_submit(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');barrier=threading.Barrier(2)
        def consume(key):
            db=connect(self.path);barrier.wait()
            try:
                with transaction(db):movement(db,{'kind':'consume','stock_id':s,'grams':600},'staff',key)
                return True
            except ValueError:return False
            finally:db.close()
        with ThreadPoolExecutor(2) as pool:r=list(pool.map(consume,['one','two']))
        self.assertEqual(sum(r),1);self.assertEqual(self.total(),250000)
        self.move(s,'consume','double',grams=100);self.move(s,'consume','double',grams=100);self.assertEqual(self.total(),150000)
        with self.assertRaises(ValueError):self.move(s,'consume','double',grams=101)
    def test_05_concurrent_reservations(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.order();barrier=threading.Barrier(2)
        def reserve(key):
            db=connect(self.path);barrier.wait()
            try:
                with transaction(db):movement(db,{'kind':'reserve','stock_id':s,'grams':600,'line_id':'l','use':'dispatch','due_at':'2026-11-25T03:00:00Z'},'staff',key)
                return True
            except ValueError:return False
            finally:db.close()
        with ThreadPoolExecutor(2) as pool:r=list(pool.map(reserve,['r-one','r-two']))
        self.assertEqual(sum(r),1);self.assertEqual(stock(self.db,s)['reserved_mg'],600000)
        with self.assertRaises(ValueError):self.move(s,'consume',grams=251)
        self.assertEqual(self.total(),850000)
    def test_06_07_08_rest_hold_tokyo(self):
        b=self.batch();batch=one(self.db,'SELECT * FROM batches WHERE id=?',(b,))
        self.assertFalse(eligibility(batch,'brew','2026-11-10T09:59:59+09:00')[0]);self.assertTrue(eligibility(batch,'brew','2026-11-10T10:00:00+09:00')[0]);self.assertTrue(eligibility(batch,'dispatch','2026-11-07T10:00:00+09:00')[0]);self.assertEqual(eligibility(batch,'brew','2026-11-05T10:00:00+09:00')[1],'2026-11-10T01:00:00+00:00')
        self.db.execute('UPDATE batches SET held=1 WHERE id=?',(b,));self.assertFalse(eligibility(one(self.db,'SELECT * FROM batches WHERE id=?',(b,)),'brew',now(self.db))[0]);self.assertEqual(self.total(),850000)
    def test_09_pack_loss_whole_units(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.move(s,'pack',package_id='p',units='4',loss_g='2.125',overfill_g='1.500',reason='Measured packaging variance')
        self.assertEqual(stock(self.db,s)['quantity_mg'],446375);self.assertEqual(self.total(),847875)
        with self.assertRaises(ValueError):self.move(s,'pack',package_id='p',units='1.5')
        self.assertEqual(self.total(),847875)
    def test_overfill_travels_with_bags_and_unpacks_into_actual_bulk(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.move(s,'pack',package_id='p',units='4',overfill_g='4.003',reason='Measured overfill')
        packed=stock_id(self.db,b,'roastery','p');self.assertEqual(self.total(),850000)
        self.move(packed,'transfer',grams=200,location_id='wall');wall=stock_id(self.db,b,'wall','p');self.assertEqual(self.total(),850000);self.assertEqual(stock(self.db,wall)['overfill_mg'],2001)
        self.move(wall,'sale',grams=100);self.assertEqual(self.total(),749000)
        self.move(wall,'unpack',grams=100,location_id='cafe');cafe=stock_id(self.db,b,'cafe');self.assertEqual(stock(self.db,cafe)['quantity_mg'],101001);self.assertEqual(self.total(),749000)
        for scope in rows(self.db,'SELECT * FROM stocks'):
            self.assertEqual(scope['overfill_mg'],self.db.execute('SELECT COALESCE(SUM(delta_overfill_mg),0) FROM entries WHERE stock_id=?',(scope['id'],)).fetchone()[0])
    def test_10_unmapped_noncoffee_and_no_name_match(self):
        o=self.order();o['lines'][0]['variant']={'id':'unknown'};self.runop(order_import,o)
        self.assertTrue(self.db.execute("SELECT 1 FROM issues WHERE kind='variant_mapping'").fetchone());self.assertEqual(len(plan(self.db)['issues']),1)
        self.db.execute("UPDATE variants SET kind='noncoffee' WHERE id='unknown'");self.assertEqual(plan(self.db)['rows'],[])
    def test_11_order_reduce_cancel_partial_and_stale(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.order(10);self.reserve(s,600)
        self.order(3,10,updated='2026-11-20T04:00:00Z');self.assertEqual(stock(self.db,s)['reserved_mg'],300000)
        self.order(10,10,updated='2026-11-20T03:00:00Z');self.assertEqual(one(self.db,"SELECT * FROM lines WHERE id='l'")['unfulfilled'],3)
        self.order(3,10,cancelled=True,updated='2026-11-20T05:00:00Z');self.assertEqual(stock(self.db,s)['reserved_mg'],0);self.assertEqual(self.total(),850000)
    def test_11_12_fulfillment_duplicate_and_refund_no_stock_return(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.move(s,'pack',package_id='p',units='4',location_id='packing');pack=stock_id(self.db,b,'packing','p')
        f={'id':'f','createdAt':'2026-11-20T02:00:00Z','status':'SUCCESS','lines':[{'line_id':'l','quantity':1}]};self.order(3,4,fulfillments=[f]);self.order(3,4,fulfillments=[f]);self.assertEqual(self.total(),850000)
        pick={'fulfillment_id':'f','picks':[{'line_id':'l','stock_id':pack,'grams':100}]};self.runop(fulfillment_pick,pick,'Tester','pick');self.runop(fulfillment_pick,pick,'Tester','pick');self.assertEqual(self.total(),750000)
        self.order(3,4,payment='REFUNDED',updated='2026-11-20T05:00:00Z',fulfillments=[f]);self.assertEqual(self.total(),750000)
        with self.assertRaises(ValueError):self.runop(fulfillment_pick,pick,'Tester','other-pick')
    def test_13_history_and_missing_output(self):
        r=self.roast_record(dateTime=int(dt('2026-10-01T10:00:00+09:00').timestamp()*1000));res=self.runop(roast_import,r);self.assertTrue(res['history_only']);self.assertEqual(self.total(),0)
        s=stock_id(self.db,res['batch_id'],'roastery');self.move(s,'opening',count_g=300,version=0,reason='Physical cutover count');self.assertEqual(self.total(),300000)
        self.runop(roast_import,self.roast_record(uid='missing',weightRoasted=0));self.assertEqual(self.total(),300000);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],1)
    def test_14_source_edit_after_consumption_preserves_ledger(self):
        r=self.roast_record();res=self.runop(roast_import,r);s=stock_id(self.db,res['batch_id'],'roastery');self.move(s,'consume',grams=500);r['weightRoasted']=200;self.runop(roast_import,r);self.assertEqual(self.total(),350000);self.assertEqual(one(self.db,'SELECT * FROM batches')['output_mg'],850000);self.assertTrue(self.db.execute("SELECT 1 FROM issues WHERE kind='source_edit'").fetchone())
    def test_15_scope_count_and_stale_version(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.move(s,'transfer',grams=300,location_id='cafe');cafe=stock_id(self.db,b,'cafe');version=stock(self.db,cafe)['version'];self.move(cafe,'count',count_g=250,version=version,reason='Measured remaining weight');self.assertEqual(stock(self.db,s)['quantity_mg'],550000)
        with self.assertRaises(ValueError):self.move(cafe,'count',count_g=200,version=version,reason='Stale count')
        self.assertEqual(self.total(),800000)
    def test_16_planner_future_readiness_and_no_double_coverage(self):
        self.db.execute("UPDATE settings SET value=? WHERE key='demo_clock'",(json.dumps('2026-11-05T02:00:00+00:00'),));b=self.batch();self.order(6,6)
        self.db.execute("UPDATE orders SET due_at='2026-11-07T01:00:00+00:00'")
        self.db.execute("INSERT INTO demands VALUES ('d','c','brew','2026-11-10T01:00:00+00:00',500000,'Forecast')")
        p=plan(self.db,14)['rows'];self.assertEqual(p[0]['covered_mg'],600000);self.assertEqual(p[1]['covered_mg'],250000);self.assertEqual(p[1]['shortage_mg'],250000);self.assertEqual(p[1]['charges_mg'],[1200000]);self.assertEqual(p[1]['yield_source'],'measured history')
        self.db.execute("UPDATE demands SET due_at='2026-11-09T01:00:00+00:00'");p=plan(self.db)['rows'];self.assertEqual(p[1]['covered_mg'],0)
    def test_16_completed_plan_not_counted_twice(self):
        c=one(self.db,'SELECT * FROM coffees');self.db.execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?,?)',('p1','c','2026-11-05T01:00:00Z',1000000,850000,'planned','Test',json.dumps(policy(c))))
        self.batch(plan_id='p1');self.order(10,10);p=plan(self.db)['rows'][0];self.assertEqual(p['covered_mg'],800000);self.assertEqual(p['shortage_mg'],200000)
    def test_16_oldest_first_and_repeated_wall_target(self):
        old=self.batch(1000,850,'2026-11-01T01:00:00Z');new=self.batch(1000,850,'2026-11-05T01:00:00Z')
        for i,day in enumerate((21,22)):self.db.execute('INSERT INTO demands VALUES (?,?,?,?,?,?)',(str(i),'c','retail',f'2026-11-{day}T01:00:00+00:00',500000,'Same total wall target'))
        p=plan(self.db)['rows'];self.assertEqual(p[0]['allocations'][0]['batch'],one(self.db,'SELECT code FROM batches WHERE id=?',(old,))['code']);self.assertEqual(p[1]['shortage_mg'],0);self.assertEqual(p[1]['allocations'][0]['kind'],'target carryover')
    def test_repeated_wall_target_rechecks_freshness(self):
        self.db.execute("UPDATE settings SET value=? WHERE key='demo_clock'",(json.dumps('2026-11-05T02:00:00Z'),));self.db.execute('UPDATE coffees SET fresh_days=6');self.batch()
        for id,day in [('one',8),('two',12)]:self.db.execute('INSERT INTO demands VALUES (?,?,?,?,?,?)',(id,'c','retail',f'2026-11-{day:02}T01:00:00Z',500000,'Wall minimum'))
        p=plan(self.db)['rows'];self.assertEqual(p[0]['covered_mg'],500000);self.assertEqual(p[1]['shortage_mg'],500000)
    def test_plan_slots_are_distinct_and_respect_weekdays(self):
        self.db.execute("UPDATE settings SET value=? WHERE key='demo_clock'",(json.dumps('2026-11-05T02:00:00Z'),));self.db.execute("UPDATE settings SET value='[0,2,4]' WHERE key='roast_days'")
        self.order(30,30);self.db.execute("UPDATE orders SET due_at='2026-11-18T01:00:00Z'")
        p=plan(self.db)['rows'][0];self.assertEqual(len(p['roast_slots']),3);self.assertEqual(len(set(p['roast_slots'])),3)
        self.assertTrue(all(dt(t).astimezone(JST).weekday() in [0,2,4] for t in p['roast_slots']));self.assertTrue(all(dt(t)<=dt('2026-11-16T01:00:00Z') for t in p['roast_slots']))
    def test_order_change_does_not_leave_fractional_bag_reservations(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.order(10,10);self.reserve(s,50);self.move(s,'pack',package_id='p',units='2');packed=stock_id(self.db,b,'roastery','p');self.reserve(packed,200)
        self.order(1,1,updated='2026-11-20T05:00:00Z');self.assertEqual(stock(self.db,packed)['reserved_mg'],0);self.assertEqual(stock(self.db,s)['reserved_mg'],50000)
    def test_imported_roast_linked_to_plan_does_not_add_stock(self):
        c=one(self.db,'SELECT * FROM coffees');self.db.execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?,?)',('p1','c','2026-11-05T01:00:00Z',1000000,850000,'planned','Imported completion',json.dumps(policy(c))))
        result=self.runop(roast_import,self.roast_record());d={'batch_id':result['batch_id'],'plan_id':'p1','reason':'Confirmed actual source UID'}
        self.runop(link_completed_plan,d,'Tester','link');self.runop(link_completed_plan,d,'Tester','link');self.assertEqual(self.total(),850000);self.assertEqual(one(self.db,'SELECT * FROM plans')['status'],'completed')
    def test_planner_does_not_promise_unpoolable_partial_bags(self):
        self.batch(200,150);self.batch(200,150);self.order(3,3)
        p=plan(self.db)['rows'][0];self.assertEqual(p['covered_mg'],200000);self.assertEqual(p['shortage_mg'],100000)
    def test_18_restart_backup_restore(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.move(s,'consume',grams=123.456)
        dest=str(Path(self.temp.name)/'backup.sqlite');backup(self.path,dest);restored=str(Path(self.temp.name)/'restored.sqlite');restore(dest,restored);new=connect(restored)
        self.assertEqual(new.execute('SELECT SUM(quantity_mg) FROM stocks').fetchone()[0],726544);self.assertEqual(new.execute('SELECT COUNT(*) FROM entries').fetchone()[0],2);self.assertEqual(new.execute('PRAGMA integrity_check').fetchone()[0],'ok');new.close();self.db.close();self.db=connect(self.path);self.assertEqual(self.total(),726544)
    def test_policy_snapshot_fixed_precision_and_immutable_history(self):
        self.assertEqual(weight('0.001'),1)
        with self.assertRaises(ValueError):weight('0.0001')
        b=self.batch();before=one(self.db,'SELECT * FROM batches WHERE id=?',(b,))['policy'];self.db.execute('UPDATE coffees SET brew_days=45,policy_version=2');self.assertEqual(one(self.db,'SELECT * FROM batches WHERE id=?',(b,))['policy'],before)
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM entries')
    def test_reversal_is_linked_and_reserved_stock_protected(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');r=self.move(s,'consume',grams=100);self.runop(movement,{'kind':'reverse','reversal_of':r['movement_id'],'reason':'Wrong measured scope'},'Tester','reverse');self.assertEqual(self.total(),850000)
        with self.assertRaises(sqlite3.IntegrityError):self.runop(movement,{'kind':'reverse','reversal_of':r['movement_id'],'reason':'Repeat correction'},'Tester','reverse2')
    def test_reservation_must_match_real_deadline_and_policy(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.order()
        with self.assertRaises(ValueError):self.move(s,'reserve',grams=100,line_id='l',use='brew',due_at='2026-11-25T03:00:00Z')
        with self.assertRaises(ValueError):self.move(s,'reserve',grams=100,line_id='l',use='dispatch',due_at='2026-11-26T03:00:00Z')
        self.assertEqual(stock(self.db,s)['reserved_mg'],0)
    def test_pack_reserved_keeps_commitment_and_mass(self):
        b=self.batch();s=stock_id(self.db,b,'roastery');self.order();self.reserve(s,200);r=one(self.db,'SELECT * FROM reservations');self.move(s,'pack_reserved',reservation_id=r['id'],location_id='packing');r2=one(self.db,'SELECT * FROM reservations');self.assertEqual(r2['quantity_mg'],200000);self.assertEqual(stock(self.db,r2['stock_id'])['package_id'],'p');self.assertEqual(self.total(),850000)
    def test_csv_preview_validation_and_duplicates(self):
        text='external_id,bean_id,roasted_at,green_g,output_g\nr1,bean,2026-11-05T10:00:00+09:00,1000,850\nr1,bean,2026-11-05T10:00:00+09:00,1000,850\nbad,bean,2026-11-05T10:00:00+09:00,1000,0\n';r=csv_preview(self.db,text);self.assertFalse(r[0]['errors']);self.assertTrue(r[1]['duplicate']);self.assertTrue(r[2]['errors']);self.assertEqual(self.total(),0)

if __name__=='__main__':unittest.main()
