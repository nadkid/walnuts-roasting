"""Shared physical products with separately approved source identities."""
import re,unicodedata
from decimal import Decimal
from difflib import SequenceMatcher
from .db import rows,one,uid
from .domain import audit,begin_move

def detected_weight(text):
    values=set()
    for value,unit in re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|g|グラム|ｇ)(?![a-z])',unicodedata.normalize('NFKC',text).lower()):
        n=Decimal(value)*(1000000 if unit=='kg' else 1000)
        if n==n.to_integral_value() and 0<n<=10**12:values.add(int(n))
    return next(iter(values)) if len(values)==1 else None

def product(db,coffee,package):
    one(db,'SELECT id FROM coffees WHERE id=?',(coffee,));one(db,'SELECT id FROM packages WHERE id=?',(package,))
    old=db.execute('SELECT id FROM sale_products WHERE coffee_id=? AND package_id=?',(coffee,package)).fetchone()
    if old:return old['id']
    id=uid();db.execute('INSERT INTO sale_products VALUES (?,?,?)',(id,coffee,package));return id

def upsert(db,source,item):
    id=str(item['id']);name=str(item.get('name',''));variation=str(item.get('variation',''));sku=str(item.get('sku') or '');unit=str(item.get('unit') or '')
    w=detected_weight(name+' '+variation);old=db.execute('SELECT * FROM sale_catalog WHERE source=? AND external_id=?',(source,id)).fetchone()
    review=old['review'] if old else 0
    if old and old['kind']=='coffee':
        p=one(db,'SELECT k.weight_mg FROM sale_products p JOIN packages k ON k.id=p.package_id WHERE p.id=?',(old['product_id'],))
        if (w is not None and w!=p['weight_mg']) or unit:review=1
    values=(name,variation,sku,w,unit,int(item.get('active',True)),review)
    if old and values==tuple(old[k] for k in ('name','variation','sku','weight_mg','unit','active','review')):return
    db.execute('INSERT INTO sale_catalog(source,external_id,name,variation,sku,weight_mg,unit,active,review) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET name=excluded.name,variation=excluded.variation,sku=excluded.sku,weight_mg=excluded.weight_mg,unit=excluded.unit,active=excluded.active,review=excluded.review,version=sale_catalog.version+1',(source,id,*values))

def seed_shopify(db):
    for c in rows(db,'SELECT id FROM coffees'):
        for p in rows(db,'SELECT id FROM packages'):product(db,c['id'],p['id'])
    for v in rows(db,"SELECT v.*,COALESCE((SELECT title FROM lines WHERE variant_id=v.id LIMIT 1),v.sku) name FROM variants v WHERE v.id NOT LIKE 'wholesale:%'"):
        if not db.execute("SELECT 1 FROM sale_catalog WHERE source='shopify' AND external_id=?",(v['id'],)).fetchone():upsert(db,'shopify',v)
        pid=product(db,v['coffee_id'],v['package_id']) if v['kind']=='coffee' and v['coffee_id'] and v['package_id'] else None
        db.execute("UPDATE sale_catalog SET kind=?,product_id=?,version=version+1 WHERE source='shopify' AND external_id=? AND (kind!=? OR product_id IS NOT ?)",(v['kind'],pid,v['id'],v['kind'],pid))

def normalized(text):
    s=unicodedata.normalize('NFKD',text).casefold()
    s=re.sub(r'\d+(?:\.\d+)?\s*(?:kg|g|グラム)\b',' ',s)
    return ' '.join(re.findall(r'[^\W_]+',''.join(c for c in s if not unicodedata.combining(c))))

