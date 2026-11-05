"""Read-only Square client and idempotent FIFO retail-wall reconciliation."""
import json,os,hashlib,urllib.parse
from datetime import timedelta
from decimal import Decimal,InvalidOperation
from .db import rows,one,settings,transaction
from .domain import stamp,dt,now,issue,audit,stock,eligibility,delta,begin_move
from . import products
from .adapters import request_json,SyncError

class Square:
    def __init__(self):
        self.token=os.getenv('SQUARE_ACCESS_TOKEN')
        if not self.token:raise SyncError('Add SQUARE_ACCESS_TOKEN to the server .env file.')
        environment=os.getenv('SQUARE_ENVIRONMENT','production')
        if environment not in ('production','sandbox'):raise SyncError('SQUARE_ENVIRONMENT must be production or sandbox.')
        self.base='https://connect.squareup.com/v2' if environment=='production' else 'https://connect.squareupsandbox.com/v2'
    def call(self,path,body=None):
        result=request_json(self.base+path,{'Authorization':'Bearer '+self.token,'Square-Version':'2026-09-16'},body)
        if result.get('errors'):raise SyncError('Square rejected the request. Check the token, environment and read permissions; no customer data was logged.')
        return result
    def pages(self,path,key,body=None):
        cursor=None;seen=set()
        for _ in range(10000):
            if body is None:
                result=self.call(path+('&' if '?' in path else '?')+urllib.parse.urlencode({'cursor':cursor}) if cursor else path)
            else:result=self.call(path,{**body,**({'cursor':cursor} if cursor else {})})
            if not isinstance(result,dict) or not isinstance(result.get(key,[]),list):raise SyncError('Unexpected Square response; sync stopped.')
            yield from result.get(key,[])
            cursor=result.get('cursor')
            if not cursor:return
            if cursor in seen:raise SyncError('Square pagination repeated a cursor; sync stopped.')
            seen.add(cursor)
        raise SyncError('Square pagination limit reached.')
    def locations(self):return self.call('/locations').get('locations',[])
    def categories(self):return list(self.pages('/catalog/list?types=CATEGORY','objects'))
    def catalog(self):
        objects=list(self.pages('/catalog/list?types=ITEM,ITEM_VARIATION','objects'))
        parents={o['id']:o.get('item_data',{}).get('name','') for o in objects if o.get('type')=='ITEM'};variants={}
        for o in objects:
            if o.get('type')=='ITEM':
                for v in o.get('item_data',{}).get('variations',[]):variants[v['id']]=v
            elif o.get('type')=='ITEM_VARIATION':variants[o['id']]=o
        memberships={}
        for o in objects:
            if o.get('type')!='ITEM':continue
            data=o.get('item_data',{});ids={c['id'] for c in data.get('categories',[]) if c.get('id')}
            if data.get('category_id'):ids.add(data['category_id'])
            if data.get('reporting_category',{}).get('id'):ids.add(data['reporting_category']['id'])
            memberships[o['id']]=sorted(ids)
        for v in variants.values():
            d=v.get('item_variation_data',{})
            yield {'id':v['id'],'name':parents.get(d.get('item_id'),''),'variation':d.get('name',''),'sku':d.get('sku',''),'unit':d.get('measurement_unit_id') or '', 'category_ids':memberships.get(d.get('item_id'),[]),'active':not v.get('is_deleted',False)}
    def orders(self,location,since):
        body={'location_ids':[location],'limit':500,'query':{'filter':{'date_time_filter':{'updated_at':{'start_at':stamp(since)}}},'sort':{'sort_field':'UPDATED_AT','sort_order':'ASC'}}}
        yield from self.pages('/orders/search','orders',body)

def normalized(order):
    # Retain only inventory and money fields. No customer, card or address payloads.
    ls=[]
    for l in order.get('line_items',[]):
        ls.append({k:l[k] for k in ('uid','catalog_object_id','name','variation_name','quantity','quantity_unit','base_price_money','total_money','total_tax_money','total_discount_money') if k in l})
        ls[-1]['modifiers']=[{'name':m.get('name','')} for m in l.get('modifiers',[])]
    return {k:order[k] for k in ('id','location_id','version','state','created_at','updated_at','closed_at','net_amounts') if k in order}|{'line_items':ls,'has_returns':bool(order.get('returns') or order.get('refunds')),'has_fulfillment':bool(order.get('fulfillments'))}

def signature(o):
    return json.dumps({'state':o['state'],'lines':sorted([(l.get('uid',''),l.get('catalog_object_id',''),l.get('quantity',''),l.get('quantity_unit'),l.get('modifiers',[])) for l in o['line_items']],key=lambda x:x[0])},sort_keys=True)

