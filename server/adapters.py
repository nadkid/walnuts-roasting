"""Server-only read adapters. No remote writes, roast controls, or client secrets."""
import os, json, re, time, threading, urllib.request, urllib.error, urllib.parse
from datetime import timedelta
from .db import connect, transaction, settings, uid, rows
from .domain import stamp, now, dt, issue
from .imports import roast_import, order_import

class SyncError(Exception): pass

def request_json(url,headers=None,body=None):
    for attempt in range(4):
        try:
            request_headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'WalnutsRoastery/0.1',**(headers or {})}
            payload=(urllib.parse.urlencode(body).encode() if request_headers['Content-Type']=='application/x-www-form-urlencoded' else json.dumps(body).encode()) if body is not None else None
            req=urllib.request.Request(url,data=payload,headers=request_headers)
            with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code in (401,403):raise SyncError('Authentication rejected. Check server credentials and app permissions.')
            if e.code not in (429,500,502,503,504):raise SyncError('Provider rejected request (HTTP '+str(e.code)+'). Review the pinned API and scopes.')
            if attempt==3:raise SyncError('Provider rate limit or outage. Retry later; existing inventory is unchanged.')
            try:delay=min(60,max(2**attempt,int(e.headers.get('Retry-After','0'))))
            except ValueError:delay=2**attempt
            time.sleep(delay)
        except (urllib.error.URLError,TimeoutError,OSError,ValueError):
            if attempt==3:raise SyncError('Connection failed or invalid provider response. Check connectivity and retry.')
            time.sleep(2**attempt)

def roast_records(key,resource='roasts'):
    page=1
    while True:
        data=request_json('https://api.roast.world/api/v3/public/'+resource+'?size=100&page='+str(page),{'x-api-key':key})
        if not isinstance(data.get('data'),list) or 'totalPages' not in data:raise SyncError('Unexpected Roast.World response; nothing guessed.')
        yield from data['data']
        if page>=int(data['totalPages']):break
        page+=1
        if page>10000:raise SyncError('Pagination safety limit reached.')

