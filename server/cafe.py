"""Internal cafe replenishment: dated requests and conservative stock transfers."""
import hashlib,json
from decimal import Decimal,InvalidOperation
from .db import one,rows,uid
from .domain import now,stamp,positive,begin_move,audit,stock,stock_id,delta,eligibility,at_roastery
from .order_rules import order_lines,order_line
from .imports import release_excess


def _note(value,limit=4000):
    value=str(value or '').strip()
    if len(value)>limit:raise ValueError('Shorten the request note and try again.')
    return value


def save_order(db,d,actor,request_id):
    m,repeat=begin_move(db,'cafe_request',actor,d,request_id)
    id=d.get('id') or 'cafe:'+hashlib.sha256(request_id.encode()).hexdigest()
    if repeat:return {'order_id':id,'duplicate':True}
    old=db.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
    if d.get('id') and (not old or old['source']!='cafe'):raise ValueError('Choose a cafe request to edit.')
    if old:
        meta=one(db,'SELECT * FROM cafe_orders WHERE order_id=?',(id,))
        if int(d.get('version',-1))!=meta['version']:raise ValueError('This request changed. Refresh before editing.')
        if old['cancelled'] or old['closed_at']:raise ValueError('Completed or cancelled requests cannot be edited.')
    if not d.get('due_at'):raise ValueError('Choose when the coffee is needed at the cafe.')
    due=stamp(d['due_at']);incoming=d.get('lines')
    if not isinstance(incoming,list) or not 1<=len(incoming)<=50:raise ValueError('Add between 1 and 50 coffees.')
    existing={l['id']:l for l in order_lines(db,id)};seen=set();prepared=[]
    for item in incoming:
        coffee=one(db,'SELECT * FROM coffees WHERE id=?',(item['coffee_id'],))
        previous=existing.get(item.get('id'));form=item.get('form')
        if db.execute('SELECT 1 FROM coffee_archives WHERE coffee_id=?',(coffee['id'],)).fetchone() and (not previous or previous['coffee_id']!=coffee['id']):raise ValueError('Restore the deleted coffee before requesting it.')
        if form not in ('bulk','bags'):raise ValueError('Choose bulk coffee or retail bags.')
        if form=='bulk':
            try:requested=positive(Decimal(str(item['kg']))*1000)
            except (InvalidOperation,KeyError):raise ValueError('Enter the bulk weight in kilograms.') from None
            pid=None;units=1;size=1
        else:
            p=one(db,'SELECT * FROM packages WHERE id=?',(item['package_id'],));pid=p['id'];size=p['weight_mg']
            try:
                units=int(item['quantity'])
                if str(units)!=str(item['quantity']) or not 1<=units<=10000:raise ValueError()
            except (ValueError,TypeError,KeyError):raise ValueError('Enter a whole number of bags between 1 and 10,000.') from None
            requested=units*size
        use='brew' if form=='bulk' else 'retail'
        if coffee[use+'_days'] is None:raise ValueError('Set the '+use+' rest policy for '+coffee['name']+' in Settings first.')
        variant='cafe:'+hashlib.sha256(json.dumps([coffee['id'],form,pid]).encode()).hexdigest()
        db.execute("INSERT OR IGNORE INTO variants VALUES (?,?,?,?,?,'Whole bean')",(variant,'',coffee['id'],pid,'coffee'))
        lid=item.get('id') or uid()
        if lid in seen or (item.get('id') and not previous):raise ValueError('A request line is duplicated or belongs to another order.')
        seen.add(lid);delivered=previous['delivered_mg'] if previous else 0
        if requested<delivered:raise ValueError('Requested weight cannot be below the amount already delivered.')
        if previous and (variant!=previous['variant_id'] or requested!=previous['requested_mg']):
            if delivered and variant!=previous['variant_id']:raise ValueError('Keep delivered coffees and bag sizes unchanged; add a new line instead.')
            if db.execute('SELECT 1 FROM reservations WHERE line_id=?',(lid,)).fetchone():raise ValueError('Release this line’s allocations before changing coffee, form or quantity.')
        title=coffee['name']+' · '+('Bulk for café' if form=='bulk' else f'{size/1000:g} g retail bags')
        prepared.append((lid,variant,title,form,requested,delivered,units,1 if form=='bulk' and requested>delivered else 0 if form=='bulk' else (requested-delivered)//size))
    for lid,previous in existing.items():
        if lid not in seen and (previous['delivered_mg'] or db.execute('SELECT 1 FROM reservations WHERE line_id=?',(lid,)).fetchone()):raise ValueError('Delivered or allocated lines must remain on the request.')
    remaining=sum(r[4]-r[5] for r in prepared);delivered=sum(r[5] for r in prepared)
    number=old['number'] if old else 'CF-'+now(db)[:10].replace('-','')+'-'+m[:5].upper()
    fulfillment='FULFILLED' if not remaining else 'PARTIALLY_FULFILLED' if delivered else 'UNFULFILLED'
    db.execute('''INSERT INTO orders(id,number,payment,cancelled,fulfillment,updated_at,due_at,notes,delivery,source,created_at,closed_at)
        VALUES (?,?,?,0,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET fulfillment=excluded.fulfillment,updated_at=excluded.updated_at,due_at=excluded.due_at,notes=excluded.notes,closed_at=excluded.closed_at''',
        (id,number,'INTERNAL',fulfillment,now(db),due,_note(d.get('notes')),'Café replenishment','cafe',now(db),None if remaining else now(db)))
    db.execute('INSERT INTO cafe_orders VALUES (?,?,1) ON CONFLICT(order_id) DO UPDATE SET version=version+1',(id,actor))
    for lid,variant,title,form,requested,delivered,units,unfulfilled in prepared:
        db.execute('INSERT INTO lines VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET variant_id=excluded.variant_id,title=excluded.title,quantity=excluded.quantity,unfulfilled=excluded.unfulfilled',(lid,id,variant,title,units,unfulfilled))
        db.execute('INSERT INTO cafe_order_lines VALUES (?,?,?,?) ON CONFLICT(line_id) DO UPDATE SET form=excluded.form,requested_mg=excluded.requested_mg',(lid,form,requested,delivered))
        release_excess(db,lid,requested-delivered,actor)
        db.execute('UPDATE reservations SET due_at=? WHERE line_id=?',(due,lid))
    for lid in existing:
        if lid not in seen:
            db.execute('DELETE FROM cafe_order_lines WHERE line_id=?',(lid,));db.execute('DELETE FROM lines WHERE id=?',(lid,))
    audit(db,actor,'cafe_request_saved',{'order_id':id,'movement_id':m,'due_at':due})
    return {'order_id':id,'number':number}


def cancel_order(db,d,actor,request_id):
    m,repeat=begin_move(db,'cafe_cancel',actor,d,request_id)
    if repeat:return {'duplicate':True}
    o=one(db,"SELECT o.*,c.version FROM orders o JOIN cafe_orders c ON c.order_id=o.id WHERE o.id=?",(d['order_id'],))
    if int(d.get('version',-1))!=o['version']:raise ValueError('This request changed. Refresh before cancelling.')
    if o['closed_at'] or o['cancelled']:raise ValueError('This request is already complete or cancelled.')
    reason=_note(d.get('reason'))
    if not reason:raise ValueError('Add a cancellation reason.')
    for l in order_lines(db,o['id']):release_excess(db,l['id'],0,actor)
    db.execute('UPDATE orders SET cancelled=1,updated_at=? WHERE id=?',(now(db),o['id']))
    db.execute('UPDATE cafe_orders SET version=version+1 WHERE order_id=?',(o['id'],))
    audit(db,actor,'cafe_request_cancelled',{'order_id':o['id'],'reason':reason,'movement_id':m})


def deliver(db,d,actor,request_id):
    m,repeat=begin_move(db,'cafe_delivery',actor,d,request_id)
    if repeat:return {'movement_id':m,'duplicate':True}
    o=one(db,'SELECT o.*,c.version FROM orders o JOIN cafe_orders c ON c.order_id=o.id WHERE o.id=?',(d['order_id'],))
    if int(d.get('version',-1))!=o['version']:raise ValueError('This request changed. Refresh before recording delivery.')
    if o['cancelled'] or o['closed_at']:raise ValueError('Choose an open cafe request.')
    picks=d.get('picks')
    if not isinstance(picks,list) or not 1<=len(picks)<=200:raise ValueError('Select the stock actually delivered.')
    for p in picks:
        l=order_line(db,p['line_id']);s=stock(db,p['stock_id']);q=positive(p['grams'])
        if l['order_id']!=o['id'] or not at_roastery(s) or s['coffee_id']!=l['coffee_id'] or s['package_id']!=l['package_id']:raise ValueError('Choose matching roastery stock in the requested form.')
        if q>l['required_mg'] or q%l['weight_mg']:raise ValueError('Delivery must fit the remaining request and contain whole bags.')
        eligible,ready,why=eligibility(s,l['use'],now(db))
        if not eligible:raise ValueError(why+(f'. Ready at {ready}.' if ready else '. Review the batch.'))
        left=q
        for r in rows(db,'SELECT * FROM reservations WHERE line_id=? AND stock_id=? ORDER BY created_at,rowid',(l['id'],s['id'])):
            take=min(left,r['quantity_mg']);left-=take
            if take==r['quantity_mg']:db.execute('DELETE FROM reservations WHERE id=?',(r['id'],))
            else:db.execute('UPDATE reservations SET quantity_mg=quantity_mg-? WHERE id=?',(take,r['id']))
        extra=-delta(db,m,s['id'],-q);dest=stock_id(db,s['batch_id'],'cafe' if l['request_form']=='bulk' else 'wall',s['package_id']);delta(db,m,dest,q,extra)
        db.execute('INSERT INTO cafe_deliveries(order_id,line_id,movement_id,source_stock_id,destination_stock_id,quantity_mg,overfill_mg) VALUES (?,?,?,?,?,?,?)',(o['id'],l['id'],m,s['id'],dest,q,extra))
        db.execute('UPDATE cafe_order_lines SET delivered_mg=delivered_mg+? WHERE line_id=?',(q,l['id']))
        remaining=l['required_mg']-q
        db.execute('UPDATE lines SET unfulfilled=? WHERE id=?',(int(bool(remaining)) if l['request_form']=='bulk' else remaining//l['weight_mg'],l['id']))
        release_excess(db,l['id'],remaining,actor)
    ls=order_lines(db,o['id']);remaining=sum(l['required_mg'] for l in ls)
    db.execute('UPDATE orders SET fulfillment=?,updated_at=?,closed_at=? WHERE id=?',('PARTIALLY_FULFILLED' if remaining else 'FULFILLED',now(db),None if remaining else now(db),o['id']))
    db.execute('UPDATE cafe_orders SET version=version+1 WHERE order_id=?',(o['id'],))
    audit(db,actor,'cafe_delivered',{'order_id':o['id'],'movement_id':m,'picks':picks})
    return {'movement_id':m}
