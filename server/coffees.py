"""Remove exhausted coffee profiles from active views, retaining their history."""
from .db import one,rows
from .domain import begin_move,now,audit


def snapshot(db):
    return rows(db,'SELECT c.*,EXISTS(SELECT 1 FROM coffee_archives a WHERE a.coffee_id=c.id) archived FROM coffees c ORDER BY c.name,c.profile,c.id')


def set_archived(db,d,actor,request_id):
    move,repeat=begin_move(db,'coffee_visibility',actor,d,request_id)
    if repeat:return {'duplicate':True}
    c=one(db,'SELECT * FROM coffees WHERE id=?',(d['id'],))
    if type(d.get('archived')) is not bool:raise ValueError('Choose delete or restore.')
    old=bool(db.execute('SELECT 1 FROM coffee_archives WHERE coffee_id=?',(c['id'],)).fetchone())
    if old==d['archived']:return {'id':c['id'],'archived':old}
    if d['archived']:
        if db.execute('SELECT 1 FROM stocks s JOIN batches b ON b.id=s.batch_id WHERE b.coffee_id=? AND s.quantity_mg+s.overfill_mg>0',(c['id'],)).fetchone():raise ValueError('This coffee still has roasted stock. Finish or reconcile its remaining stock before deleting it.')
        if db.execute('SELECT 1 FROM reservations r JOIN stocks s ON s.id=r.stock_id JOIN batches b ON b.id=s.batch_id WHERE b.coffee_id=?',(c['id'],)).fetchone():raise ValueError('Release this coffee’s allocations before deleting it.')
        if db.execute("SELECT 1 FROM lines l JOIN variants v ON v.id=l.variant_id JOIN orders o ON o.id=l.order_id LEFT JOIN wholesale_orders w ON w.order_id=o.id WHERE v.coffee_id=? AND l.unfulfilled>0 AND o.cancelled=0 AND o.closed_at IS NULL AND (o.source!='wholesale' OR w.status='CONFIRMED')",(c['id'],)).fetchone():raise ValueError('This coffee has unfulfilled orders. Complete or cancel those commitments before deleting it.')
        if db.execute("SELECT 1 FROM plans WHERE coffee_id=? AND status='planned'",(c['id'],)).fetchone():raise ValueError('Complete or cancel this coffee’s planned roasts before deleting it.')
        if db.execute('SELECT 1 FROM demands WHERE coffee_id=? AND quantity_mg>0 AND due_at>=?',(c['id'],now(db))).fetchone():raise ValueError('Remove this coffee’s upcoming café forecasts or retail targets before deleting it.')
        link=db.execute('SELECT bean_id FROM green_coffee_links WHERE coffee_id=?',(c['id'],)).fetchone()
        if link and not db.execute('SELECT 1 FROM green_coffee_links l WHERE l.bean_id=? AND l.coffee_id!=? AND NOT EXISTS(SELECT 1 FROM coffee_archives a WHERE a.coffee_id=l.coffee_id)',(link['bean_id'],c['id'])).fetchone():
            from .green import snapshot as green_snapshot
            bean=next(b for b in green_snapshot(db)['beans'] if b['id']==link['bean_id'])
            if bean['quantity_mg']!=0:raise ValueError('The linked green bean still has stock or needs a count correction. Reconcile it before deleting the last active coffee profile.')
        db.execute('INSERT INTO coffee_archives VALUES (?,?,?)',(c['id'],now(db),actor))
    else:db.execute('DELETE FROM coffee_archives WHERE coffee_id=?',(c['id'],))
    audit(db,actor,'coffee_deleted' if d['archived'] else 'coffee_restored',{'id':c['id'],'name':c['name'],'profile':c['profile'],'movement_id':move})
    return {'id':c['id'],'archived':d['archived']}
