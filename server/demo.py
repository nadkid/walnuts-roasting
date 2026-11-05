import json
from datetime import timedelta
from .db import transaction,uid
from .auth import password_hash
from .domain import create_batch,movement,dt,stamp,stock_id,now
from .imports import order_import,roast_import

def seed(db):
    if db.execute('SELECT 1 FROM users').fetchone():raise ValueError('Demo seeding requires a new, empty database. Never point it at production.')
    with transaction(db):
        cfg={'demo':True,'demo_clock':'2026-11-05T03:00:00+00:00','charge_mg':1200000,'max_charge_mg':1500000,'roast_days':[0,2,4,5],'roast_days_confirmed':False,'cutover_at':'2026-10-01T00:00:00+00:00'}
        for k,v in cfg.items():db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,json.dumps(v)))
        db.execute('INSERT INTO users VALUES (?,?,?,?,1)',('demo','demo',password_hash('walnuts-demo-only'),'admin'))
        for c in [('c1','Example · Kiri','Pour-over',45,3,5,75,8500),('c2','Example · Komorebi','Espresso',7,3,5,35,8400),('c3','Example · Nagi','Pour-over',45,4,5,75,8600)]:db.execute('INSERT INTO coffees VALUES (?,?,?,?,?,?,?,?,1)',c)
        for p in [('p100','Example · 100 g bag',100000),('p200','Example · 200 g bag',200000)]:db.execute('INSERT INTO packages VALUES (?,?,?)',p)
        for bean,coffee in [('example-bean-kiri','c1'),('example-bean-komorebi','c2')]:db.execute('INSERT INTO bean_mappings VALUES (?,?)',(bean,coffee))
        for vid,c,p in [('example-v1','c1','p100'),('example-v2','c2','p200')]:db.execute("INSERT INTO variants VALUES (?,?,?,?,?,'Whole bean')",(vid,vid,c,p,'coffee'))
        batches=[]
        for c,days,g,o,code in [('c1',49,1200,1020,'EX-0917-K1'),('c1',40,1200,1010,'EX-0926-K2'),('c2',10,1200,1000,'EX-1026-E1'),('c2',2,1200,1020,'EX-1103-E2'),('c3',50,1200,1030,'EX-0916-N1')]:
            b=create_batch(db,{'coffee_id':c,'green_g':g,'output_g':o,'roasted_at':stamp(dt(now(db))-timedelta(days=days)),'code':code},'demo seed','seed:'+code);batches.append(b['batch_id'])
        db.execute('UPDATE batches SET held=1,hold_reason=? WHERE id=?',('Example cupping review',batches[4]))
        s=stock_id(db,batches[0],'roastery');movement(db,{'kind':'pack','stock_id':s,'package_id':'p100','units':'4','location_id':'wall'},'demo seed','seed:pack')
        movement(db,{'kind':'transfer','stock_id':s,'grams':300,'location_id':'cafe'},'demo seed','seed:cafe')
        movement(db,{'kind':'transfer','stock_id':stock_id(db,batches[2],'roastery'),'grams':500,'location_id':'cafe'},'demo seed','seed:espresso')
        for o in [
            {'id':'example-o1','name':'EX #1001','displayFinancialStatus':'PAID','displayFulfillmentStatus':'PARTIALLY_FULFILLED','lines':[{'id':'example-l1','variant':{'id':'example-v1'},'title':'Example Kiri · 100 g','quantity':4,'currentQuantity':4,'unfulfilledQuantity':3}]},
            {'id':'example-o2','name':'EX #1002','displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','lines':[{'id':'example-l2','variant':{'id':'example-v2'},'title':'Example Komorebi · 200 g','quantity':8,'currentQuantity':8,'unfulfilledQuantity':8}]},
            {'id':'example-o3','name':'EX #1003','displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','lines':[{'id':'example-l3','variant':{'id':'example-bundle'},'title':'Example discovery box · composition unknown','quantity':1,'currentQuantity':1,'unfulfilledQuantity':1}]},
            {'id':'example-o4','name':'EX #1004','displayFinancialStatus':'PENDING','displayFulfillmentStatus':'UNFULFILLED','lines':[{'id':'example-l4','variant':{'id':'example-v2'},'title':'Example Komorebi · 200 g','quantity':1,'currentQuantity':1,'unfulfilledQuantity':1}]}
        ]:
            o['updatedAt']=now(db);o['cancelledAt']=None;order_import(db,o,'demo seed')
            db.execute('UPDATE orders SET due_at=? WHERE id=?',(stamp(dt(now(db))+timedelta(days=2)),o['id']))
        movement(db,{'kind':'reserve','stock_id':s,'grams':200,'line_id':'example-l1','due_at':stamp(dt(now(db))+timedelta(days=2)),'use':'dispatch'},'demo seed','seed:reserve')
        db.execute('INSERT INTO demands VALUES (?,?,?,?,?,?)',('d1','c2','brew',stamp(dt(now(db))+timedelta(days=4)),1800000,'Example café forecast — one-off requirement'))
        db.execute('INSERT INTO demands VALUES (?,?,?,?,?,?)',('d2','c1','retail',stamp(dt(now(db))+timedelta(days=3)),1000000,'Example wall target — total desired stock'))
        roast_import(db,{'uid':'example-missing-weight','beanId':'example-bean-kiri','dateTime':int(dt(now(db)).timestamp()*1000),'weightGreen':1200,'weightRoasted':0},'demo seed')
