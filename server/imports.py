"""Source records never rewrite posted inventory. Imports run inside transactions."""
import json, csv, io
from datetime import datetime, timezone
from .db import uid, one, rows, settings
from . import blends
from .domain import stamp, now, dt, weight, positive, create_batch, issue, audit, stock, delta, begin_move, eligibility

def roast_import(db,r,actor='Roast.World'):
    external=str(r.get('uid','')).strip()
    if not external: raise ValueError('External roast ID is required.')
    existing=db.execute('SELECT * FROM batches WHERE external_id=?',(external,)).fetchone()
    start=settings(db).get('roastworld_start_at')
    if start and not existing:
        try:source_time=datetime.fromtimestamp(int(r['dateTime'])/1000,timezone.utc)
        except (ValueError,KeyError,TypeError,OverflowError,OSError):source_time=None
        if source_time is not None and source_time<dt(start):
            db.execute("UPDATE issues SET resolved=1 WHERE source='roastworld' AND external_id=? AND kind='import_review'",(external,))
            return {'skipped':True,'reason':'before_import_start'}
    db.execute('INSERT INTO imports VALUES (?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',('roastworld',external,json.dumps(r),now(db)))
    if existing:
        old=json.loads(existing['source_json'] or '{}')
        changed=any(old.get(k)!=r.get(k) for k in ('weightGreen','weightRoasted','dateTime','beanId','roastName','tags'))
        if changed: issue(db,'roastworld',external,'source_edit','Source weights, date or coffee changed. Review the source snapshot; posted inventory and batch policy were preserved.')
        db.execute('UPDATE batches SET source_json=?,source_updated=? WHERE id=?',(json.dumps(r),str(r.get('updatedAt','')),existing['id']))
        return {'batch_id':existing['id'],'duplicate':True}
    coffee_id,routing_error=blends.route(db,r)
    mapping={'coffee_id':coffee_id} if coffee_id else None
    errors=[]
    if not mapping: errors.append(routing_error or 'Bean mapping missing')
    try:
        roasted=stamp(datetime.fromtimestamp(int(r['dateTime'])/1000,timezone.utc));g=positive(r['weightGreen']);o=positive(r['weightRoasted'])
        if o>=g or dt(roasted)>dt(now(db)): raise ValueError()
    except (ValueError,KeyError,TypeError,OverflowError): errors.append('Confirm credible measured input/output and past roast timestamp')
    if not errors and blends.profile(db,coffee_id):
        try:blends.charge(db,coffee_id,roasted,g,check_stock=bool(settings(db)['cutover_at'] and dt(roasted)>=dt(settings(db)['cutover_at'])))
        except ValueError as e:errors.append(str(e))
    if errors:
        issue(db,'roastworld',external,'import_review','; '.join(errors));return {'pending':True}
    cutover=settings(db)['cutover_at'];history=not cutover or dt(roasted)<dt(cutover)
    result=create_batch(db,{'coffee_id':mapping['coffee_id'],'green_g':str(g/1000),'output_g':str(o/1000),'roasted_at':roasted},actor,'roastworld:'+external,external,history)
    db.execute('UPDATE batches SET source_json=?,source_updated=? WHERE id=?',(json.dumps(r),str(r.get('updatedAt','')),result['batch_id']))
    # Create zero stock scope so historical opening counts can be entered explicitly.
    from .domain import stock_id
    stock_id(db,result['batch_id'],'roastery')
    db.execute("UPDATE issues SET resolved=1 WHERE source='roastworld' AND external_id=? AND kind='import_review'",(external,))
    return {**result,'history_only':history}

