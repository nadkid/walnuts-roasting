"""Read-only customer-order work list. Never reserve stock or create roast plans."""
from collections import defaultdict
from datetime import timedelta
from .db import rows, settings
from .domain import dt, stamp, now, stock, eligibility, order_eligible, at_roastery
from .planner import latest_slot
from . import coffees, blends


def customer_roast(db):
    cfg=settings(db);clock=now(db)
    profiles={c['id']:c for c in coffees.snapshot(db)}
    orders={o['id']:o for o in rows(db,'SELECT * FROM orders')
            if not o['cancelled'] and not o['closed_at'] and o['fulfillment']!='FULFILLED'
            and order_eligible(db,o['id'])}
    lines=rows(db,'''SELECT l.*,v.kind,v.coffee_id,v.package_id,p.weight_mg
        FROM lines l LEFT JOIN variants v ON v.id=l.variant_id
        LEFT JOIN packages p ON p.id=v.package_id WHERE l.unfulfilled>0''')
    demands=[];unmapped=set()
    for line in lines:
        if line['order_id'] not in orders or line['kind']=='noncoffee':continue
        if line['kind']!='coffee' or line['coffee_id'] not in profiles or not line['weight_mg']:
            unmapped.add(line['order_id']);continue
        o=orders[line['order_id']]
        demands.append({**line,'number':o['number'],'source':o['source'],'due_at':o['due_at'],
                        'required_mg':line['unfulfilled']*line['weight_mg'],
                        'stock_mg':0,'scheduled_mg':0,'roast_mg':None,'roast_by':None,'notes':[]})
    demands.sort(key=lambda d:(dt(d['due_at']) if d['due_at'] else dt('9999-01-01T00:00:00Z'),d['number'],d['id']))
    supply={r['id']:stock(db,r['id']) for r in rows(db,"SELECT id FROM stocks WHERE quantity_mg>0 AND location_id='roastery'")}
    for s in supply.values():s['left']=max(0,s['quantity_mg']-s['reserved_mg'])
    available=sorted(supply.values(),key=lambda s:(s['roasted_at'] or '',s['id']))
    reservations=defaultdict(list)
    for r in rows(db,'SELECT r.*,s.location_id FROM reservations r JOIN stocks s ON s.id=r.stock_id WHERE r.line_id IS NOT NULL'):reservations[r['line_id']].append(r)
    plans=rows(db,"SELECT * FROM plans WHERE status='planned' ORDER BY roast_at,id")
    for p in plans:p.update(left=p['expected_mg'],roasted_at=p['roast_at'],held=0,archived=0)

    def suitable(s,d):
        return s['coffee_id']==d['coffee_id'] and s.get('package_id','bulk') in ('bulk',d['package_id']) and eligibility(s,'dispatch',max((d['due_at'],clock),key=dt))[0]

    # Net bulk grams can be consolidated before packing. Packed bags must match
    # the requested size. Spend stock once, by deadline, without forecast demand.
    for d in demands:
        if not d['due_at']:
            d['notes'].append('Add an order deadline to calculate roasting needs.');continue
        need=d['required_mg']
        for r in reservations[d['id']]:
            if not at_roastery(r):
                d['notes'].append('An order allocation is outside the roastery. Review it before reallocating.');continue
            s=supply.get(r['stock_id'])
            if not s or not suitable(s,d):
                d['notes'].append('Review an allocation that is not suitable for this deadline.');continue
            if r['quantity_mg']%d['weight_mg']:d['notes'].append('Review split-bag allocations.')
            take=min(need,r['quantity_mg'])
            need-=take
        # Use matching packed bags before flexible bulk, which can cover other sizes.
        for s in sorted(available,key=lambda s:s['package_id']=='bulk'):
            if not need:break
            if not suitable(s,d):continue
            usable=s['left'] if s['package_id']=='bulk' else s['left']//d['weight_mg']*d['weight_mg']
            take=min(need,usable)
            s['left']-=take;need-=take
        d['stock_mg']=d['required_mg']-need;d['roast_mg']=need
        if not need:continue
        coffee=profiles[d['coffee_id']]
        if coffee['dispatch_days'] is None:d['notes'].append('Set the dispatch rest policy.');continue
        limit=dt(d['due_at'])-timedelta(days=coffee['dispatch_days']+cfg['buffer_days'])
        try:d['roast_by']=stamp(latest_slot(limit,cfg,set()))
        except ValueError:d['notes'].append('Set the roasting days and start times.')

    # Approved supply is a subset of work still to roast, never physical stock.
    for d in demands:
        if not d['roast_mg']:continue
        need=d['roast_mg']
        for p in plans:
            if not suitable(p,d):continue
            take=min(need,p['left'])
            p['left']-=take;need-=take;d['scheduled_mg']+=take
            if take and dt(p['roast_at'])<dt(clock):d['notes'].append('A scheduled roast is overdue.')
            if not need:break

    grouped=defaultdict(list)
    for d in demands:grouped[d['coffee_id']].append(d)
    yields={r['coffee_id']:(r['o']*10000//r['g']) for r in rows(db,'''SELECT coffee_id,SUM(output_mg) o,SUM(green_mg) g
        FROM batches WHERE output_mg>0 AND green_mg>output_mg GROUP BY coffee_id''')}
    pending_pick_coffees={r['coffee_id'] for r in rows(db,'''SELECT DISTINCT v.coffee_id FROM fulfillment_events f JOIN lines l ON l.order_id=f.order_id JOIN variants v ON v.id=l.variant_id WHERE f.recorded=0 AND v.kind='coffee' ''')}
    tiles=[]
    for c in profiles.values():
        ds=grouped[c['id']]
        if c['archived'] and not ds:continue
        roast=sum(d['roast_mg'] or 0 for d in ds);scheduled=sum(d['scheduled_mg'] for d in ds)
        unknown=sum(d['roast_mg'] is None for d in ds)
        roast_by=min((d['roast_by'] for d in ds if d['roast_mg'] and d['roast_by']),default=None,key=dt)
        due=min((d['due_at'] for d in ds if d['due_at']),default=None,key=dt)
        notes=list(dict.fromkeys(n for d in ds for n in d['notes']))
        if ds and c['id'] in pending_pick_coffees:notes.append('A shipment needs its actual stock pick recorded; check stock coverage.')
        if c['archived']:notes.append('This coffee is currently deleted from the lineup.')
        overdue=any(d['due_at'] and dt(d['due_at'])<dt(clock) for d in ds)
        missed=any(d['roast_mg'] and d['roast_by'] and dt(d['roast_by'])<dt(clock) for d in ds)
        if overdue:tone,label='red','Order overdue'
        elif missed:tone,label='red','Roast overdue'
        elif unknown:tone,label='yellow','Set deadline'
        elif notes:tone,label='yellow','Needs attention'
        elif roast>scheduled:tone,label='yellow','To schedule'
        elif roast:tone,label='green','Scheduled'
        else:tone,label='green','Stock covered' if ds else 'No orders'
        yield_bp=max(1,yields.get(c['id'],c['yield_bp']))
        green=((roast*10000+yield_bp*1000-1)//(yield_bp*1000))*1000
        mix=[]
        if green and blends.profile(db,c['id']):
            try:
                recipe_at=max((clock,roast_by or clock),key=dt)
                mix=blends.charge(db,c['id'],recipe_at,green,check_stock=False)['ingredients']
            except ValueError as e:
                notes.append(str(e))
                if tone!='red':tone,label='yellow','Needs recipe'
        order_rows=[]
        for order_id in dict.fromkeys(d['order_id'] for d in ds):
            ls=[d for d in ds if d['order_id']==order_id];first=ls[0]
            order_rows.append({'id':order_id,'number':first['number'],'source':first['source'],
                'due_at':first['due_at'],'required_mg':sum(d['required_mg'] for d in ls),
                'stock_mg':sum(d['stock_mg'] for d in ls),'roast_mg':None if any(d['roast_mg'] is None for d in ls) else sum(d['roast_mg'] for d in ls),
                'scheduled_mg':sum(d['scheduled_mg'] for d in ls),
                'quantities':[{'units':d['unfulfilled'],'unit_mg':d['weight_mg']} for d in ls]})
        tiles.append({'coffee_id':c['id'],'name':c['name'],'profile':c['profile'],
            'roast_mg':roast,'scheduled_mg':scheduled,'unplanned_mg':roast-scheduled,
            'unknown_lines':unknown,'roast_by':roast_by,'due_at':due,'tone':tone,'status':label,
            'green_mg':green,'blend_components':mix,'notes':notes,'orders':order_rows})
    tiles.sort(key=lambda t:({'red':0,'yellow':1,'green':2}[t['tone']],not bool(t['orders']),dt(t['roast_by'] or t['due_at'] or '9999-01-01T00:00:00Z'),t['name'].casefold(),t['profile'],t['coffee_id']))
    return {'coffees':tiles,'unmapped_orders':len(unmapped),'order_count':len({d['order_id'] for d in demands}|unmapped)}
