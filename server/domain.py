"""All weights are integer milligrams. Decimal parsing never uses binary floats."""
import json, hashlib, math
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .db import uid, rows, one, settings, transaction
JST=ZoneInfo('Asia/Tokyo')

def stamp(value=None):
    if value is None: return datetime.now(timezone.utc).isoformat(timespec='seconds')
    d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('Timestamp must include its timezone.')
    return d.astimezone(timezone.utc).isoformat(timespec='seconds')
def dt(s): return datetime.fromisoformat(stamp(s))
def now(db): return settings(db).get('demo_clock') or stamp()
def weight(v):
    try: d=Decimal(str(v))*1000
    except InvalidOperation: raise ValueError('Enter a weight in grams.')
    if not d.is_finite() or d!=d.to_integral_value() or abs(d)>10**12: raise ValueError('Use grams with at most three decimal places.')
    return int(d)
def positive(v):
    q=weight(v)
    if q<=0: raise ValueError('Quantity must be greater than zero.')
    return q

def audit(db,actor,action,detail): db.execute('INSERT INTO audit(at,actor,action,detail) VALUES (?,?,?,?)',(now(db),actor,action,json.dumps(detail)))
def issue(db,source,external,kind,detail):
    db.execute('INSERT INTO issues VALUES (?,?,?,?,?,?,0) ON CONFLICT(source,external_id,kind) DO UPDATE SET detail=excluded.detail,resolved=0',(uid(),source,external,kind,detail,now(db)))
def policy(coffee): return {k:coffee[k] for k in ('brew_days','dispatch_days','retail_days','fresh_days','policy_version')}
def eligibility(batch,use,at):
    p=json.loads(batch['policy']) if isinstance(batch['policy'],str) else batch['policy']
    days=p.get(use+'_days')
    if batch['held']: return False,None,'Quality hold'
    if batch['archived']: return False,None,'Archived / exception'
    if not batch['roasted_at'] or days is None: return False,None,'Policy or roast timestamp missing'
    ready=dt(batch['roasted_at'])+timedelta(days=days)
    fresh=dt(batch['roasted_at'])+timedelta(days=p['fresh_days'])
    if dt(at)>fresh: return False,stamp(ready),'Outside freshness policy'
    return dt(at)>=ready,stamp(ready),'Ready' if dt(at)>=ready else 'Resting'

def stock(db,id):
    return one(db,"SELECT s.*,b.coffee_id,b.code,b.roasted_at,b.policy,b.held,b.archived,c.name coffee,c.profile,l.name location,COALESCE(p.name,'Bulk') form,COALESCE(p.weight_mg,0) package_mg,COALESCE((SELECT SUM(quantity_mg) FROM reservations r WHERE r.stock_id=s.id),0) reserved_mg FROM stocks s JOIN batches b ON b.id=s.batch_id LEFT JOIN coffees c ON c.id=b.coffee_id JOIN locations l ON l.id=s.location_id LEFT JOIN packages p ON p.id=s.package_id WHERE s.id=?",(id,))
def at_roastery(scope):
    return scope.get('location_id')=='roastery'

def stock_id(db,batch,location,package='bulk'):
    one(db,'SELECT * FROM locations WHERE id=?',(location,))
    if package!='bulk': one(db,'SELECT * FROM packages WHERE id=?',(package,))
    db.execute('INSERT OR IGNORE INTO stocks(id,batch_id,location_id,package_id,quantity_mg,version) VALUES (?,?,?,?,0,0)',(uid(),batch,location,package))
    return one(db,'SELECT id FROM stocks WHERE batch_id=? AND location_id=? AND package_id=?',(batch,location,package))['id']