def import_order(db,order):
    r=normalized(order);id=r['id'];old=db.execute('SELECT * FROM square_sales WHERE id=?',(id,)).fetchone();version=int(r.get('version',0));updated=stamp(r['updated_at'])
    if old and (version<old['version'] or (version==old['version'] and dt(updated)<dt(old['updated_at']))):return
    completed=stamp(r.get('closed_at') or r.get('created_at') or r['updated_at'])
    if not old and r['state']!='COMPLETED':return
    if settings(db).get('square_category_id') and not any(in_category(db,l) for l in r['line_items']) and not (old and old['movement_id']):
        if old:outside_scope(db,id)
        return
    db.execute('INSERT INTO square_sales(id,location_id,version,completed_at,updated_at,state,payload) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,completed_at=excluded.completed_at,updated_at=excluded.updated_at,state=excluded.state,payload=excluded.payload',(id,r['location_id'],version,completed,updated,r['state'],json.dumps(r)))
    for l in r['line_items']:
        vid=l.get('catalog_object_id')
        if vid and not db.execute("SELECT 1 FROM sale_catalog WHERE source='square' AND external_id=?",(vid,)).fetchone():products.upsert(db,'square',{'id':vid,'name':l.get('name',''),'variation':l.get('variation_name',''),'unit':'measured' if l.get('quantity_unit') else ''})
    if old and old['movement_id'] and signature(json.loads(old['posted_payload']))!=signature(r):
        issue(db,'square',id,'source_edit','Posted Square receipt changed. Original batch deductions are preserved; review the sale and physical stock.')
        db.execute("UPDATE square_sales SET status='source_review',detail='Source receipt changed after stock was deducted' WHERE id=?",(id,))
    if r['has_returns']:issue(db,'square',id,'return_review','Square records a return/refund. Confirm any physical return separately; stock has not been added back.')

def in_category(db,line):
    item=db.execute("SELECT in_scope FROM sale_catalog WHERE source='square' AND external_id=?",(line.get('catalog_object_id',''),)).fetchone()
    return bool(item and item['in_scope'])

def outside_scope(db,id):
    db.execute("UPDATE square_sales SET status='outside_scope',detail='Outside Square Beans category' WHERE id=?",(id,))
    db.execute("UPDATE issues SET resolved=1 WHERE source='square' AND external_id=? AND kind IN ('sale_review','return_review')",(id,))

def pending(db,id,detail,status='pending'):
    db.execute('UPDATE square_sales SET status=?,detail=? WHERE id=?',(status,detail,id))
    issue(db,'square',id,'sale_review',detail)

