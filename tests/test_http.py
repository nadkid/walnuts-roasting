"""End-to-end staff workflow over authenticated HTTP against a real SQLite server."""
import unittest,tempfile,threading,json,urllib.request,urllib.error,http.cookiejar,hmac,hashlib,base64,os
from unittest.mock import patch
from pathlib import Path
from server.app import Server
from server.db import migrate,connect,transaction
from server.demo import seed
from server.auth import password_hash

class HTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=str(Path(cls.temp.name)/'http.sqlite');migrate(cls.path);db=connect(cls.path);seed(db)
        with transaction(db):db.execute('INSERT INTO users VALUES (?,?,?,?,1)',('staff','staff',password_hash('test-staff-password'),'staff'))
        db.close();cls.server=Server(('127.0.0.1',0),cls.path);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.base='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def setUp(self):self.server.login_attempts.clear();self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));self.csrf=None
    def request(self,path,data=None,key=None,origin=None,csrf=True):
        headers={'Content-Type':'application/json','Origin':origin or self.base}
        if csrf and self.csrf:headers['X-CSRF-Token']=self.csrf
        if key:headers['Idempotency-Key']=key
        req=urllib.request.Request(self.base+'/api/'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with self.client.open(req,timeout=5) as response:return response.status,json.load(response),response.headers
        except urllib.error.HTTPError as e:return e.code,json.load(e),e.headers
    def login(self,staff=False):
        status,result,headers=self.request('login',{'name':'staff' if staff else 'demo','password':'test-staff-password' if staff else 'walnuts-demo-only'});self.assertEqual(status,200);self.csrf=result['csrf'];return headers
    def test_end_to_end_batch_pack_transfer_sale_count_reload(self):
        self.login(True)
        status,b,_=self.request('batch',{'coffee_id':'c2','green_g':'1000','output_g':'850','roasted_at':'2026-10-20T10:00:00+09:00','code':'HTTP-TEST'},'smoke-roast');self.assertEqual(status,200,b)
        _,state,_=self.request('state');s=next(s for s in state['stocks'] if s['batch_id']==b['batch_id'])
        payload={'kind':'pack','stock_id':s['id'],'package_id':'p100','units':'4','location_id':'wall'}
        self.assertEqual(self.request('move',payload,'smoke-pack')[0],200);self.assertTrue(self.request('move',payload,'smoke-pack')[1]['duplicate'])
        self.assertEqual(self.request('move',{'kind':'transfer','stock_id':s['id'],'grams':300,'location_id':'cafe'},'smoke-transfer')[0],200)
        _,state,_=self.request('state');wall=next(s for s in state['stocks'] if s['batch_id']==b['batch_id'] and s['location_id']=='wall')
        self.assertEqual(self.request('move',{'kind':'sale','stock_id':wall['id'],'grams':100},'smoke-sale')[0],200)
        _,state,_=self.request('state');scopes=[s for s in state['stocks'] if s['batch_id']==b['batch_id']];self.assertEqual(sum(s['quantity_mg'] for s in scopes),750000)
        cafe=next(s for s in scopes if s['location_id']=='cafe');count={'kind':'count','stock_id':cafe['id'],'count_g':250,'version':cafe['version'],'reason':'Measured end-of-shift weight'}
        self.assertEqual(self.request('move',count,'smoke-count')[0],200);self.assertEqual(self.request('move',count,'stale-count')[0],400)
        _,history,_=self.request('history?batch='+b['batch_id']);self.assertEqual(len(history['movements']),7)
        self.request('logout',{});self.assertEqual(self.request('state')[0],401);self.login(True);_,state,_=self.request('state');self.assertEqual(sum(s['quantity_mg'] for s in state['stocks'] if s['batch_id']==b['batch_id']),700000)
    def test_staff_adds_found_stock_without_green_then_reviews_unknown_date(self):
        self.login(True)
        _,before,_=self.request('state');green_before=before['green']['beans']
        payload={'coffee_id':'c2','grams':'125.125','location_id':'cafe','reason':'Found a missed container','code':'HTTP-FOUND-STOCK'}
        status,result,_=self.request('roasted-stock',payload,'http-found-stock');self.assertEqual(status,200,result)
        self.assertTrue(self.request('roasted-stock',payload,'http-found-stock')[1]['duplicate'])
        _,after,_=self.request('state');b=next(b for b in after['batches'] if b['id']==result['batch_id'])
        s=next(s for s in after['stocks'] if s['id']==result['stock_id'])
        self.assertTrue(b['stock_only']);self.assertEqual(b['green_mg'],0);self.assertEqual(b['output_mg'],0)
        self.assertEqual(s['quantity_mg'],125125);self.assertFalse(s['readiness']['brew']['eligible'])
        self.assertEqual(after['green']['beans'],green_before)
        review={'id':b['id'],'roasted_at':'2026-10-20T01:00:00Z','reason':'Matched original container label'}
        self.assertEqual(self.request('batch-policy',review)[0],403)
        self.request('logout',{});self.login()
        self.assertEqual(self.request('batch-policy',review)[0],200)
        _,after,_=self.request('state');s=next(s for s in after['stocks'] if s['id']==result['stock_id'])
        self.assertTrue(s['readiness']['brew']['eligible']);self.assertEqual(s['quantity_mg'],125125)
        self.assertEqual(after['green']['beans'],green_before)
        ordinary=next(b for b in after['batches'] if not b['history_only'])
        self.assertEqual(self.request('batch-policy',{**review,'id':ordinary['id']})[0],400)

    def test_roasted_stock_requires_session_csrf_idempotency_and_reason(self):
        payload={'coffee_id':'c2','grams':'100','reason':'Found coffee'}
        self.assertEqual(self.request('roasted-stock',payload,'not-signed-in')[0],401)
        self.login(True)
        self.assertEqual(self.request('roasted-stock',payload,'no-csrf',csrf=False)[0],403)
        self.assertEqual(self.request('roasted-stock',payload)[0],400)
        self.assertEqual(self.request('roasted-stock',{**payload,'reason':''},'no-reason')[0],400)

    def test_profit_read_and_shipping_are_authenticated_audited_and_csrf_protected(self):
        self.assertEqual(self.request('profit')[0],401)
        self.login(True)
        status,report,_=self.request('profit');self.assertEqual(status,200);self.assertIn('rows',report)
        payload={'order_id':'example-o1','version':0,'currency':'JPY','mode':'pickup','parcels':[],'reason':'Customer collected order'}
        self.assertEqual(self.request('order-shipping',payload,'shipping-no-csrf',csrf=False)[0],403)
        self.assertEqual(self.request('order-shipping',payload)[0],400)
        _,before,_=self.request('state');weights={r['id']:r['quantity_mg'] for r in before['stocks']}
        self.assertEqual(self.request('order-shipping',payload,'http-shipping')[0],200)
        self.assertTrue(self.request('order-shipping',payload,'http-shipping')[1]['duplicate'])
        self.assertEqual(self.request('order-shipping',payload,'http-shipping-stale')[0],400)
        _,after,_=self.request('state');order=next(o for o in after['orders'] if o['id']=='example-o1')
        self.assertEqual(order['shipping']['mode'],'pickup');self.assertEqual(order['shipping']['version'],1)
        self.assertEqual({r['id']:r['quantity_mg'] for r in after['stocks']},weights)

    def test_auth_csrf_authorization_and_no_secret_leak(self):
        self.assertEqual(self.request('state')[0],401);headers=self.login(True);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.request('settings',{'poll_seconds':60})[0],403);self.assertEqual(self.request('logout',{},csrf=False)[0],403);self.assertEqual(self.request('logout',{},origin='https://attacker.example')[0],403)
        _,state,_=self.request('state');body=json.dumps(state);self.assertNotIn('password_hash',body);self.assertNotIn('test-staff-password',body);self.assertNotIn('walnuts-demo-only',body);self.assertEqual(state['users'],[])
    def test_reject_invalid_json_and_idempotency(self):
        self.login();status,body,_=self.request('batch',{'coffee_id':'c2','green_g':1000,'output_g':850,'roasted_at':'2026-10-20T10:00:00+09:00'});self.assertEqual(status,400);self.assertIn('request identifier',body['error'])
    def test_demo_cannot_sync_live(self):
        self.login();self.assertEqual(self.server.scheduler.sync('shopify')['status'],'error');_,s,_=self.request('state');self.assertIn('Demo database is isolated',s['sync']['shopify']['last_attempt']['message'])

    def test_signed_webhooks_deduplicate_and_reject_tampering(self):
        db=connect(self.path);db.execute("UPDATE settings SET value='false' WHERE key='demo'")
        raw=b'{"id":123,"customer":{"email":"not-stored@example.invalid"}}';secret='fixture-only-webhook-secret'
        def post(body,signature,delivery='delivery-1'):
            req=urllib.request.Request(self.base+'/api/webhook/shopify',data=body,headers={'Content-Type':'application/json','X-Shopify-Hmac-Sha256':signature,'X-Shopify-Shop-Domain':'test.myshopify.com','X-Shopify-Webhook-Id':delivery,'X-Shopify-Topic':'orders/updated'})
            try:
                with self.client.open(req) as response:return response.status
            except urllib.error.HTTPError as e:return e.code
        signature=base64.b64encode(hmac.new(secret.encode(),raw,hashlib.sha256).digest()).decode()
        try:
            with patch.dict(os.environ,{'SHOPIFY_WEBHOOK_SECRET':secret,'SHOPIFY_SHOP':'test.myshopify.com'}):
                self.assertEqual(post(raw,'invalid'),401);self.assertEqual(post(raw,signature),200);self.assertEqual(post(raw,signature),200)
                self.assertEqual(post(raw+b' ',signature),401)
            records=[dict(r) for r in db.execute('SELECT * FROM webhook_deliveries')];self.assertEqual(len(records),1);self.assertNotIn('not-stored',json.dumps(records));self.assertIsNone(records[0]['processed_at'])
        finally:db.execute("UPDATE settings SET value='true' WHERE key='demo'");db.close()

    def test_staff_can_create_wholesale_order_and_see_customer_and_demand(self):
        self.login(True)
        payload={'customer':{'business':'HTTP fixture café','email':'fixture@example.invalid'},'status':'CONFIRMED','payment':'PENDING','due_at':'2026-11-12T03:00:00Z','lines':[{'coffee_id':'c2','unit_g':'100','quantity':'2'}]}
        status,result,_=self.request('wholesale',payload,'http-wholesale');self.assertEqual(status,200,result)
        self.assertTrue(self.request('wholesale',payload,'http-wholesale')[1]['duplicate'])
        _,state,_=self.request('state');o=next(o for o in state['orders'] if o['id']==result['order_id']);self.assertEqual(o['source'],'wholesale');self.assertEqual(o['wholesale']['customer']['business'],'HTTP fixture café');self.assertEqual(o['lines'][0]['required_mg'],200000);self.assertNotEqual(o['lines'][0]['status'],'Awaiting payment');self.assertTrue(any(r['id']==o['lines'][0]['id'] for r in state['planner']['rows']))

    def test_staff_green_receipt_count_and_export_are_persistent(self):
        self.login(True)
        payload={'name':'HTTP green fixture','currency':'JPY','coffee_ids':['c1']}
        status,b,_=self.request('green-bean',payload,'http-green-bean');self.assertEqual(status,200,b)
        purchase={'bean_id':b['id'],'grams':'10000','total':'24000','received_at':'2026-11-01T03:00:00Z','supplier':'Fixture supplier','lot':'TEST'}
        self.assertEqual(self.request('green-purchase',purchase,'http-green-purchase')[0],200)
        self.assertTrue(self.request('green-purchase',purchase,'http-green-purchase')[1]['duplicate'])
        _,s,_=self.request('state');bean=next(x for x in s['green']['beans'] if x['id']==b['id'])
        counted={'bean_id':b['id'],'grams':'8000','version':bean['version'],'reason':'Fixture opening count'}
        self.assertEqual(self.request('green-count',counted,'http-green-count')[0],200)
        self.assertEqual(self.request('green-count',counted,'http-green-stale')[0],400)
        _,s,_=self.request('state');bean=next(x for x in s['green']['beans'] if x['id']==b['id']);self.assertEqual(bean['quantity_mg'],8000000);self.assertEqual(bean['last_price_per_kg'],2400)
        e=next(e for e in s['green']['events'] if e['bean_id']==b['id'] and e['kind']=='purchase')
        self.assertEqual(self.request('green-reverse',{'event_id':e['id'],'reason':'Fixture'},'http-green-reverse')[0],403)
        self.request('logout',{});self.login();_,export,_=self.request('export');self.assertTrue(any(x['id']==b['id'] for x in export['green_beans']));self.assertTrue(any(x['bean_id']==b['id'] for x in export['green_events']))

    def test_shared_product_mapping_is_admin_only_and_square_preview_is_visible(self):
        from server import products
        db=connect(self.path)
        with transaction(db):
            products.seed_shopify(db)
            products.upsert(db,'square',{'id':'http-square-fixture','name':'Example Kiri coffee beans','variation':'100g'})
        item=next(i for i in products.snapshot(db)['catalog'] if i['external_id']=='http-square-fixture');pid=next(p['id'] for p in products.snapshot(db)['products'] if p['coffee_id']=='c1' and p['weight_mg']==100000);db.close()
        payload={'source':'square','external_id':item['external_id'],'version':item['version'],'kind':'coffee','product_id':pid}
        self.login(True);self.assertEqual(self.request('product-map',payload,'http-map-staff')[0],403);self.assertEqual(self.request('square-config',{'enabled':True})[0],403)
        self.request('logout',{});self.login();self.assertEqual(self.request('product-map',payload,'http-map-admin')[0],200)
        _,s,_=self.request('state');v=next(i for i in s['products']['catalog'] if i['external_id']==item['external_id']);self.assertEqual(v['product_id'],pid);self.assertFalse(s['settings']['square_enabled']);self.assertIn('square',s['sync'])