def release_excess(db,line_id,limit,actor):
    rs=rows(db,'SELECT * FROM reservations WHERE line_id=? ORDER BY created_at,rowid',(line_id,));left=limit
    for r in rs:
        keep=min(r['quantity_mg'],max(0,left))
        current=stock(db,r['stock_id']);mapping=one(db,'SELECT v.* FROM variants v JOIN lines l ON l.variant_id=v.id WHERE l.id=?',(line_id,))
        if mapping['kind']!='coffee' or current['coffee_id']!=mapping['coffee_id'] or current['package_id'] not in ('bulk',mapping['package_id']):keep=0
        if current['package_mg']:keep=(keep//current['package_mg'])*current['package_mg']
        left-=keep
        if keep<r['quantity_mg']:
            audit(db,actor,'order_allocation_released',{'reservation':r,'retained_mg':keep})
            if keep: db.execute('UPDATE reservations SET quantity_mg=? WHERE id=?',(keep,r['id']))
            else: db.execute('DELETE FROM reservations WHERE id=?',(r['id'],))

def order_import(db,o,actor='Shopify'):
    id=o['id']; updated=stamp(o['updatedAt'])
    existing=db.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
    if existing and dt(existing['updated_at'])>dt(updated): return {'stale':True}
    cancelled=bool(o.get('cancelledAt'));payment=o.get('displayFinancialStatus','UNKNOWN')
    db.execute('INSERT INTO orders(id,number,payment,cancelled,fulfillment,updated_at,source,delivery) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET number=excluded.number,payment=excluded.payment,cancelled=excluded.cancelled,fulfillment=excluded.fulfillment,updated_at=excluded.updated_at,delivery=excluded.delivery',(id,o['name'],payment,int(cancelled),o.get('displayFulfillmentStatus',''),updated,'shopify',o.get('deliveryMethod','Not supplied — confirm dispatch / pickup')))
    db.execute('UPDATE orders SET created_at=COALESCE(?,created_at),closed_at=? WHERE id=?',(stamp(o['createdAt']) if o.get('createdAt') else None,stamp(o['closedAt']) if o.get('closedAt') else None,id))
    seen=[]
    for l in o['lines']:
        lid=l['id'];seen.append(lid);variant=l.get('variant',{});vid=variant.get('id') if variant else None;vid=vid or 'unmapped:'+lid
        db.execute("INSERT OR IGNORE INTO variants(id,sku,kind) VALUES (?,?,'unresolved')",(vid,l.get('sku') or ''))
        remaining=int(l['unfulfilledQuantity']);quantity=int(l.get('currentQuantity',l['quantity']))
        if remaining<0 or quantity<0 or remaining>quantity: raise ValueError('Invalid imported line quantities; review source order.')
        db.execute('INSERT INTO lines VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET variant_id=excluded.variant_id,title=excluded.title,quantity=excluded.quantity,unfulfilled=excluded.unfulfilled',(lid,id,vid,l['title'],quantity,remaining))
        v=one(db,'SELECT * FROM variants WHERE id=?',(vid,))
        if v['kind']=='unresolved': issue(db,'shopify',vid,'variant_mapping','Map this stable variant ID to coffee and net package size, exclude merchandise, or leave bundles unresolved.')
        size=one(db,'SELECT weight_mg FROM packages WHERE id=?',(v['package_id'],))['weight_mg'] if v['kind']=='coffee' and v['package_id'] else 0
        eligible=not cancelled and payment in settings(db)['eligible_payments']
        release_excess(db,lid,remaining*size if eligible else 0,actor)
    for l in rows(db,'SELECT id FROM lines WHERE order_id=?',(id,)):
        if l['id'] not in seen:
            db.execute('UPDATE lines SET unfulfilled=0 WHERE id=?',(l['id'],));release_excess(db,l['id'],0,actor)
    for f in o.get('fulfillments',[]):
        if f.get('status') not in ('SUCCESS','success'): continue
        db.execute('INSERT OR IGNORE INTO fulfillment_events VALUES (?,?,?,?,0)',(f['id'],id,stamp(f['createdAt']),json.dumps(f)))
        event=one(db,'SELECT * FROM fulfillment_events WHERE id=?',(f['id'],))
        if not event['recorded']: issue(db,'shopify',f['id'],'external_fulfillment','Shopify confirms fulfillment. Record the actual batch pick; inventory has not been guessed or deducted.')
    from .profit import import_shopify
    import_shopify(db,o)
    return {'order_id':id}

def fulfillment_pick(db,d,actor,request_id):
    m,repeat=begin_move(db,'shipment',actor,d,request_id)
    if repeat:return {'duplicate':True,'movement_id':m}
    f=one(db,'SELECT * FROM fulfillment_events WHERE id=?',(d['fulfillment_id'],))
    if f['recorded']: raise ValueError('Fulfillment already reconciled.')
    source=json.loads(f['payload']);required={}
    for item in source['lines']:
        l=one(db,'SELECT l.*,v.kind,v.package_id,v.coffee_id FROM lines l JOIN variants v ON v.id=l.variant_id WHERE l.id=?',(item['line_id'],))
        if l['kind']=='noncoffee': continue
        if l['kind']!='coffee': raise ValueError('Map every coffee variant before confirming the pick.')
        p=one(db,'SELECT * FROM packages WHERE id=?',(l['package_id'],))
        required[l['id']]={'mg':int(item['quantity'])*p['weight_mg'],'coffee':l['coffee_id'],'package':p['id']}
    allocated={}
    for pick in d['picks']:
        line=pick['line_id'];q=positive(pick['grams']);s=stock(db,pick['stock_id']);req=required.get(line)
        if not req or req['coffee']!=s['coffee_id'] or req['package']!=s['package_id']: raise ValueError('Picked batch/package must match the fulfillment line.')
        eligible,_,why=eligibility(s,'dispatch',now(db))
        if not eligible: raise ValueError('Pick is ineligible: '+why+'. Use an audited policy override if appropriate.')
        # Remaining-order reservations cannot be consumed for an already fulfilled quantity.
        extra=-delta(db,m,s['id'],-q)
        db.execute('INSERT INTO fulfillment_picks(fulfillment_id,line_id,stock_id,movement_id,quantity_mg,overfill_mg) VALUES (?,?,?,?,?,?)',(f['id'],line,s['id'],m,q,extra))
        allocated[line]=allocated.get(line,0)+q
    if {k:v['mg'] for k,v in required.items()}!=allocated: raise ValueError('Picks must exactly cover all coffee quantities in this fulfillment.')
    db.execute('UPDATE fulfillment_events SET recorded=1 WHERE id=?',(f['id'],));db.execute("UPDATE issues SET resolved=1 WHERE source='shopify' AND external_id=? AND kind='external_fulfillment'",(f['id'],));audit(db,actor,'fulfillment_pick',d)
    return {'movement_id':m}

def csv_preview(db,text):
    records=[];seen=set()
    for n,r in enumerate(csv.DictReader(io.StringIO(text)),2):
        errors=[]
        if not {'external_id','bean_id','roasted_at','green_g','output_g'}<=r.keys(): raise ValueError('Use the supplied CSV template; this is not an asserted RoasTime export format.')
        id=r['external_id'].strip()
        duplicate=id in seen or bool(db.execute('SELECT 1 FROM imports WHERE source=? AND external_id=?',('roastworld',id)).fetchone());seen.add(id)
        try:
            if not id: raise ValueError('External ID is required')
            time=dt(r['roasted_at']);g=positive(r['green_g']);o=positive(r['output_g'])
            if o>=g or time>dt(now(db)): raise ValueError('Check actual weights and roast date')
        except (ValueError,KeyError) as e: errors.append(str(e))
        if not db.execute('SELECT 1 FROM bean_mappings WHERE external_id=?',(r['bean_id'],)).fetchone(): errors.append('Bean mapping required')
        records.append({'row':n,'external_id':id,'duplicate':duplicate,'errors':errors,'source':{'uid':id,'beanId':r['bean_id'],'dateTime':int(time.timestamp()*1000) if not errors else None,'weightGreen':r['green_g'],'weightRoasted':r['output_g']}})
    if not records: raise ValueError('No CSV records found.')
    return records