def post_sale(db,id):
    o=one(db,'SELECT * FROM square_sales WHERE id=?',(id,));cfg=settings(db)
    if o['movement_id'] or o['status']=='acknowledged':return
    r=json.loads(o['payload'])
    if cfg.get('square_category_id') and not any(in_category(db,l) for l in r['line_items']):return outside_scope(db,id)
    if cfg['square_start_at'] and dt(o['completed_at'])<dt(cfg['square_start_at']):
        db.execute("UPDATE square_sales SET status='before_start',detail='Before the sales deduction start' WHERE id=?",(id,));return
    if not cfg['square_enabled']:
        db.execute("UPDATE square_sales SET status='preview',detail='Preview only — no stock deducted' WHERE id=?",(id,));return
    if o['location_id']!=cfg['square_location_id']:return pending(db,id,'Receipt is from a different Square location.')
    if r['state']!='COMPLETED' or not r.get('closed_at'):return pending(db,id,'Receipt is not a completed sale with a closing timestamp.')
    if dt(o['completed_at'])>dt(now(db)):return pending(db,id,'Receipt is dated in the future.')
    if r['has_returns'] or r['has_fulfillment']:return pending(db,id,'Return, exchange or fulfillment order needs review before retail-wall deduction.')
    picks=[];available={};seen=set()
    for l in r['line_items']:
        lid=l.get('uid','');vid=l.get('catalog_object_id')
        if not lid or lid in seen:return pending(db,id,'Receipt contains a missing or duplicate line identity.')
        seen.add(lid)
        v=db.execute("SELECT * FROM sale_catalog WHERE source='square' AND external_id=?",(vid or '',)).fetchone()
        if cfg.get('square_category_id') and v and not v['in_scope']:continue
        if not v or v['kind']=='unresolved' or v['review'] or not v['active']:return pending(db,id,'Approve the Square item mapping: '+l.get('name',vid or 'Custom amount'))
        if v['kind']=='noncoffee':continue
        p=one(db,'SELECT p.*,k.weight_mg FROM sale_products p JOIN packages k ON k.id=p.package_id WHERE p.id=?',(v['product_id'],))
        try:q=Decimal(str(l['quantity']))
        except (InvalidOperation,KeyError):return pending(db,id,'Check the sold bag quantity.')
        if not q.is_finite() or q<=0 or q!=q.to_integral_value() or q>100000 or l.get('quantity_unit'):return pending(db,id,'Only whole bags can be deducted automatically.')
        if any(products.detected_weight(m.get('name','')) not in (None,p['weight_mg']) for m in l['modifiers']):return pending(db,id,'A modifier changes the bag weight. Review this receipt.')
        required=int(q)*p['weight_mg']
        candidates=rows(db,"SELECT s.id FROM stocks s JOIN batches b ON b.id=s.batch_id WHERE s.location_id='wall' AND b.coffee_id=? AND s.package_id=? ORDER BY b.roasted_at,b.code,s.id",(p['coffee_id'],p['package_id']))
        for item in candidates:
            counted=db.execute("SELECT 1 FROM entries e JOIN movements m ON m.id=e.movement_id WHERE e.stock_id=? AND m.kind IN ('count','opening') AND m.at>=? LIMIT 1",(item['id'],o['completed_at'])).fetchone()
            if counted:return pending(db,id,'Receipt predates a retail-wall physical count. Confirm whether that count already includes this sale.')
        for item in candidates:
            s=stock(db,item['id'])
            if not eligibility(s,'retail',o['completed_at'])[0]:continue
            free=available.get(s['id'],s['quantity_mg']-s['reserved_mg']);take=min(required,free//p['weight_mg']*p['weight_mg'])
            if take:picks.append((lid,s['id'],take));available[s['id']]=free-take;required-=take
            if not required:break
        if required:return pending(db,id,'Insufficient eligible, unreserved packaged retail-wall stock. Pack/transfer or reconcile stock, then retry.')
    if not picks:
        db.execute("UPDATE square_sales SET status='noncoffee',detail='All lines classified as non-coffee' WHERE id=?",(id,));db.execute("UPDATE issues SET resolved=1 WHERE source='square' AND external_id=? AND kind='sale_review'",(id,));return
    # All lines and all stock validated before any ledger entry: one receipt is atomic.
    m,repeat=begin_move(db,'square_sale','Square',{'order_id':id,'reason':'Square retail sale · oldest eligible wall batch first'},'square-sale:'+hashlib.sha256(id.encode()).hexdigest())
    if repeat:raise ValueError('Square movement exists without its receipt marker; review database integrity.')
    for lid,sid,q in picks:
        extra=-delta(db,m,sid,-q)
        db.execute('INSERT INTO square_sale_picks(sale_id,line_uid,stock_id,quantity_mg,overfill_mg) VALUES (?,?,?,?,?)',(id,lid,sid,q,extra))
    db.execute("UPDATE square_sales SET status='posted',detail='Deducted from retail wall',movement_id=?,posted_payload=? WHERE id=?",(m,o['payload'],id))
    db.execute("UPDATE issues SET resolved=1 WHERE source='square' AND external_id=? AND kind='sale_review'",(id,));audit(db,'Square','square_sale',{'order_id':id,'movement_id':m,'picks':picks})

def retry_sales(db):
    for r in rows(db,"SELECT id FROM square_sales WHERE movement_id IS NULL AND status!='acknowledged' ORDER BY completed_at,id"):post_sale(db,r['id'])

def configure(db,d,actor):
    enabled=d.get('enabled') is True;start=stamp(d['start_at']) if d.get('start_at') else None;location=d.get('location_id')
    if location:one(db,'SELECT id FROM square_locations WHERE id=? AND active=1',(location,))
    if enabled and (not start or not location):raise ValueError('Choose a Square location and a sales deduction start before enabling automatic deductions.')
    old=settings(db)
    if old.get('square_start_at') and start!=old['square_start_at'] and db.execute('SELECT 1 FROM square_sales WHERE movement_id IS NOT NULL').fetchone():raise ValueError('The start date is locked after sales post; changing it needs an audited reconciliation.')
    if old.get('square_location_id') and location!=old['square_location_id'] and db.execute('SELECT 1 FROM square_sales WHERE movement_id IS NOT NULL').fetchone():raise ValueError('This installation already contains sales for another Square location.')
    if start!=old.get('square_start_at') or location!=old.get('square_location_id'):db.execute("DELETE FROM settings WHERE key='square_watermark'")
    for k,v in {'square_enabled':enabled,'square_start_at':start,'square_location_id':location}.items():db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(v),k))
    audit(db,actor,'square_configuration',d)

