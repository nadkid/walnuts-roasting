"""One normalized order-line shape for customer bags and internal cafe requests."""
from .db import rows


def _lines(db,where,args=()):
    result=rows(db,'''SELECT l.*,v.kind,v.coffee_id,v.package_id,p.weight_mg,
        o.source,o.due_at,o.number,o.payment,o.cancelled,
        cl.form request_form,cl.requested_mg,cl.delivered_mg
        FROM lines l JOIN orders o ON o.id=l.order_id
        LEFT JOIN variants v ON v.id=l.variant_id LEFT JOIN packages p ON p.id=v.package_id
        LEFT JOIN cafe_order_lines cl ON cl.line_id=l.id WHERE '''+where,args)
    for l in result:
        l['use']='brew' if l['request_form']=='bulk' else 'retail' if l['source']=='cafe' else 'dispatch'
        if l['request_form']=='bulk':l.update(package_id='bulk',weight_mg=1)
        l['required_mg']=l['requested_mg']-l['delivered_mg'] if l['source']=='cafe' else l['unfulfilled']*(l['weight_mg'] or 0)
    return result


def order_lines(db,order_id=None,open_only=False):
    return _lines(db,'l.order_id=?' if order_id is not None else 'l.unfulfilled>0' if open_only else '1=1',(order_id,) if order_id is not None else ())


def order_line(db,id):
    result=_lines(db,'l.id=?',(id,))
    if not result:raise ValueError('Order line not found. Refresh and try again.')
    return result[0]