def delta(db,movement,id,amount,extra=None):
    s=stock(db,id)
    result=s['quantity_mg']+amount
    if result<0 or result<s['reserved_mg']: raise ValueError(f"Insufficient free stock in {s['code']}: {(s['quantity_mg']-s['reserved_mg'])/1000:g} g available. Release or replace allocations first.")
    if s['package_mg'] and result%s['package_mg']: raise ValueError('Packaged stock must contain whole bags.')
    if extra is None:
        extra=(s['overfill_mg']*abs(amount)//s['quantity_mg'])*(1 if amount>=0 else -1) if s['package_mg'] and s['quantity_mg'] else 0
    if s['overfill_mg']+extra<0 or (not s['package_mg'] and extra):raise ValueError('Invalid measured packaging overfill.')
    if result+ s['overfill_mg']+extra>0 and db.execute('SELECT 1 FROM coffee_archives WHERE coffee_id=?',(s['coffee_id'],)).fetchone():
        db.execute('DELETE FROM coffee_archives WHERE coffee_id=?',(s['coffee_id'],))
        audit(db,'Inventory','coffee_restored_for_stock',{'id':s['coffee_id'],'movement_id':movement})
    db.execute('UPDATE stocks SET quantity_mg=?,overfill_mg=overfill_mg+?,version=version+1 WHERE id=?',(result,extra,id))
    db.execute('INSERT INTO entries(movement_id,stock_id,delta_mg,delta_overfill_mg) VALUES (?,?,?,?)',(movement,id,amount,extra))
    return extra
def begin_move(db,kind,actor,payload,request_id,reversal=None):
    if not request_id or len(request_id)>200: raise ValueError('A request identifier is required.')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    old=db.execute('SELECT * FROM movements WHERE request_id=?',(request_id,)).fetchone()
    if old:
        if old['payload_hash']!=digest: raise ValueError('Request identifier was reused with different data.')
        return old['id'],True
    id=uid()
    db.execute('INSERT INTO movements VALUES (?,?,?,?,?,?,?,?)',(id,kind,now(db),actor,payload.get('reason',''),request_id,digest,reversal))
    return id,False

def create_batch(db,d,actor,request_id,external=None,history=False):
    # Called inside a transaction, including import transactions.
    m,repeat=begin_move(db,'history' if history else 'production',actor,d,request_id)
    if repeat: return {'movement_id':m,'duplicate':True}
    c=one(db,'SELECT * FROM coffees WHERE id=?',(d['coffee_id'],))
    green=positive(d['green_g']); output=positive(d['output_g'])
    if output>=green: raise ValueError('Output must be below green input; reconcile exceptional weights before entry.')
    roasted=stamp(d['roasted_at'])
    if dt(roasted)>dt(now(db)): raise ValueError('A future roast belongs in the plan, not physical inventory.')
    id=uid();code=d.get('code') or 'WR-'+dt(roasted).astimezone(JST).strftime('%y%m%d')+'-'+id[:4].upper()
    plan=d.get('plan_id') or None
    if plan:
        p=one(db,'SELECT * FROM plans WHERE id=?',(plan,))
        if p['status']!='planned' or p['coffee_id']!=c['id']: raise ValueError('Plan must be open and match this coffee.')
    db.execute('INSERT INTO batches(id,code,coffee_id,external_id,roasted_at,green_mg,output_mg,policy,notes,green_lot,history_only,plan_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(id,code,c['id'],external,roasted,green,output,json.dumps(policy(c)),d.get('notes',''),d.get('green_lot',''),int(history),plan))
    from . import blends
    if d.get('recipe_id') and not str(d.get('notes') or '').strip():raise ValueError('Add a note explaining the recipe override.')
    blends.attach(db,id,d.get('recipe_id'))
    if not history:
        delta(db,m,stock_id(db,id,d.get('location_id','roastery')),output)
        from .green import record_roast
        record_roast(db,id,m,actor)
    if plan: db.execute("UPDATE plans SET status='completed' WHERE id=?",(plan,))
    return {'batch_id':id,'movement_id':m}

def add_roasted_stock(db,d,actor,request_id):
    """Physical coffee found outside production; never create a green charge.

    A new stock-only batch uses the existing historical/opening-stock marker and
    zero production weights. It is excluded from green reconciliation, measured
    yields and plan completion, while retaining normal batch-level stock rules.
    """
    m,repeat=begin_move(db,'stock_addition',actor,d,request_id)
    if repeat:
        scope=one(db,'SELECT s.id,s.batch_id FROM entries e JOIN stocks s ON s.id=e.stock_id WHERE e.movement_id=?',(m,))
        return {'movement_id':m,'batch_id':scope['batch_id'],'stock_id':scope['id'],'duplicate':True}
    reason=str(d.get('reason','')).strip()
    if not reason:raise ValueError('Explain why this roasted stock is being added.')
    package=d.get('package_id') or 'bulk'
    extra=weight(d.get('overfill_g') or 0)
    if extra<0:raise ValueError('Measured overfill cannot be negative.')
    if package=='bulk':
        q=positive(d['grams'])
        if extra:raise ValueError('Overfill applies only to packaged bags.')
    else:
        p=one(db,'SELECT * FROM packages WHERE id=?',(package,))
        units=int(d.get('units',0))
        if units<=0 or str(units)!=str(d.get('units')):raise ValueError('Enter a positive whole number of bags.')
        q=positive(Decimal(units*p['weight_mg'])/1000)
    if d.get('batch_id'):
        b=one(db,'SELECT * FROM batches WHERE id=?',(d['batch_id'],))
        if b['archived']:raise ValueError('Restore this batch from archive before adding stock.')
        batch=b['id']
    else:
        c=one(db,'SELECT * FROM coffees WHERE id=?',(d['coffee_id'],))
        roasted=stamp(d['roasted_at']) if d.get('roasted_at') else None
        if roasted and dt(roasted)>dt(now(db)):raise ValueError('The roast date cannot be in the future.')
        batch=uid();code=str(d.get('code') or '').strip() or 'STOCK-'+dt(now(db)).astimezone(JST).strftime('%y%m%d')+'-'+batch[:4].upper()
        db.execute('INSERT INTO batches(id,code,coffee_id,roasted_at,policy,notes,history_only) VALUES (?,?,?,?,?,?,1)',(batch,code,c['id'],roasted,json.dumps(policy(c)),reason))
    scope=stock_id(db,batch,d.get('location_id') or 'roastery',package)
    delta(db,m,scope,q,extra)
    audit(db,actor,'stock_addition',{'movement_id':m,'batch_id':batch,'stock_id':scope,'quantity_mg':q,'overfill_mg':extra,'reason':reason})
    return {'movement_id':m,'batch_id':batch,'stock_id':scope}

def movement(db,d,actor,request_id):
    kind=d['kind']; m,repeat=begin_move(db,kind,actor,d,request_id,d.get('reversal_of'))
    if repeat: return {'movement_id':m,'duplicate':True}
    if kind=='reverse':
        if not d.get('reason'): raise ValueError('A correction reason is required.')
        original=one(db,'SELECT * FROM movements WHERE id=?',(d['reversal_of'],))
        if original['kind'] in ('reserve','release','reverse','history','shipment','square_sale'): raise ValueError('Use an explicit audited adjustment for this operation.')
        es=rows(db,'SELECT stock_id,delta_mg,delta_overfill_mg FROM entries WHERE movement_id=?',(original['id'],))
        for e in es: delta(db,m,e['stock_id'],-e['delta_mg'],-e['delta_overfill_mg'])
        from .green import reverse_production
        reverse_production(db,original['id'],m,actor)
        return {'movement_id':m}
    s=stock(db,d['stock_id']);q=positive(d.get('grams',1))
    if kind in ('consume','sale','reserve','shipment'):
        use=d.get('use') or ('brew' if kind=='consume' else 'retail' if kind=='sale' else 'dispatch')
        at=d.get('due_at',now(db)) if kind=='reserve' else now(db)
        if kind=='consume': use='brew'
        elif kind=='sale': use='retail'
        eligible,ready,why=eligibility(s,use,at)
        if not eligible: raise ValueError(f'{why}. '+(f'Ready at {ready}.' if ready else 'Review the batch or policy.'))
    if kind=='transfer':
        dest=stock_id(db,s['batch_id'],d['location_id'],s['package_id'])
        if dest==s['id']: raise ValueError('Choose a different destination.')
        carried=-delta(db,m,s['id'],-q);delta(db,m,dest,q,carried)
    elif kind=='pack':
        if s['package_id']!='bulk': raise ValueError('Pack from bulk stock.')
        p=one(db,'SELECT * FROM packages WHERE id=?',(d['package_id'],))
        units=int(d['units'])
        if units<=0 or str(units)!=str(d['units']): raise ValueError('Enter a whole number of bags.')
        loss=weight(d.get('loss_g',0)); overfill=weight(d.get('overfill_g',0))
        if min(loss,overfill)<0: raise ValueError('Loss and overfill cannot be negative.')
        if (loss or overfill) and not d.get('reason'): raise ValueError('Explain packaging loss or overfill.')
        delta(db,m,s['id'],-(units*p['weight_mg']+loss+overfill))
        delta(db,m,stock_id(db,s['batch_id'],d.get('location_id',s['location_id']),p['id']),units*p['weight_mg'],overfill)
        # Measured overfill travels with package stock and is apportioned exactly on movements.
        audit(db,actor,'pack_variance',{'movement_id':m,'loss_mg':loss,'overfill_mg':overfill})
    elif kind in ('consume','sale','waste'):
        if kind=='consume' and s['package_id']!='bulk': raise ValueError('Open bags into bulk before recording consumption.')
        if kind=='sale' and s['package_id']=='bulk': raise ValueError('Retail sale requires packaged stock.')
        delta(db,m,s['id'],-q)
    elif kind=='unpack':
        if s['package_id']=='bulk': raise ValueError('Select packaged stock to open.')
        carried=-delta(db,m,s['id'],-q);delta(db,m,stock_id(db,s['batch_id'],d.get('location_id',s['location_id'])),q+carried)
    elif kind in ('count','opening','return'):
        if not d.get('reason'): raise ValueError('A count or return reason is required.')
        if int(d['version'])!=s['version']: raise ValueError('Stock changed after you opened this count. Refresh and count again.')
        target=weight(d['count_g'])
        if target<0: raise ValueError('Count cannot be negative.')
        if kind=='opening' and not one(db,'SELECT history_only FROM batches WHERE id=?',(s['batch_id'],))['history_only']: raise ValueError('Opening stock is for historical batches only.')
        if kind=='return':
            if not s['held']: raise ValueError('Record returns into a quality-held batch after physical receipt.')
            returned_extra=weight(d.get('return_overfill_g',0))
            if returned_extra<0:raise ValueError('Returned overfill cannot be negative.')
            delta(db,m,s['id'],q,returned_extra)
        else: delta(db,m,s['id'],target-s['quantity_mg'])
    elif kind=='reserve':
        due=stamp(d['due_at']); line=d.get('line_id') or None; demand=d.get('demand_id') or None
        if bool(line)==bool(demand): raise ValueError('Choose exactly one order line or café/retail requirement.')
        if line:
            if not at_roastery(s):raise ValueError('Customer orders can only reserve stock at the roastery.')
            l=one(db,'SELECT l.*,v.coffee_id,v.package_id,v.kind,o.payment,o.cancelled,o.due_at FROM lines l JOIN orders o ON o.id=l.order_id LEFT JOIN variants v ON v.id=l.variant_id WHERE l.id=?',(line,))
            if l['kind']!='coffee' or l['coffee_id']!=s['coffee_id'] or not order_eligible(db,l['order_id']): raise ValueError('Order is unmapped, ineligible, or for another coffee.')
            if d.get('use','dispatch')!='dispatch' or not l['due_at'] or stamp(l['due_at'])!=due: raise ValueError('Order allocations must use its exact local dispatch deadline and dispatch policy.')
            size=one(db,'SELECT weight_mg FROM packages WHERE id=?',(l['package_id'],))['weight_mg']
            if s['package_id'] not in ('bulk',l['package_id']): raise ValueError('Package does not match the order variant.')
            existing=db.execute('SELECT COALESCE(SUM(quantity_mg),0) FROM reservations WHERE line_id=?',(line,)).fetchone()[0]
            if existing+q>l['unfulfilled']*size: raise ValueError('Allocation exceeds remaining order demand.')
        else:
            req=one(db,'SELECT * FROM demands WHERE id=?',(demand,))
            if req['coffee_id']!=s['coffee_id'] or req['channel']!=d.get('use') or stamp(req['due_at'])!=due: raise ValueError('Requirement must match coffee and intended use.')
            existing=db.execute('SELECT COALESCE(SUM(quantity_mg),0) FROM reservations WHERE demand_id=?',(demand,)).fetchone()[0]
            if existing+q>req['quantity_mg']: raise ValueError('Allocation exceeds requirement.')
        if q>s['quantity_mg']-s['reserved_mg']: raise ValueError('Not enough unreserved stock.')
        if s['package_mg'] and q%s['package_mg']: raise ValueError('Reserve whole bags.')
        db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?)',(uid(),s['id'],line,demand,q,d.get('use','dispatch'),due,now(db)))
    elif kind=='release':
        r=one(db,'SELECT * FROM reservations WHERE id=?',(d['reservation_id'],))
        if r['stock_id']!=s['id']: raise ValueError('Allocation does not belong to selected stock.')
        db.execute('DELETE FROM reservations WHERE id=?',(r['id'],));audit(db,actor,'release',r)
    elif kind=='pack_reserved':
        r=one(db,'SELECT * FROM reservations WHERE id=?',(d['reservation_id'],))
        if r['stock_id']!=s['id'] or not r['line_id'] or s['package_id']!='bulk': raise ValueError('Select a bulk order allocation.')
        v=one(db,'SELECT v.* FROM variants v JOIN lines l ON l.variant_id=v.id WHERE l.id=?',(r['line_id'],))
        p=one(db,'SELECT * FROM packages WHERE id=?',(v['package_id'],));q=r['quantity_mg']
        if q%p['weight_mg']: raise ValueError('Allocation must cover whole bags; replace this allocation first.')
        db.execute('DELETE FROM reservations WHERE id=?',(r['id'],));delta(db,m,s['id'],-q)
        dest=stock_id(db,s['batch_id'],d.get('location_id','roastery'),p['id']);delta(db,m,dest,q)
        db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?)',(r['id'],dest,r['line_id'],None,q,r['use'],r['due_at'],r['created_at']))
    elif kind=='shipment':
        event=one(db,'SELECT * FROM fulfillment_events WHERE id=?',(d['fulfillment_id'],))
        if event['recorded']: raise ValueError('This fulfillment already has a physical pick.')
        # Entire fulfillment must be picked atomically through the separate fulfillment-pick endpoint.
        raise ValueError('Use Confirm fulfillment pick from Orders to reconcile all lines together.')
    else: raise ValueError('Unknown stock action.')
    audit(db,actor,kind,{'movement_id':m,**d})
    return {'movement_id':m}

def link_completed_plan(db,d,actor,request_id):
    m,repeat=begin_move(db,'plan_link',actor,d,request_id)
    if repeat:return {'duplicate':True}
    b=one(db,'SELECT * FROM batches WHERE id=?',(d['batch_id'],));p=one(db,'SELECT * FROM plans WHERE id=?',(d['plan_id'],))
    if b['plan_id'] or b['history_only'] or p['status']!='planned' or b['coffee_id']!=p['coffee_id']:raise ValueError('Choose an unlinked production batch and an open plan for the same coffee.')
    if not d.get('reason'):raise ValueError('Explain how the completed batch matches this plan.')
    db.execute('UPDATE batches SET plan_id=? WHERE id=?',(p['id'],b['id']));db.execute("UPDATE plans SET status='completed' WHERE id=?",(p['id'],));audit(db,actor,'link_completed_plan',d)
    return {'movement_id':m}


def order_eligible(db,order_id):
    o=one(db,'SELECT * FROM orders WHERE id=?',(order_id,))
    if o['cancelled']:return False
    if o['source']=='wholesale':
        return one(db,'SELECT status FROM wholesale_orders WHERE order_id=?',(order_id,))['status']=='CONFIRMED'
    return o['payment'] in settings(db)['eligible_payments']
