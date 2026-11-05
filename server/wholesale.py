"""Local wholesale commitments. Never writes orders or fulfillment to Shopify."""
import hashlib,json,re
from .db import uid,one,rows,settings
from .domain import now,stamp,weight,positive,begin_move,audit,stock,order_eligible
from .imports import release_excess,fulfillment_pick

def text(value,limit=200):
    result=str(value or '').strip()
    if len(result)>limit:raise ValueError('A field is too long. Shorten it and retry.')
    return result

def save_order(db,d,actor,request_id):
    m,repeat=begin_move(db,'wholesale_order',actor,d,request_id)
    id=d.get('id') or 'wholesale:'+hashlib.sha256(request_id.encode()).hexdigest()
    if repeat:return {'order_id':id,'duplicate':True}
    old=db.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
    if d.get('id') and (not old or old['source']!='wholesale'):raise ValueError('Only local wholesale orders can be changed here.')
    meta=None
    if old:
        meta=one(db,'SELECT * FROM wholesale_orders WHERE order_id=?',(id,))
        if int(d.get('version',-1))!=meta['version']:raise ValueError('This order changed. Refresh before editing it again.')
    customer={k:text(d.get('customer',{}).get(k),2000 if k=='address' else 200) for k in ('business','contact','email','phone','address')}
    if not customer['business']:raise ValueError('Enter the customer or business name.')
    if customer['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',customer['email']):raise ValueError('Check the customer email address.')
    status=d.get('status','CONFIRMED');payment=d.get('payment','PENDING')
    if status not in ('DRAFT','CONFIRMED','CANCELLED') or payment not in ('PENDING','PAID','PARTIALLY_PAID','REFUNDED'):raise ValueError('Choose valid order and payment statuses.')
    due=stamp(d['due_at']) if d.get('due_at') else None
    if status=='CONFIRMED' and not due:raise ValueError('Confirmed orders need a dispatch or pickup deadline.')
    method=d.get('method','delivery')
    if method not in ('delivery','pickup'):raise ValueError('Choose delivery or pickup.')
    incoming=d.get('lines')
    if not isinstance(incoming,list) or not incoming or len(incoming)>100:raise ValueError('Add between 1 and 100 coffee lines.')
    existing={l['id']:l for l in rows(db,'SELECT * FROM lines WHERE order_id=?',(id,))};seen=set();prepared=[]
    for item in incoming:
        coffee=one(db,'SELECT * FROM coffees WHERE id=?',(item['coffee_id'],))
        if item.get('package_id'):
            package=one(db,'SELECT * FROM packages WHERE id=?',(item['package_id'],))
        else:
            size=positive(item['unit_g'])
            match=db.execute('SELECT * FROM packages WHERE weight_mg=? ORDER BY id LIMIT 1',(size,)).fetchone()
            if match:package=dict(match)
            else:
                pid='wholesale-size:'+str(size);db.execute('INSERT INTO packages VALUES (?,?,?)',(pid,'Wholesale · '+str(size/1000)+' g',size));package=one(db,'SELECT * FROM packages WHERE id=?',(pid,))
        try:
            units=int(item['quantity'])
            if str(units)!=str(item['quantity']) or not 1<=units<=10000:raise ValueError()
        except (TypeError,ValueError):raise ValueError('Enter a positive whole number of bags (up to 10,000).') from None
        grind=text(item.get('grind','Whole bean'),100)
        variant='wholesale:'+hashlib.sha256(json.dumps([coffee['id'],package['id'],grind]).encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO variants VALUES (?,?,?,?,?,?)',(variant,'',coffee['id'],package['id'],'coffee',grind))
        lid=item.get('id') or uid()
        if lid in seen or (item.get('id') and lid not in existing):raise ValueError('A line is duplicated or belongs to another order.')
        seen.add(lid);previous=existing.get(lid);shipped=(previous['quantity']-previous['unfulfilled']) if previous else 0
        if units<shipped:raise ValueError('Quantity cannot be below the amount already dispatched.')
        if previous and previous['variant_id']!=variant and shipped:raise ValueError('Dispatched lines must keep their original coffee and package. Add another line instead.')
        if previous and (previous['variant_id']!=variant or units!=previous['quantity']):
            if db.execute('SELECT 1 FROM reservations WHERE line_id=?',(lid,)).fetchone():raise ValueError('Release this line’s allocations before changing its coffee, bag size or quantity.')
        title=coffee['name']+' · '+str(package['weight_mg']/1000)+' g · '+grind
        prepared.append((lid,id,variant,title,units,units-shipped))
    for lid,previous in existing.items():
        if lid not in seen and (previous['unfulfilled']!=previous['quantity'] or db.execute('SELECT 1 FROM reservations WHERE line_id=?',(lid,)).fetchone()):raise ValueError('Release allocations before removing a line; dispatched lines must remain in the order.')
    cancelled=int(status=='CANCELLED');number=old['number'] if old else 'WS-'+now(db)[:10].replace('-','')+'-'+m[:5].upper()
    remaining=sum(x[5] for x in prepared);shipped=sum(x[4]-x[5] for x in prepared)
    fulfillment='FULFILLED' if not remaining else 'PARTIALLY_FULFILLED' if shipped else 'UNFULFILLED'
    db.execute('INSERT INTO orders(id,number,payment,cancelled,fulfillment,updated_at,due_at,notes,delivery,source,created_at,closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payment=excluded.payment,cancelled=excluded.cancelled,fulfillment=excluded.fulfillment,updated_at=excluded.updated_at,due_at=excluded.due_at,notes=excluded.notes,delivery=excluded.delivery,closed_at=excluded.closed_at',(id,number,payment,cancelled,fulfillment,now(db),due,text(d.get('notes'),4000),method.title(),'wholesale',now(db),now(db) if not remaining else None))
    db.execute('INSERT INTO wholesale_orders VALUES (?,?,?,?,?,1) ON CONFLICT(order_id) DO UPDATE SET customer_json=excluded.customer_json,status=excluded.status,terms=excluded.terms,reference=excluded.reference,version=wholesale_orders.version+1',(id,json.dumps(customer),status,text(d.get('terms'),300),text(d.get('reference'),200)))
    for row in prepared:
        db.execute('INSERT INTO lines VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET variant_id=excluded.variant_id,title=excluded.title,quantity=excluded.quantity,unfulfilled=excluded.unfulfilled',row)
        release_excess(db,row[0],row[5]*one(db,'SELECT p.weight_mg FROM variants v JOIN packages p ON p.id=v.package_id WHERE v.id=?',(row[2],))['weight_mg'] if status=='CONFIRMED' else 0,actor)
        db.execute('UPDATE reservations SET due_at=? WHERE line_id=?',(due,row[0]))
    for lid in existing:
        if lid not in seen:db.execute('DELETE FROM lines WHERE id=?',(lid,))
    audit(db,actor,'wholesale_saved',{'order_id':id,'status':status,'line_count':len(prepared),'version':(meta['version']+1 if meta else 1)})
    return {'order_id':id,'number':number}

def dispatch_order(db,d,actor,request_id):
    o=one(db,'SELECT * FROM orders WHERE id=?',(d['order_id'],))
    if o['source']!='wholesale':raise ValueError('This action is only for local wholesale orders.')
    fid='wholesale-dispatch:'+hashlib.sha256((o['id']+request_id).encode()).hexdigest()
    payload={'fulfillment_id':fid,'picks':d.get('picks',[]),'reason':'Confirmed wholesale physical dispatch'}
    if db.execute('SELECT 1 FROM movements WHERE request_id=?',(request_id,)).fetchone():return fulfillment_pick(db,payload,actor,request_id)
    meta=one(db,'SELECT * FROM wholesale_orders WHERE order_id=?',(o['id'],))
    if int(d.get('version',-1))!=meta['version']:raise ValueError('The order changed. Refresh before recording dispatch.')
    if not order_eligible(db,o['id']):raise ValueError('Confirm the wholesale order before dispatching it.')
    if not payload['picks']:raise ValueError('Choose at least one physical pick.')
    quantities={}
    for pick in payload['picks']:
        line=one(db,'SELECT l.*,p.weight_mg FROM lines l JOIN variants v ON v.id=l.variant_id JOIN packages p ON p.id=v.package_id WHERE l.id=? AND l.order_id=?',(pick['line_id'],o['id']))
        q=positive(pick['grams'])
        if q%line['weight_mg']:raise ValueError('Dispatch whole bags matching the order’s bag size.')
        quantities[line['id']]=quantities.get(line['id'],0)+q//line['weight_mg']
        if quantities[line['id']]>line['unfulfilled']:raise ValueError('Pick exceeds this line’s remaining quantity.')
        # Free only this order line’s allocation at the picked stock; other commitments stay protected.
        left=q
        for reserve in rows(db,'SELECT * FROM reservations WHERE line_id=? AND stock_id=? ORDER BY created_at,rowid',(line['id'],pick['stock_id'])):
            amount=min(left,reserve['quantity_mg']);left-=amount
            if amount==reserve['quantity_mg']:db.execute('DELETE FROM reservations WHERE id=?',(reserve['id'],))
            else:db.execute('UPDATE reservations SET quantity_mg=quantity_mg-? WHERE id=?',(amount,reserve['id']))
    event={'lines':[{'line_id':lid,'quantity':units} for lid,units in quantities.items()]}
    db.execute('INSERT INTO fulfillment_events VALUES (?,?,?,?,0)',(fid,o['id'],now(db),json.dumps(event)))
    result=fulfillment_pick(db,payload,actor,request_id)
    for lid,units in quantities.items():
        db.execute('UPDATE lines SET unfulfilled=unfulfilled-? WHERE id=?',(units,lid))
        line=one(db,'SELECT l.*,p.weight_mg FROM lines l JOIN variants v ON v.id=l.variant_id JOIN packages p ON p.id=v.package_id WHERE l.id=?',(lid,));release_excess(db,lid,line['unfulfilled']*line['weight_mg'],actor)
    remaining=one(db,'SELECT SUM(unfulfilled) remaining FROM lines WHERE order_id=?',(o['id'],))['remaining']
    db.execute('UPDATE orders SET fulfillment=?,updated_at=?,closed_at=? WHERE id=?',('PARTIALLY_FULFILLED' if remaining else 'FULFILLED',now(db),None if remaining else now(db),o['id']))
    db.execute('UPDATE wholesale_orders SET version=version+1 WHERE order_id=?',(o['id'],));audit(db,actor,'wholesale_dispatched',{'order_id':o['id'],'fulfillment_id':fid,'line_quantities':quantities})
    return result