class Shopify:
    def __init__(self):
        self.shop=os.environ.get('SHOPIFY_SHOP','')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com',self.shop):raise SyncError('Set SHOPIFY_SHOP to the canonical myshopify.com hostname.')
        self.token=os.environ.get('SHOPIFY_ACCESS_TOKEN')
        if not self.token:
            client=os.environ.get('SHOPIFY_CLIENT_ID');secret=os.environ.get('SHOPIFY_CLIENT_SECRET')
            if not client or not secret:raise SyncError('Shopify credentials are not configured on the server.')
            data=request_json('https://'+self.shop+'/admin/oauth/access_token',headers={'Content-Type':'application/x-www-form-urlencoded'},body={'grant_type':'client_credentials','client_id':client,'client_secret':secret})
            self.token=data.get('access_token')
            if not self.token:raise SyncError('Token exchange failed. Confirm same-organization app installation.')
    def query(self,query,variables):
        for attempt in range(4):
            data=request_json('https://'+self.shop+'/admin/api/2026-10/graphql.json',{'X-Shopify-Access-Token':self.token},{'query':query,'variables':variables})
            errors=data.get('errors',[])
            if errors:
                if all(e.get('extensions',{}).get('code')=='THROTTLED' for e in errors) and attempt<3:time.sleep(2**(attempt+1));continue
                raise SyncError('Shopify GraphQL rejected the query. Verify read_orders access and API schema; no customer payload was logged.')
            status=data.get('extensions',{}).get('cost',{}).get('throttleStatus',{})
            if status.get('currentlyAvailable',1000)<100:time.sleep(min(10,max(1,100/max(1,status.get('restoreRate',50)))))
            if 'data' not in data:raise SyncError('Missing Shopify query data.')
            return data['data']
        raise SyncError('Shopify throttled synchronization. Retry later.')
    def catalog(self):
        after=None
        while True:
            result=self.query('query($after:String){productVariants(first:100,after:$after){nodes{id title sku product{title} selectedOptions{name value}} pageInfo{hasNextPage endCursor}}}',{'after':after})['productVariants']
            for v in result['nodes']:
                yield {'id':v['id'],'name':v['product']['title'],'variation':' / '.join(x['value'] for x in v.get('selectedOptions',[])) or v['title'],'sku':v.get('sku') or ''}
            if not result['pageInfo']['hasNextPage']:return
            after=result['pageInfo']['endCursor']
    def orders(self,since):
        after=None
        while True:
            data=self.query('query($after:String,$q:String!){orders(first:20,after:$after,query:$q,sortKey:UPDATED_AT){nodes{id name createdAt closedAt updatedAt cancelledAt displayFinancialStatus displayFulfillmentStatus processedAt currencyCode taxesIncluded currentShippingPriceSet{shopMoney{amount currencyCode}}} pageInfo{hasNextPage endCursor}}}',{'after':after,'q':"updated_at:>='"+stamp(since)+"'"})['orders']
            for o in data['nodes']:
                o['lines']=self.connection(o['id'],'lineItems','id title sku quantity currentQuantity unfulfilledQuantity variant{id} priceAfterAllDiscountsBeforeTaxesSet{shopMoney{amount currencyCode}} originalTotalSet{shopMoney{amount currencyCode}} discountAllocations{allocatedAmountSet{shopMoney{amount currencyCode}}} taxLines{priceSet{shopMoney{amount currencyCode}}}')
                shipping=self.connection(o['id'],'shippingLines','title deliveryCategory isRemoved taxLines{priceSet{shopMoney{amount currencyCode}}}')
                o['shippingLines']=shipping
                o['deliveryMethod']=' / '.join(s['title']+((' · '+s['deliveryCategory']) if s.get('deliveryCategory') else '') for s in shipping) or 'Not supplied — confirm dispatch / pickup'
                details=self.query('query($id:ID!){order(id:$id){refunds{id createdAt totalRefundedSet{shopMoney{amount currencyCode}}} fulfillments(first:250){id createdAt status}}}',{'id':o['id']})['order']
                fs=details['fulfillments'];o['refunds']=details.get('refunds',[])
                for refund in o['refunds']:
                    refund['refundLineItems']=self.connection(refund['id'],'refundLineItems','quantity lineItem{id} subtotalSet{shopMoney{amount currencyCode}} totalTaxSet{shopMoney{amount currencyCode}}',root='refund')
                    refund['refundShippingLines']=self.connection(refund['id'],'refundShippingLines','subtotalAmountSet{shopMoney{amount currencyCode}} taxAmountSet{shopMoney{amount currencyCode}}',root='refund')
                    refund['transactions']=self.connection(refund['id'],'transactions','status kind',root='refund')
                    refund['orderAdjustments']=self.connection(refund['id'],'orderAdjustments','id',root='refund')
                if len(fs)>=250:raise SyncError('Order reached fulfillment retrieval limit. Reconcile it before advancing sync.')
                for f in fs:
                    f['lines']=[{'line_id':i['lineItem']['id'],'quantity':i['quantity']} for i in self.connection(f['id'],'fulfillmentLineItems','quantity lineItem{id}',root='fulfillment')]
                o['fulfillments']=fs;yield o
            if not data['pageInfo']['hasNextPage']:break
            after=data['pageInfo']['endCursor']
    def connection(self,id,field,selection,root='order'):
        allrows=[];after=None
        while True:
            q='query($id:ID!,$after:String){'+root+'(id:$id){'+field+'(first:100,after:$after){nodes{'+selection+'} pageInfo{hasNextPage endCursor}}}}'
            result=self.query(q,{'id':id,'after':after})[root][field];allrows+=result['nodes']
            if not result['pageInfo']['hasNextPage']:return allrows
            after=result['pageInfo']['endCursor']

