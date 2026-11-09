from datetime import timedelta
from decimal import Decimal
import json, math
from .db import rows, one, settings
from .domain import dt, stamp, now, JST, eligibility, stock, order_eligible, at_roastery

def plan(db,horizon=14):
    cfg=settings(db);clock=dt(now(db));end=clock+timedelta(days=horizon);demands=[];problems=[]
    for l in rows(db,"SELECT l.*,o.due_at,o.number,o.payment,o.cancelled,v.kind,v.coffee_id,p.weight_mg FROM lines l JOIN orders o ON o.id=l.order_id LEFT JOIN variants v ON v.id=l.variant_id LEFT JOIN packages p ON p.id=v.package_id WHERE l.unfulfilled>0"):
        if not order_eligible(db,l['order_id']) or l['kind']=='noncoffee':continue
        if l['kind']!='coffee':problems.append(l['number']+': variant mapping required');continue
        if not l['due_at']:problems.append(l['number']+': target dispatch / pickup date required');continue
        demands.append({'id':l['id'],'coffee_id':l['coffee_id'],'channel':'dispatch','due_at':l['due_at'],'quantity_mg':l['unfulfilled']*l['weight_mg'],'label':l['number'],'type':'line_id','unit_mg':l['weight_mg']})
    for d in rows(db,'SELECT d.* FROM demands d WHERE NOT EXISTS(SELECT 1 FROM coffee_archives a WHERE a.coffee_id=d.coffee_id)'):
        demands.append({**d,'label':d['note'] or ('Café forecast' if d['channel']=='brew' else 'Retail target'),'type':'demand_id'})
    order=cfg['channel_priority'];demands.sort(key=lambda d:(d['due_at'],order.index(d['channel'])))
    supply=[]
    for r in rows(db,'SELECT id FROM stocks WHERE quantity_mg>0'):
        s=stock(db,r['id']);s['left']=s['quantity_mg']-s['reserved_mg'];supply.append(s)
    for p in rows(db,"SELECT p.*,c.name coffee FROM plans p JOIN coffees c ON c.id=p.coffee_id WHERE p.status='planned'"):
        supply.append({'coffee_id':p['coffee_id'],'roasted_at':p['roast_at'],'policy':p['policy'],'held':0,'archived':0,'left':p['expected_mg'],'code':'Plan '+p['id'][:6],'id':p['id'],'planned':True})
    supply.sort(key=lambda s:s['roasted_at'] or '')
    result=[];retail_holds={};used_slots={stamp(p['roast_at']) for p in rows(db,"SELECT roast_at FROM plans WHERE status='planned'")}
    for d in demands:
        if dt(d['due_at'])>end:continue
        coffee=one(db,'SELECT * FROM coffees WHERE id=?',(d['coffee_id'],));need=d['quantity_mg'];covered=0;allocations=[]
        if d['channel']=='retail':
            retained=[]
            for held in retail_holds.get(d['coffee_id'],[]):
                if eligibility(held['stock'],'retail',d['due_at'])[0]:
                    retained.append(held);take=min(need,held['qty']);need-=take;covered+=take
                    if take:allocations.append({'batch':held['stock']['code'],'grams':take/1000,'kind':'target carryover'})
            retail_holds[d['coffee_id']]=retained
        outside_order_allocation=False
        # Customer orders can use only physical stock at the roastery.
        for r in rows(db,'SELECT * FROM reservations WHERE '+d['type']+'=?',(d['id'],)):
            s=stock(db,r['stock_id'])
            if d['channel']=='dispatch' and not at_roastery(s):
                outside_order_allocation=True;continue
            if eligibility(s,d['channel'],d['due_at'])[0]:
                take=min(need,r['quantity_mg'])
                if d['channel']=='dispatch':take=(take//d['unit_mg'])*d['unit_mg']
                need-=take;covered+=take;allocations.append({'batch':s['code'],'grams':take/1000,'kind':'reserved'})
                if d['channel']=='retail' and take:retail_holds[d['coffee_id']].append({'stock':s,'qty':take})
        for s in supply:
            if need<=0:break
            if d['channel']=='dispatch' and not s.get('planned') and not at_roastery(s):continue
            if s['coffee_id']!=d['coffee_id'] or not eligibility(s,d['channel'],d['due_at'])[0]:continue
            if s.get('package_id','bulk')!='bulk' and d['channel']=='brew':continue # opening still required; do not imply ready bulk
            if d['channel']=='dispatch' and s.get('package_id','bulk')!='bulk':
                line=one(db,'SELECT v.package_id FROM lines l JOIN variants v ON v.id=l.variant_id WHERE l.id=?',(d['id'],))
                if s['package_id']!=line['package_id']:continue
            take=min(need,s['left'])
            if d['channel']=='dispatch':take=(take//d['unit_mg'])*d['unit_mg']
            elif s.get('package_mg'):
                take=(take//s['package_mg'])*s['package_mg']
            s['left']-=take;need-=take;covered+=take
            if take:allocations.append({'batch':s['code'],'grams':take/1000,'kind':'planned' if s.get('planned') else 'physical'})
            if d['channel']=='retail' and take:retail_holds[d['coffee_id']].append({'stock':s,'qty':take})
        rest=coffee[d['channel']+'_days'];deadline=None;warning=[];charges=[];green=0;excess=0
        history=one(db,'SELECT COALESCE(SUM(output_mg),0) o,COALESCE(SUM(green_mg),0) g FROM batches WHERE coffee_id=? AND output_mg>0 AND green_mg>output_mg',(coffee['id'],))
        yield_bp=history['o']*10000//history['g'] if history['g'] else coffee['yield_bp'];yield_source='measured history' if history['g'] else 'configured estimate'
        if outside_order_allocation:warning.append('Order allocation outside the roastery; review its reservation.')
        if rest is None: warning.append('Configure '+d['channel']+' rest policy')
        else:
            deadline=dt(d['due_at'])-timedelta(days=rest+cfg['buffer_days']);local=deadline.astimezone(JST)
            # Latest configured slot that precedes the true rest/buffer deadline.
            candidate=latest_slot(deadline,cfg,used_slots)
            deadline=stamp(candidate)
            if dt(deadline)<clock and need:warning.append('Deadline at risk: latest roast slot has passed')
        schedule=[]
        if need:
            if not cfg['max_charge_mg']:warning.append('Confirm Bullet maximum charge before approving')
            charge=cfg['charge_mg'];max_charge=cfg['max_charge_mg'] or charge
            if charge>max_charge:warning.append('Working charge exceeds configured maximum')
            charge=min(charge,max_charge)
            required=(need*(10000+cfg['safety_bp'])+9999)//10000
            n=(required*10000+charge*yield_bp-1)//(charge*yield_bp);charges=[charge]*n;green=sum(charges);expected=green*yield_bp//10000;excess=expected-need
            if deadline:
                limit=dt(d['due_at'])-timedelta(days=rest+cfg['buffer_days'])
                for _ in charges:
                    chosen=latest_slot(limit,cfg,used_slots);key=stamp(chosen);schedule.append(key);used_slots.add(key)
                deadline=schedule[0]
                if any(dt(t)<clock for t in schedule) and not any('passed' in w for w in warning):warning.append('Deadline at risk: required roast slots have passed')
            if d['channel']=='retail' and deadline:
                retail_holds[d['coffee_id']].append({'stock':{'roasted_at':deadline,'held':0,'archived':0,'policy':json.dumps({k:coffee[k] for k in ('brew_days','dispatch_days','retail_days','fresh_days')}),'code':'Earlier wall roast suggestion'},'qty':need})
            # Suggested future supply is spent once; its rounding excess can cover subsequent demand.
            if deadline and excess>0:
                supply.append({'coffee_id':coffee['id'],'roasted_at':deadline,'policy':json.dumps({k:coffee[k] for k in ('brew_days','dispatch_days','retail_days','fresh_days')}),'held':0,'archived':0,'left':excess,'code':'Suggestion carryover','id':'suggestion','planned':True})
                supply.sort(key=lambda s:s['roasted_at'] or '')
        result.append({**d,'coffee':coffee['name'],'profile':coffee['profile'],'covered_mg':covered,'shortage_mg':need,'allocations':allocations,'yield_bp':yield_bp,'yield_source':yield_source,'green_mg':green,'charges_mg':charges,'roast_slots':schedule,'excess_mg':excess,'latest_roast_at':deadline,'ready_at':stamp(dt(deadline)+timedelta(days=rest)) if deadline else None,'warnings':warning})
    from . import blends
    for r in result:
        if blends.profile(db,r['coffee_id']) and r['green_mg']>0:
            try:
                blend=blends.charge(db,r['coffee_id'],r['latest_roast_at'] or now(db),r['green_mg'],check_stock=False)
                r['blend_components']=blend['ingredients']
            except ValueError as e:r['warnings'].append(str(e))
    return {'rows':result,'issues':problems,'horizon_days':horizon,'generated_at':now(db)}

def latest_slot(limit,cfg,used):
    local=limit.astimezone(JST)
    for day in range(3660):
        base=local-timedelta(days=day)
        if base.weekday() not in cfg['roast_days']:continue
        for slot in sorted(cfg['roast_slots'],reverse=True):
            hour,minute=map(int,slot.split(':'));candidate=base.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if candidate<=local and stamp(candidate) not in used:return candidate
    raise ValueError('No available roast slots in the planning search window.')
