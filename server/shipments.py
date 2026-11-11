"""Audited historical shipment acknowledgements; never write inventory entries."""
import hashlib,json
from .db import uid,one,rows
from .domain import now,dt,audit,issue


def active(db):
    return rows(db,"""SELECT r.*,f.order_id,f.at shipment_at,f.payload
        FROM fulfillment_reconciliations r JOIN fulfillment_events f ON f.id=r.fulfillment_id
        WHERE r.action='pre_dashboard' AND f.recorded=1
        AND r.rowid=(SELECT MAX(last.rowid) FROM fulfillment_reconciliations last WHERE last.fulfillment_id=r.fulfillment_id)
        ORDER BY r.at,r.rowid""")


def reconcile(db,d,actor,request_id):
    if not request_id or len(request_id)>200:raise ValueError('A request identifier is required.')
    action=d.get('action','pre_dashboard');reason=str(d.get('reason') or '').strip()
    if action not in ('pre_dashboard','reopen'):raise ValueError('Choose a valid shipment reconciliation action.')
    if not reason or len(reason)>2000:raise ValueError('Add a reconciliation note of 1–2,000 characters.')
    data={'fulfillment_id':d['fulfillment_id'],'action':action,'reason':reason}
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    old=db.execute('SELECT * FROM fulfillment_reconciliations WHERE request_id=?',(request_id,)).fetchone()
    if old:
        if old['payload_hash']!=digest:raise ValueError('Request identifier was reused with different data.')
        return {'reconciliation_id':old['id'],'duplicate':True}
    f=one(db,'SELECT f.*,o.source FROM fulfillment_events f JOIN orders o ON o.id=f.order_id WHERE f.id=?',(data['fulfillment_id'],))
    if f['source']!='shopify':raise ValueError('Only imported Shopify shipments can use this reconciliation.')
    if dt(f['at'])>dt(now(db)):raise ValueError('A future shipment cannot be reconciled as historical stock.')
    if db.execute('SELECT 1 FROM fulfillment_picks WHERE fulfillment_id=?',(f['id'],)).fetchone():raise ValueError('This shipment already has a physical stock pick.')
    last=db.execute('SELECT * FROM fulfillment_reconciliations WHERE fulfillment_id=? ORDER BY rowid DESC LIMIT 1',(f['id'],)).fetchone()
    if action=='pre_dashboard':
        if f['recorded']:raise ValueError('This shipment has already been reconciled.')
    elif not f['recorded'] or not last or last['action']!='pre_dashboard':
        raise ValueError('Only a shipment marked as pre-dashboard stock can be reopened.')
    id=uid();at=now(db)
    db.execute('INSERT INTO fulfillment_reconciliations VALUES (?,?,?,?,?,?,?,?)',(id,f['id'],action,at,actor,reason,request_id,digest))
    db.execute('UPDATE fulfillment_events SET recorded=? WHERE id=?',(int(action=='pre_dashboard'),f['id']))
    if action=='pre_dashboard':
        db.execute("UPDATE issues SET resolved=1 WHERE source='shopify' AND external_id=? AND kind='external_fulfillment'",(f['id'],))
    else:
        issue(db,'shopify',f['id'],'external_fulfillment','Historical reconciliation reopened. Record the actual stock pick or review the shipment.')
    audit(db,actor,'fulfillment_'+action,{'reconciliation_id':id,'order_id':f['order_id'],**data})
    return {'reconciliation_id':id}