class Scheduler:
    def __init__(self,path):self.path=path;self.lock=threading.Lock();self.stop=threading.Event();self.wake=threading.Event()
    def configured(self):return {'roastworld':bool(os.getenv('ROASTWORLD_API_KEY')),'shopify':bool(os.getenv('SHOPIFY_SHOP') and (os.getenv('SHOPIFY_ACCESS_TOKEN') or os.getenv('SHOPIFY_CLIENT_SECRET'))),'square':bool(os.getenv('SQUARE_ACCESS_TOKEN'))}
    def sync(self,source):
        if source not in ('roastworld','shopify','square'):raise ValueError('Unknown connection.')
        if not self.lock.acquire(False):return {'status':'busy'}
        db=connect(self.path);run=uid()
        try:
            with transaction(db):db.execute('INSERT INTO sync_runs VALUES (?,?,?,NULL,?,?)',(run,source,stamp(),'running','Connecting'))
            if settings(db)['demo']:raise SyncError('Demo database is isolated. Live sync is disabled.')
            if not self.configured()[source]:raise SyncError('Not configured. Add credentials to the server environment; never enter them in chat.')
            started=stamp();count=0;ignored=0;review=0
            if source=='roastworld':
                seen=set()
                for bean in roast_records(os.environ['ROASTWORLD_API_KEY'],'beans'):
                    bid=str(bean.get('beanId') or bean.get('uid') or '')
                    if bid:
                        with transaction(db):db.execute('INSERT INTO imports VALUES (?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',('beans',bid,json.dumps(bean),stamp()))
                for record in roast_records(os.environ['ROASTWORLD_API_KEY']):
                    with transaction(db):result=roast_import(db,record)
                    ignored+=int(result.get('reason')=='before_import_start');review+=int(bool(result.get('pending')))
                    seen.add(record['uid']);count+=1
                with transaction(db):
                    for b in rows(db,'SELECT external_id FROM batches WHERE external_id IS NOT NULL'):
                        if b['external_id'] not in seen:issue(db,source,b['external_id'],'missing_source','Previously imported roast is absent from this complete sync. Stock and history are preserved; verify with the provider.')
            elif source=='square':
                from .square import sync
                result=sync(self,db,started);count=result['records']
            else:
                from . import products
                api=Shopify()
                for item in api.catalog():
                    with transaction(db):
                        db.execute("INSERT OR IGNORE INTO variants(id,sku,kind) VALUES (?,?,'unresolved')",(item['id'],item['sku']))
                        products.upsert(db,'shopify',item)
                cfg=settings(db)
                # Repair the formerly unquoted date query with a full initial-window backfill.
                since=(cfg.get('shopify_watermark') if cfg.get('shopify_import_version')==3 else None) or stamp(dt(stamp())-timedelta(days=59))
                since=stamp(dt(since)-timedelta(minutes=10))
                for record in api.orders(since):
                    with transaction(db):order_import(db,record)
                    count+=1
                with transaction(db):
                    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('shopify_watermark',json.dumps(started)))
                    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('shopify_import_version',json.dumps(3)))
                    db.execute('UPDATE webhook_deliveries SET processed_at=? WHERE processed_at IS NULL AND received_at<=?',(stamp(),started))
                    products.seed_shopify(db)
            message=result['message'] if source=='square' else (f'{count} records checked; {ignored} before import start; {review} need review') if source=='roastworld' else f'{count} records reconciled'
            with transaction(db):db.execute('UPDATE sync_runs SET finished_at=?,status=?,message=? WHERE id=?',(stamp(),'success',message,run))
            return {'status':'success','records':count}
        except Exception as e:
            message=str(e) if isinstance(e,SyncError) else 'Sync could not complete. Review mappings and provider schema; inventory already posted remains intact.'
            with transaction(db):db.execute('UPDATE sync_runs SET finished_at=?,status=?,message=? WHERE id=?',(stamp(),'error',message,run))
            return {'status':'error','message':message}
        finally:db.close();self.lock.release()
    def loop(self):
        next_regular=0
        while not self.stop.is_set():
            configured=self.configured();db=connect(self.path);cfg=settings(db);db.close()
            if configured['square']:self.sync('square')
            if time.monotonic()>=next_regular or self.wake.is_set():
                for source in ('shopify','roastworld'):
                    if configured[source]:self.sync(source)
                next_regular=time.monotonic()+max(60,int(cfg['poll_seconds']))
            self.wake.clear();self.wake.wait(max(60,int(cfg.get('square_poll_seconds',60))) if configured['square'] else max(60,int(cfg['poll_seconds'])))