def acknowledge(db,d,actor):
    o=one(db,'SELECT * FROM square_sales WHERE id=?',(d['id'],));reason=str(d.get('reason','')).strip()
    if o['movement_id'] or not reason:raise ValueError('Only an unposted receipt can be acknowledged, with a reconciliation reason.')
    db.execute("UPDATE square_sales SET status='acknowledged',detail=? WHERE id=?",(reason,o['id']))
    db.execute("UPDATE issues SET resolved=1 WHERE source='square' AND external_id=? AND kind='sale_review'",(o['id'],));audit(db,actor,'square_already_counted',d)

def snapshot(db):
    sales=rows(db,"SELECT id,completed_at,status,detail,location_id,payload,movement_id FROM square_sales WHERE status!='outside_scope' ORDER BY completed_at DESC LIMIT 200")
    for s in sales:
        s['receipt']=json.loads(s.pop('payload'))
        if settings(db).get('square_category_id'):s['receipt']['line_items']=[l for l in s['receipt']['line_items'] if in_category(db,l)]
        s['picks']=rows(db,'SELECT p.*,b.code FROM square_sale_picks p JOIN stocks st ON st.id=p.stock_id JOIN batches b ON b.id=st.batch_id WHERE sale_id=?',(s['id'],))
    return {'locations':rows(db,'SELECT * FROM square_locations ORDER BY name'),'sales':sales,'pending_count':db.execute("SELECT COUNT(*) FROM square_sales WHERE status IN ('pending','source_review')").fetchone()[0]}

def sync(scheduler,db,started):
    api=Square();categories=api.categories();cfg=settings(db);category=cfg.get('square_category_id')
    if not category:
        matches=[c['id'] for c in categories if c.get('category_data',{}).get('name','').strip().casefold()=='beans']
        if len(matches)!=1:raise SyncError('Square must have exactly one category named Beans before importing retail beans.')
        category=matches[0]
    if not any(c['id']==category for c in categories):raise SyncError('The configured Square Beans category is unavailable; stock was not changed.')
    catalog=list(api.catalog());locations=api.locations()
    with transaction(db):
        db.execute('UPDATE square_locations SET active=0')
        for l in locations:db.execute('INSERT INTO square_locations VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,active=excluded.active',(l['id'],l.get('name',l['id']),int(l.get('status')=='ACTIVE')))
        db.execute("UPDATE settings SET value=? WHERE key='square_category_id'",(json.dumps(category),))
        seen={v['id'] for v in catalog}
        for old in rows(db,"SELECT external_id FROM sale_catalog WHERE source='square' AND active=1"):
            if old['external_id'] not in seen:db.execute("UPDATE sale_catalog SET active=0,version=version+1 WHERE source='square' AND external_id=?",(old['external_id'],))
        for v in catalog:
            products.upsert(db,'square',v)
            ids=v.get('category_ids',[]);scope=int(category in ids)
            db.execute("UPDATE sale_catalog SET category_ids=?,in_scope=?,version=version+CASE WHEN in_scope!=? THEN 1 ELSE 0 END WHERE source='square' AND external_id=?",(json.dumps(ids),scope,scope,v['id']))
        for old in rows(db,'SELECT id,payload FROM square_sales WHERE movement_id IS NULL'):
            if not any(in_category(db,l) for l in json.loads(old['payload'])['line_items']):outside_scope(db,old['id'])
        products.seed_shopify(db)
    cfg=settings(db);location=cfg['square_location_id']
    if not location:return {'records':sum(category in v.get('category_ids',[]) for v in catalog),'message':f'{sum(category in v.get('category_ids',[]) for v in catalog)} Beans variations imported. Select your shop location in Product mappings.'}
    if not db.execute('SELECT 1 FROM square_locations WHERE id=? AND active=1',(location,)).fetchone():raise SyncError('Selected Square location is unavailable. Review location setup.')
    since=cfg.get('square_watermark') or cfg['square_start_at'] or stamp(dt(started)-timedelta(days=7))
    since=stamp(dt(since)-timedelta(minutes=10));count=0
    for r in api.orders(location,since):
        with transaction(db):import_order(db,r)
        count+=1
    with transaction(db):
        retry_sales(db)
        db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('square_watermark',json.dumps(started)))
    return {'records':count,'message':f'{sum(category in v.get('category_ids',[]) for v in catalog)} Beans variations; {count} receipts checked. '+('Automatic FIFO deductions enabled.' if cfg['square_enabled'] else 'Preview only — no stock deducted.')}
