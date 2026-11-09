"""Imported roasts awaiting completion, visible beside operational roast batches."""
import hashlib,json
from . import blends
from datetime import datetime,timezone
from .db import rows,one,settings
from .domain import now,dt,stamp,positive,create_batch,stock_id,audit


def version(record):
    return hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()


def source_date(record):
    try:return stamp(datetime.fromtimestamp(int(record['dateTime'])/1000,timezone.utc))
    except (ValueError,TypeError,KeyError,OverflowError,OSError):return None


def source_weight(record,key):
    try:return positive(record[key])
    except (ValueError,TypeError,KeyError,OverflowError):return None


def pending_roasts(db):
    result=[];cfg=settings(db);start=cfg.get('roastworld_start_at')
    for item in rows(db,"SELECT i.* FROM imports i WHERE i.source='roastworld' AND NOT EXISTS(SELECT 1 FROM batches b WHERE b.external_id=i.external_id)"):
        r=json.loads(item['payload']);at=source_date(r)
        if start and at and dt(at)<dt(start):continue
        bean_id=str(r.get('beanId') or '').strip();coffee_id,routing_error=blends.route(db,r);mapping={'coffee_id':coffee_id} if coffee_id else None
        green=source_weight(r,'weightGreen');output=source_weight(r,'weightRoasted');missing=[]
        if not mapping:missing.append(routing_error if routing_error and 'More than one' in routing_error else 'Bean assignment missing' if not bean_id else 'Bean mapping missing')
        if not at or dt(at)>dt(now(db)):missing.append('Confirm past roast date')
        if not green or not output or output>=green:missing.append('Confirm green input and roasted output')
        if mapping and at and green and output and output<green and dt(at)<=dt(now(db)):
            try:blends.charge(db,coffee_id,at,green,check_stock=bool(cfg['cutover_at'] and dt(at)>=dt(cfg['cutover_at'])))
            except ValueError as e:missing.append(str(e))
        # The source can be awaiting its first retry even if its mapping was just added.
        if not missing:missing.append('Ready to complete import')
        result.append({'external_id':item['external_id'],'source_version':version(r),'bean_id':bean_id,'coffee_id':mapping['coffee_id'] if mapping else None,'roasted_at':at,'green_mg':green,'output_mg':output,'missing':missing,'history_only':not cfg['cutover_at'] or bool(at and dt(at)<dt(cfg['cutover_at']))})
    return sorted(result,key=lambda r:(r['roasted_at'] is not None,r['roasted_at'] or '',r['external_id']),reverse=True)


def complete_roast(db,d,actor,request_id):
    if not request_id or len(request_id)>200:raise ValueError('A request identifier is required.')
    external=str(d.get('external_id') or '').strip()
    # Source identity guards against both double submissions and sync completing first.
    existing=db.execute('SELECT id FROM batches WHERE external_id=?',(external,)).fetchone()
    if existing:return {'batch_id':existing['id'],'duplicate':True}
    source=one(db,"SELECT payload FROM imports WHERE source='roastworld' AND external_id=?",(external,));r=json.loads(source['payload'])
    if d.get('source_version')!=version(r):raise ValueError('The source roast changed. Refresh and review its latest details.')
    coffee=one(db,'SELECT * FROM coffees WHERE id=?',(d['coffee_id'],));at=stamp(d['roasted_at']);green=positive(d['green_g']);output=positive(d['output_g'])
    if output>=green or dt(at)>dt(now(db)):raise ValueError('Confirm a past roast date and positive measured output below green input.')
    cfg=settings(db);start=cfg.get('roastworld_start_at');original=source_date(r)
    if start and ((original and dt(original)<dt(start)) or dt(at)<dt(start)):raise ValueError('This roast is before the configured import start date.')
    reason=str(d.get('reason') or '').strip()
    if not reason or len(reason)>2000:raise ValueError('Enter a short completion / correction note.')
    bean=str(r.get('beanId') or '').strip()
    if d.get('map_bean') and blends.profile(db,coffee['id']):raise ValueError('Espresso uses its tag and recipe; assign this roast only instead of mapping one component bean.')
    if d.get('map_bean'):
        if not bean:raise ValueError('The source has no bean identity. Assign a coffee to this roast only.')
        old=db.execute('SELECT coffee_id FROM bean_mappings WHERE external_id=?',(bean,)).fetchone()
        if old and old['coffee_id']!=coffee['id']:raise ValueError('This external bean already maps to another coffee. Choose this roast only or review that mapping in Settings.')
        db.execute('INSERT OR IGNORE INTO bean_mappings VALUES (?,?)',(bean,coffee['id']))
    history=not cfg['cutover_at'] or dt(at)<dt(cfg['cutover_at'])
    result=create_batch(db,{'coffee_id':coffee['id'],'roasted_at':at,'green_g':str(green/1000),'output_g':str(output/1000),'notes':reason,'recipe_id':d.get('recipe_id')},actor,'roastworld:'+external,external,history)
    # Keep the actual source snapshot. Local completion must not look like a later source edit.
    db.execute('UPDATE batches SET source_json=?,source_updated=? WHERE id=?',(json.dumps(r),str(r.get('updatedAt','')),result['batch_id']))
    stock_id(db,result['batch_id'],'roastery')
    db.execute("UPDATE issues SET resolved=1 WHERE source='roastworld' AND external_id=? AND kind='import_review'",(external,))
    audit(db,actor,'roast_import_completed',{'external_id':external,'batch_id':result['batch_id'],'coffee_id':coffee['id'],'map_bean':bool(d.get('map_bean')),'source_version':version(r),'green_mg':green,'output_mg':output,'roasted_at':at,'reason':reason})
    return {**result,'history_only':history}