def snapshot(db):
    ps=rows(db,'SELECT p.*,c.name coffee,c.profile,k.name package,k.weight_mg FROM sale_products p JOIN coffees c ON c.id=p.coffee_id JOIN packages k ON k.id=p.package_id ORDER BY c.name,k.weight_mg')
    items=rows(db,"SELECT * FROM sale_catalog WHERE source!='square' OR in_scope=1 ORDER BY source,name,variation,external_id")
    for item in items:
        item['suggestions']=[]
        if item['kind']!='unresolved' and not item['review']:continue
        if item['unit'] or re.search(r'\b(bundle|discovery|assortment|sample box)\b|飲み比べ|セット',item['name'],re.I):continue
        for p in ps:
            if item['weight_mg'] and item['weight_mg']!=p['weight_mg']:continue
            aliases=[p['coffee']+' '+p['profile']]+[x['name']+' '+x['variation'] for x in items if x['product_id']==p['id'] and x['source']!=item['source'] and not x['review']]
            score=max(SequenceMatcher(None,normalized(item['name']+' '+item['variation']),normalized(a)).ratio() for a in aliases)
            if score>=(.35 if item['weight_mg'] else .8):item['suggestions'].append({'id':p['id'],'score':round(score,3),'label':p['coffee']+' · '+p['profile']+' · '+str(p['weight_mg']/1000)+' g'})
        item['suggestions']=sorted(item['suggestions'],key=lambda x:(-x['score'],x['id']))[:3]
    return {'products':ps,'catalog':items}

def approve(db,d,actor,request_id):
    m,repeat=begin_move(db,'product_mapping',actor,d,request_id)
    if repeat:return {'duplicate':True}
    item=one(db,'SELECT * FROM sale_catalog WHERE source=? AND external_id=?',(d['source'],d['external_id']))
    if int(d['version'])!=item['version']:raise ValueError('This catalogue item changed. Refresh and review the mapping again.')
    if item['source']=='square' and not item['in_scope']:raise ValueError('This item is outside the Square Beans category.')
    kind=d['kind'];pid=None
    if kind not in ('coffee','noncoffee','unresolved'):raise ValueError('Choose a classification.')
    if kind=='coffee':
        if re.search(r'\b(bundle|discovery|assortment|sample box)\b|飲み比べ|セット',item['name'],re.I):raise ValueError('Bundles and assortments require an explicit composition model. Leave this listing unresolved.')
        if item['unit']:raise ValueError('This Square variation is sold by a measurement unit. Configure fixed bag variations in Square before mapping it.')
        pid=d.get('product_id') or product(db,d['coffee_id'],d['package_id'])
        p=one(db,'SELECT p.*,k.weight_mg FROM sale_products p JOIN packages k ON k.id=p.package_id WHERE p.id=?',(pid,))
        if item['weight_mg'] and item['weight_mg']!=p['weight_mg']:raise ValueError('The selected bag size conflicts with the catalogue label. Correct the source variation first.')
    if item['source']=='shopify':
        if db.execute('SELECT 1 FROM reservations r JOIN lines l ON l.id=r.line_id WHERE l.variant_id=?',(item['external_id'],)).fetchone():raise ValueError('Release this Shopify variant’s allocations before remapping it.')
        db.execute('UPDATE variants SET kind=?,coffee_id=?,package_id=? WHERE id=?',(kind,p['coffee_id'] if pid else None,p['package_id'] if pid else None,item['external_id']))
        if kind!='unresolved':db.execute("UPDATE issues SET resolved=1 WHERE source='shopify' AND external_id=? AND kind='variant_mapping'",(item['external_id'],))
    db.execute('UPDATE sale_catalog SET kind=?,product_id=?,review=0,version=version+1 WHERE source=? AND external_id=?',(kind,pid,item['source'],item['external_id']))
    audit(db,actor,'product_mapping',{**d,'product_id':pid});return {'product_id':pid}


def approve_batch(db,d,actor,request_id):
    import hashlib
    items=d.get('items',[])
    if not isinstance(items,list) or not 1<=len(items)<=1000:raise ValueError('Select between 1 and 1000 items.')
    if not request_id:raise ValueError('A request identifier is required.')
    for i,item in enumerate(items):
        if item.get('kind')!='noncoffee':raise ValueError('Bulk approval is limited to explicit non-coffee exclusions.')
        key='product-batch:'+hashlib.sha256((request_id+':'+str(i)).encode()).hexdigest()
        approve(db,item,actor,key)
    return {'count':len(items)}
