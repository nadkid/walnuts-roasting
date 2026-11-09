"""Green inventory: dated receipts, absolute counts, and once-only roast charges.
Counts are physical snapshots. A late source import predating a count is already
reflected in that count, so replaying the timeline never deducts it twice.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .db import uid, one, rows
from .domain import now, stamp, dt, weight, positive, begin_move, audit

# Prices are stored as integer minor currency units, never binary floats.
CURRENCIES={'JPY':0,'USD':2,'EUR':2,'GBP':2,'AUD':2,'CAD':2}

def money(value,currency):
    if value in (None,''):return None
    try:v=Decimal(str(value))*(10**CURRENCIES[currency])
    except (InvalidOperation,KeyError):raise ValueError('Enter a valid price and currency.')
    if not v.is_finite() or v<0 or v!=v.to_integral_value() or v>10**14:raise ValueError('Use a non-negative price with the currency’s decimal precision.')
    return int(v)

def snapshot(db):
    beans=rows(db,'SELECT * FROM green_beans ORDER BY name,id')
    from . import blends
    blend_plans=blends.planned_components(db)
    events=rows(db,'SELECT e.*,b.code batch_code FROM green_events e LEFT JOIN batch_green_components bc ON bc.event_id=e.id OR bc.event_id=e.reversal_of LEFT JOIN batches b ON b.id=COALESCE(e.batch_id,bc.batch_id) ORDER BY effective_at,CASE WHEN e.kind=\'count\' THEN 1 ELSE 0 END,e.id')
    for b in beans:
        es=[e for e in events if e['bean_id']==b['id']];q=0
        for e in es:q=e['count_mg'] if e['kind']=='count' else q+e['delta_mg']
        b.update(quantity_mg=q,counted_at=next((e['effective_at'] for e in reversed(es) if e['kind']=='count'),None),
                 coffee_ids=[r['coffee_id'] for r in db.execute('SELECT coffee_id FROM green_coffee_links WHERE bean_id=?',(b['id'],))])
        paid=next((e for e in reversed(es) if e['kind']=='purchase' and e['total_minor'] is not None and not any(x['reversal_of']==e['id'] for x in es)),None)
        b['last_price_per_kg']=float(Decimal(paid['total_minor'])*1000000/paid['delta_mg']/(10**CURRENCIES[b['currency']])) if paid else None
        b['planned_mg']=db.execute("SELECT COALESCE(SUM(p.green_mg),0) FROM plans p JOIN green_coffee_links l ON l.coffee_id=p.coffee_id WHERE l.bean_id=? AND p.status='planned'",(b['id'],)).fetchone()[0]
        b['planned_mg']+=blend_plans.get(b['id'],0)
        b['after_plans_mg']=q-b['planned_mg']
    unlinked=rows(db,"SELECT b.id,b.code,b.coffee_id,b.green_mg,b.roasted_at,c.name coffee,c.profile FROM batches b JOIN coffees c ON c.id=b.coffee_id WHERE b.history_only=0 AND NOT EXISTS(SELECT 1 FROM green_events e WHERE e.batch_id=b.id) AND NOT EXISTS(SELECT 1 FROM batch_green_components bc WHERE bc.batch_id=b.id) AND NOT EXISTS(SELECT 1 FROM movements m JOIN movements orig ON m.reversal_of=orig.id WHERE orig.kind='production' AND EXISTS(SELECT 1 FROM entries e JOIN stocks s ON s.id=e.stock_id WHERE e.movement_id=orig.id AND s.batch_id=b.id)) ORDER BY b.roasted_at")
    return {'beans':beans,'events':list(reversed(events)),'unlinked':unlinked}

def event(db,bean,kind,at,actor,movement,**kw):
    fields={'bean_id':bean,'kind':kind,'effective_at':stamp(at),'recorded_at':now(db),'actor':actor,'movement_id':movement,**kw}
    db.execute('INSERT INTO green_events('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',tuple(fields.values()))
    db.execute('UPDATE green_beans SET version=version+1 WHERE id=?',(bean,))

def record_roast(db,batch_id,movement_id,actor):
    b=one(db,'SELECT * FROM batches WHERE id=?',(batch_id,))
    if b['history_only'] or db.execute('SELECT 1 FROM green_events WHERE batch_id=?',(batch_id,)).fetchone() or db.execute('SELECT 1 FROM batch_green_components WHERE batch_id=?',(batch_id,)).fetchone():return
    blend=db.execute('SELECT ingredients FROM batch_blends WHERE batch_id=?',(batch_id,)).fetchone()
    if blend:
        if db.execute('SELECT 1 FROM movements WHERE reversal_of=?',(movement_id,)).fetchone():return
        import json
        for i in json.loads(blend['ingredients']):
            event(db,i['bean_id'],'roast',b['roasted_at'],actor,movement_id,delta_mg=-i['quantity_mg'],reason='Blend component · '+b['code'])
            eid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute('INSERT INTO batch_green_components VALUES (?,?,?,?)',(batch_id,i['bean_id'],i['quantity_mg'],eid))
        return
    # Historical unassigned batches must never inherit a newly activated recipe.
    if db.execute('SELECT 1 FROM blend_profiles WHERE coffee_id=?',(b['coffee_id'],)).fetchone():return
    link=db.execute('SELECT bean_id FROM green_coffee_links WHERE coffee_id=?',(b['coffee_id'],)).fetchone()
    if not link:return
    # A production correction must not be reintroduced by a later mapping/retry.
    if db.execute('SELECT 1 FROM movements WHERE reversal_of=?',(movement_id,)).fetchone():return
    event(db,link['bean_id'],'roast',b['roasted_at'],actor,movement_id,delta_mg=-b['green_mg'],batch_id=batch_id,lot=b['green_lot'],reason='Measured green charge · '+b['code'])

def reconcile(db,actor):
    for b in rows(db,"SELECT b.id,MIN(m.rowid) FROM batches b JOIN stocks s ON s.batch_id=b.id JOIN entries e ON e.stock_id=s.id JOIN movements m ON m.id=e.movement_id WHERE b.history_only=0 AND m.kind='production' AND NOT EXISTS(SELECT 1 FROM green_events g WHERE g.batch_id=b.id) GROUP BY b.id"):
        m=one(db,"SELECT m.id FROM movements m JOIN entries e ON e.movement_id=m.id JOIN stocks s ON s.id=e.stock_id WHERE s.batch_id=? AND m.kind='production' ORDER BY m.rowid LIMIT 1",(b['id'],))
        record_roast(db,b['id'],m['id'],actor)

def save_bean(db,d,actor,request_id):
    from . import blends
    m,repeat=begin_move(db,'green_bean',actor,d,request_id)
    if repeat:return {'duplicate':True}
    id=d.get('id') or uid();name=str(d.get('name','')).strip();currency=d.get('currency','JPY')
    if not name or len(name)>200:raise ValueError('Enter a bean name (up to 200 characters).')
    if currency not in CURRENCIES:raise ValueError('Choose a supported currency.')
    old=db.execute('SELECT * FROM green_beans WHERE id=?',(id,)).fetchone()
    if old:
        if int(d['version'])!=old['version']:raise ValueError('This bean changed. Refresh before editing.')
        if old['currency']!=currency and db.execute('SELECT 1 FROM green_events WHERE bean_id=?',(id,)).fetchone():raise ValueError('Currency cannot change after stock activity. Create a separate bean entry for a different currency.')
    coffee_ids=d.get('coffee_ids',[])
    if not isinstance(coffee_ids,list) or len(coffee_ids)!=len(set(coffee_ids)):raise ValueError('Choose distinct coffee profiles.')
    for c in coffee_ids:
        one(db,'SELECT id FROM coffees WHERE id=?',(c,))
        if blends.profile(db,c):raise ValueError('A blend draws from its saved recipe. Do not link it to one green bean.')
        link=db.execute('SELECT bean_id FROM green_coffee_links WHERE coffee_id=?',(c,)).fetchone()
        if link and link['bean_id']!=id:raise ValueError('A selected profile is already linked to another green bean. Edit that bean first.')
    db.execute('INSERT INTO green_beans(id,name,origin,variety,process,notes,currency) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,origin=excluded.origin,variety=excluded.variety,process=excluded.process,notes=excluded.notes,currency=excluded.currency,version=green_beans.version+1',(id,name,*(str(d.get(k,''))[:2000] for k in ('origin','variety','process','notes')),currency))
    db.execute('DELETE FROM green_coffee_links WHERE bean_id=?',(id,))
    for c in coffee_ids:db.execute('INSERT INTO green_coffee_links VALUES (?,?)',(c,id))
    purchase=d.get('purchase')
    if purchase is not None:
        if not isinstance(purchase,dict):raise ValueError('Check the purchase details.')
        receive(db,{**purchase,'bean_id':id},actor,'green-first-purchase:'+m)
    reconcile(db,actor);audit(db,actor,'green_bean',{'id':id,**d});return {'id':id}

def receive(db,d,actor,request_id):
    m,repeat=begin_move(db,'green_purchase',actor,d,request_id)
    if repeat:return {'duplicate':True,'movement_id':m}
    b=one(db,'SELECT * FROM green_beans WHERE id=?',(d['bean_id'],));q=positive(d['grams']);at=stamp(d['received_at'])
    if dt(at)>dt(now(db)):raise ValueError('Record a purchase when the beans have physically arrived.')
    basis=d.get('price_basis','total')
    if basis not in ('total','per_kg'):raise ValueError('Choose total purchase price or price per kg.')
    if basis=='per_kg' and d.get('price_per_kg') not in (None,''):
        try:price=Decimal(str(d['price_per_kg']))
        except InvalidOperation:raise ValueError('Enter a valid price per kg.')
        if not price.is_finite() or price<0 or price>10**12 or price.as_tuple().exponent < -6:raise ValueError('Use a non-negative price per kg with at most six decimal places.')
        total=int((price*q/1000000*(10**CURRENCIES[b['currency']])).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        if total>10**14:raise ValueError('Purchase price is out of range.')
    else:
        total=money(d.get('total'),b['currency'])
    event(db,b['id'],'purchase',at,actor,m,delta_mg=q,total_minor=total,**{k:str(d.get(k,''))[:2000] for k in ('supplier','reference','lot','reason')})
    audit(db,actor,'green_purchase',{'movement_id':m,**d});return {'movement_id':m}

def count(db,d,actor,request_id):
    m,repeat=begin_move(db,'green_count',actor,d,request_id)
    if repeat:return {'duplicate':True,'movement_id':m}
    b=one(db,'SELECT * FROM green_beans WHERE id=?',(d['bean_id'],))
    if int(d['version'])!=b['version']:raise ValueError('Green stock changed after this count was opened. Refresh and count again.')
    q=weight(d['grams']);reason=str(d.get('reason','')).strip()
    if q<0 or not reason:raise ValueError('Enter a non-negative physical count and a reason.')
    event(db,b['id'],'count',now(db),actor,m,count_mg=q,reason=reason)
    audit(db,actor,'green_count',{'movement_id':m,**d});return {'movement_id':m}

def reverse(db,d,actor,request_id):
    m,repeat=begin_move(db,'green_reversal',actor,d,request_id)
    if repeat:return {'duplicate':True,'movement_id':m}
    e=one(db,'SELECT * FROM green_events WHERE id=?',(d['event_id'],));reason=str(d.get('reason','')).strip()
    if e['kind']!='purchase' or not reason:raise ValueError('Only purchases can be reversed here. Correct counts with a new physical count; reverse roasts from their batch.')
    event(db,e['bean_id'],'reversal',e['effective_at'],actor,m,delta_mg=-e['delta_mg'],reversal_of=e['id'],reason=reason)
    audit(db,actor,'green_purchase_reversed',{'event_id':e['id'],'reason':reason});return {'movement_id':m}

def reverse_production(db,original_id,reversal_id,actor):
    for e in rows(db,"SELECT * FROM green_events WHERE movement_id=? AND kind='roast'",(original_id,)):
        event(db,e['bean_id'],'reversal',e['effective_at'],actor,reversal_id,delta_mg=-e['delta_mg'],reversal_of=e['id'],reason='Production movement reversed')
