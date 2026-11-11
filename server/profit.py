"""Bean contribution reporting. Missing information is never a zero-cost assumption.
All source money uses integer currency units; intermediate cost rates use Decimal.
No reporting import or shipping edit posts physical inventory.
"""
import json
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from .db import rows, one, settings
from .domain import now, stamp, dt, begin_move, audit, positive
from .green import CURRENCIES, money


def rounded(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def shop_money(bag, currency):
    value=(bag or {}).get('shopMoney')
    if not value or value.get('currencyCode')!=currency:raise ValueError('Missing or mixed source currency.')
    result=money(value.get('amount'),currency)
    if result is None:raise ValueError('Source price is missing.')
    return result


def square_money(value, currency, default=None):
    if value is None:return default
    if value.get('currency')!=currency or type(value.get('amount')) is not int:raise ValueError('Missing or mixed source currency.')
    return value['amount']


def import_shopify(db, order):
    # Older/manual normalized fixtures have no prices. Keep those visibly missing.
    if 'currencyCode' not in order:return
    currency=order['currencyCode'];warnings=[];lines=[]
    def amount(bag):
        try:return shop_money(bag,currency)
        except ValueError:return None
    for item in order['lines']:
        net=amount(item.get('priceAfterAllDiscountsBeforeTaxesSet'))
        gross=amount(item.get('originalTotalSet'))
        discounts=[amount(x.get('allocatedAmountSet')) for x in item.get('discountAllocations',[])]
        taxes=[amount(x.get('priceSet')) for x in item.get('taxLines',[])]
        basis=None if gross is None or None in discounts or None in taxes else max(0,gross-sum(discounts)-(sum(taxes) if order.get('taxesIncluded') else 0))
        lines.append({'id':item['id'],'net_minor':net,'basis_minor':basis,'original_units':int(item['quantity']),'net_units':int(item.get('currentQuantity',item['quantity']))})
    shipping=amount(order.get('currentShippingPriceSet'))
    shipping_taxes=[amount(t.get('priceSet')) for s in order.get('shippingLines',[]) if not s.get('isRemoved') for t in s.get('taxLines',[])]
    refunded_shipping_tax=0
    # Quantity refunds are already reflected in current line net prices. Never subtract twice.
    # Unallocated refunds or pending/failed refund transactions cannot be attributed safely.
    for refund in order.get('refunds',[]):
        transactions=refund.get('transactions',[])
        if not transactions or any(t.get('status')!='SUCCESS' for t in transactions):warnings.append('Refund payment needs review')
        if refund.get('orderAdjustments'):warnings.append('Unallocated refund needs review')
        components=[]
        for item in refund.get('refundLineItems',[]):
            components.extend([amount(item.get('subtotalSet')),amount(item.get('totalTaxSet'))])
        for item in refund.get('refundShippingLines',[]):
            tax=amount(item.get('taxAmountSet'));subtotal=amount(item.get('subtotalAmountSet'))
            components.extend([subtotal,tax])
            if tax is not None:refunded_shipping_tax+=tax
        paid=amount(refund.get('totalRefundedSet'))
        if paid is None or None in components or abs(paid-sum(x or 0 for x in components))>1:warnings.append('Refund allocation needs review')
    if order.get('taxesIncluded'):
        shipping=None if shipping is None or None in shipping_taxes else max(0,shipping-max(0,sum(shipping_taxes)-refunded_shipping_tax))
    if currency not in CURRENCIES:warnings.append('Unsupported currency')
    payload={'lines':lines,'shipping_minor':shipping,'warnings':sorted(set(warnings)),'version':1}
    db.execute('INSERT INTO order_financials VALUES (?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET currency=excluded.currency,sold_at=excluded.sold_at,payload=excluded.payload,updated_at=excluded.updated_at',
               (order['id'],currency,stamp(order.get('processedAt') or order.get('createdAt') or order['updatedAt']),json.dumps(payload),stamp(order['updatedAt'])))


def shipping_eligible(db, order):
    return order['source'] in ('shopify','wholesale') and (order['fulfillment'] in ('FULFILLED','PARTIALLY_FULFILLED') or bool(db.execute('SELECT 1 FROM fulfillment_events WHERE order_id=?',(order['id'],)).fetchone()))


def shipping_snapshot(db):
    return {r['order_id']:{**r,'parcels':json.loads(r['parcels'])} for r in rows(db,'SELECT * FROM order_shipping')}


def save_shipping(db, data, actor, request_id):
    movement,repeat=begin_move(db,'shipping_cost',actor,data,request_id)
    if repeat:return {'duplicate':True}
    order=one(db,'SELECT * FROM orders WHERE id=?',(data['order_id'],))
    if not shipping_eligible(db,order):raise ValueError('Record shipping after the first fulfillment or dispatch is confirmed.')
    old=db.execute('SELECT * FROM order_shipping WHERE order_id=?',(order['id'],)).fetchone()
    if int(data.get('version',0))!=(old['version'] if old else 0):raise ValueError('Shipping details changed. Refresh before editing again.')
    currency=data.get('currency','JPY');mode=data.get('mode','shipping')
    if currency not in CURRENCIES or mode not in ('shipping','pickup'):raise ValueError('Choose a supported currency and delivery type.')
    financial=db.execute('SELECT currency FROM order_financials WHERE order_id=?',(order['id'],)).fetchone()
    if financial and financial['currency']!=currency:raise ValueError('Enter the shipping cost in the order currency. Currency conversion is not automatic.')
    incoming=data.get('parcels',[])
    if not isinstance(incoming,list) or len(incoming)>50 or (mode=='shipping' and not incoming):raise ValueError('Add between 1 and 50 parcels, or choose pickup / no shipping cost.')
    if mode=='pickup' and incoming:raise ValueError('Pickup cannot contain chargeable parcels.')
    parcels=[]
    for item in incoming:
        cost=money(item.get('cost'),currency)
        if cost is None:raise ValueError('Enter each parcel’s actual shipping cost, including 0 for a confirmed free shipment.')
        at=stamp(item['shipped_at'])
        if dt(at)>dt(now(db)):raise ValueError('The dispatch date cannot be in the future.')
        if order['created_at'] and dt(at)<dt(order['created_at']):raise ValueError('The dispatch date cannot be before the order was placed.')
        p={'cost_minor':cost,'shipped_at':at,'weight_mg':positive(item['weight_g']) if item.get('weight_g') not in (None,'') else None}
        for key,limit in [('carrier',100),('service',100),('tracking',200),('notes',1000)]:
            value=str(item.get(key,'')).strip()
            if len(value)>limit:raise ValueError('A shipping field is too long.')
            p[key]=value
        if not p['carrier']:raise ValueError('Enter the carrier or delivery provider for each parcel.')
        parcels.append(p)
    reason=str(data.get('reason','')).strip()
    if not reason or len(reason)>1000:raise ValueError('Add a short note for this shipping record or correction.')
    db.execute('INSERT INTO order_shipping VALUES (?,?,?,?,1,?,?) ON CONFLICT(order_id) DO UPDATE SET currency=excluded.currency,mode=excluded.mode,parcels=excluded.parcels,version=order_shipping.version+1,updated_at=excluded.updated_at,actor=excluded.actor',
               (order['id'],currency,mode,json.dumps(parcels),now(db),actor))
    audit(db,actor,'shipping_cost',{'order_id':order['id'],'before':dict(old) if old else None,'after':{'currency':currency,'mode':mode,'parcels':parcels},'reason':reason,'movement_id':movement})
    return {'order_id':order['id']}


def batch_costs(db):
    """Moving weighted-average green cost, summed across all blend components."""
    events=rows(db,"SELECT e.*,g.currency,COALESCE(e.batch_id,bc.batch_id) costing_batch_id FROM green_events e JOIN green_beans g ON g.id=e.bean_id LEFT JOIN batch_green_components bc ON bc.event_id=e.id ORDER BY effective_at,CASE WHEN e.kind='count' THEN 1 ELSE 0 END,e.id")
    reversed_ids={e['reversal_of'] for e in events if e['reversal_of']};balances={};costs={}
    for e in events:
        if e['kind']=='reversal' or e['id'] in reversed_ids:continue
        qty,value=balances.get(e['bean_id'],(0,Decimal(0)))
        if e['kind']=='purchase':
            value=value+e['total_minor'] if value is not None and e['total_minor'] is not None and qty>=0 else None;qty+=e['delta_mg']
        elif e['kind']=='count':
            count=e['count_mg'];value=Decimal(0) if count==0 else value*count/qty if value is not None and qty>0 and count<=qty else None;qty=count
        elif e['kind']=='roast':
            used=-e['delta_mg'];charge=value*used/qty if value is not None and qty>=used and qty>0 else None
            b=costs.setdefault(e['costing_batch_id'],{'currencies':set(),'charge':Decimal(0),'quantity':0})
            b['currencies'].add(e['currency']);b['quantity']+=used
            b['charge']=b['charge']+charge if b['charge'] is not None and charge is not None else None
            qty-=used;value=value-charge if charge is not None else None
        if qty==0:value=Decimal(0)
        balances[e['bean_id']]=(qty,value)
    result={}
    for batch in rows(db,'SELECT id,green_mg,output_mg FROM batches'):
        cost=costs.get(batch['id'])
        if cost and cost['charge'] is not None and len(cost['currencies'])==1 and cost['quantity']==batch['green_mg'] and batch['output_mg']>0:
            result[batch['id']]={'currency':next(iter(cost['currencies'])),'rate':cost['charge']/batch['output_mg']}
    return result


def allocate(total, weights):
    """Largest remainder allocation preserves every minor unit across line filters."""
    if total is None or any(w is None for w in weights.values()):return {k:None for k in weights}
    denominator=sum(weights.values())
    if not denominator:return {k:0 if total==0 else None for k in weights}
    sign=-1 if total<0 else 1;parts={k:abs(total)*w//denominator for k,w in weights.items()}
    remaining=abs(total)-sum(parts.values())
    for k in sorted(weights,key=lambda k:(-(abs(total)*weights[k]%denominator),k))[:remaining]:parts[k]+=1
    return {k:sign*v for k,v in parts.items()}


def pick_cost(picks, costs, currency, expected):
    if sum(p['quantity_mg'] for p in picks)!=expected:return None,'Batch pick missing or changed'
    value=Decimal(0)
    for p in picks:
        cost=costs.get(p['batch_id'])
        if not cost:return None,'Green purchase cost missing'
        if cost['currency']!=currency:return None,'Bean cost currency differs'
        value+=(p['quantity_mg']+p['overfill_mg'])*cost['rate']
    return rounded(value),None


def estimate_context(db):
    # This is a reporting estimate only: no inventory, green receipt or pick is invented.
    prices={}
    for e in rows(db,"SELECT e.*,g.currency,l.coffee_id FROM green_events e JOIN green_beans g ON g.id=e.bean_id JOIN green_coffee_links l ON l.bean_id=g.id WHERE e.kind='purchase' AND e.total_minor IS NOT NULL AND e.delta_mg>0 AND NOT EXISTS(SELECT 1 FROM green_events r WHERE r.reversal_of=e.id) ORDER BY e.effective_at,e.id"):
        if dt(e['effective_at'])<=dt(now(db)):prices[e['coffee_id']]={'currency':e['currency'],'rate':Decimal(e['total_minor'])/e['delta_mg'],'at':e['effective_at']}
    bean_prices={}
    for e in rows(db,"SELECT e.*,g.currency FROM green_events e JOIN green_beans g ON g.id=e.bean_id WHERE e.kind='purchase' AND e.total_minor IS NOT NULL AND e.delta_mg>0 AND NOT EXISTS(SELECT 1 FROM green_events r WHERE r.reversal_of=e.id) ORDER BY e.effective_at,e.id"):
        if dt(e['effective_at'])<=dt(now(db)):bean_prices[e['bean_id']]={'currency':e['currency'],'rate':Decimal(e['total_minor'])/e['delta_mg']}
    from . import blends
    return {'bean_prices':bean_prices,'blend_profiles':{p['coffee_id'] for p in rows(db,'SELECT * FROM blend_profiles')},'batch_blends':blends.batch_snapshot(db),'recipes':[r for r in blends.snapshot(db)['recipes'] if not r['cancelled']],'prices':prices,'batches':{b['id']:b for b in rows(db,'SELECT * FROM batches')},'coffees':{c['id']:c for c in rows(db,'SELECT * FROM coffees')}}


def sale_cost(picks, costs, currency, expected, coffee_id, at, context):
    cost,why=pick_cost(picks,costs,currency,expected)
    if cost is not None and (picks or expected==0):return cost,why,'recorded','Moving weighted-average green cost; actual roast yield and batch picks.'
    if coffee_id in context.get('blend_profiles',set()):return blend_sale_cost(picks,costs,currency,expected,coffee_id,at,context)
    price=context['prices'].get(coffee_id)
    if not price:return None,'Green purchase cost missing','missing','No priced purchase is linked to this coffee profile.'
    if price['currency']!=currency:return None,'Bean cost currency differs','missing','Currency conversion is not automatic.'
    coffee=context['coffees'].get(coffee_id)
    if not coffee or expected<=0:return None,why or 'Sold quantity needs review','missing','A mapped coffee and positive sold weight are required.'
    notes=[]
    def rate(batch=None):
        if batch and batch['green_mg']>0 and batch['output_mg']>0:
            notes.append('measured yield of '+batch['code'])
            return price['rate']*batch['green_mg']/batch['output_mg']
        notes.append('configured roast yield '+str(coffee['yield_bp']/100)+'%')
        return price['rate']*10000/coffee['yield_bp']
    if picks and sum(p['quantity_mg'] for p in picks)==expected:
        value=Decimal(0)
        for pick in picks:
            actual=costs.get(pick['batch_id'])
            if actual and actual['currency']!=currency:return None,'Bean cost currency differs','missing','Currency conversion is not automatic.'
            r=actual['rate'] if actual else rate(context['batches'].get(pick['batch_id']))
            value+=(pick['quantity_mg']+pick['overfill_mg'])*r
    else:
        # Without a physical pick use the configured yield; never guess a batch.
        value=Decimal(expected)*rate()
        notes.append('sold bag weight; historical batch/overfill unavailable')
    note='Estimated using latest entered green price ('+price['at'][:10]+'); '+ '; '.join(dict.fromkeys(notes))+'.'
    return rounded(value),None,'estimated',note


def blend_sale_cost(picks,costs,currency,expected,coffee_id,at,context):
    if expected<=0:return None,'Sold quantity needs review','missing','A positive blend sale weight is required.'
    notes=[]
    def rate(batch_id=None):
        frozen=context['batch_blends'].get(batch_id)
        batch=context['batches'].get(batch_id)
        if frozen:
            ingredients=frozen['ingredients'];notes.append('saved batch recipe v'+str(frozen['version']))
        else:
            when=(batch.get('roasted_at') if batch else None) or at
            recipes=[r for r in context['recipes'] if r['coffee_id']==coffee_id and when and dt(r['effective_at'])<=dt(when)]
            if not recipes:raise ValueError('Blend recipe missing for the sale / roast date')
            r=max(recipes,key=lambda r:(r['effective_at'],r['version']));ingredients=r['ingredients'];notes.append('dated recipe v'+str(r['version'])+'; actual batch recipe unavailable')
        price=Decimal(0)
        for i in ingredients:
            p=context['bean_prices'].get(i['bean_id'])
            if not p:raise ValueError('Green purchase cost missing for '+i['name'])
            if p['currency']!=currency:raise ValueError('Bean cost currency differs')
            price+=p['rate']*(Decimal(i['quantity_mg'])/batch['green_mg'] if frozen and batch and batch['green_mg']>0 else Decimal(i['bp'])/10000)
        if batch and batch['green_mg']>0 and batch['output_mg']>0:return price*batch['green_mg']/batch['output_mg']
        return price*10000/context['coffees'][coffee_id]['yield_bp']
    try:
        if picks and sum(p['quantity_mg'] for p in picks)==expected:
            value=Decimal(0)
            for p in picks:
                actual=costs.get(p['batch_id'])
                if actual and actual['currency']!=currency:raise ValueError('Bean cost currency differs')
                value+=(p['quantity_mg']+p['overfill_mg'])*(actual['rate'] if actual else rate(p['batch_id']))
        else:value=Decimal(expected)*rate()
    except ValueError as e:return None,str(e),'missing',str(e)
    return rounded(value),None,'estimated','Estimated from component green prices; '+ '; '.join(dict.fromkeys(notes))+'.'


def finish(row):
    row['issues']=list(dict.fromkeys(row['issues']))
    row['revenue_minor']=None if row['net_sales_minor'] is None or row['shipping_income_minor'] is None else row['net_sales_minor']+row['shipping_income_minor']
    row['profit_minor']=None if row['issues'] or any(row[k] is None for k in ('revenue_minor','bean_cost_minor','shipping_cost_minor')) else row['revenue_minor']-row['bean_cost_minor']-row['shipping_cost_minor']
    row['margin_pct']=round(row['profit_minor']/row['revenue_minor']*100,2) if row['profit_minor'] is not None and row['revenue_minor'] else None
    row['status']='complete' if row['profit_minor'] is not None else 'incomplete'
    return row


def snapshot(db):
    costs=batch_costs(db);context=estimate_context(db);result=[];shipping=shipping_snapshot(db);cfg=settings(db)
    from .shipments import active
    historical_lines={(r['order_id'],line['line_id']) for r in active(db) for line in json.loads(r['payload'])['lines']}
    # Square retains historical receipts even before inventory cutover. Their costs
    # use labelled current-price estimates when actual batch picks are unavailable.
    mappings={r['external_id']:r for r in rows(db,"SELECT v.*,p.coffee_id,p.package_id,k.weight_mg,c.name coffee,c.profile FROM sale_catalog v LEFT JOIN sale_products p ON p.id=v.product_id LEFT JOIN packages k ON k.id=p.package_id LEFT JOIN coffees c ON c.id=p.coffee_id WHERE v.source='square'")}
    returns=defaultdict(list)
    for record in rows(db,'SELECT payload FROM square_return_orders'):
        payload=json.loads(record['payload'])
        if payload.get('state')!='COMPLETED':continue
        for ret in payload.get('returns',[]):returns[ret.get('source_order_id')].append(ret)
    for sale in rows(db,"SELECT * FROM square_sales WHERE state='COMPLETED' AND status NOT IN ('noncoffee','outside_scope') ORDER BY completed_at"):
        if cfg.get('square_location_id') and sale['location_id']!=cfg['square_location_id']:continue
        payload=json.loads(sale['payload']);posted=json.loads(sale['posted_payload'] or sale['payload'])
        picks=rows(db,'SELECT p.*,s.batch_id,b.code FROM square_sale_picks p JOIN stocks s ON s.id=p.stock_id JOIN batches b ON b.id=s.batch_id WHERE p.sale_id=?',(sale['id'],))
        for line in payload['line_items']:
            mapping=mappings.get(line.get('catalog_object_id'))
            if mapping and (mapping['kind']=='noncoffee' or cfg.get('square_category_id') and not mapping['in_scope']):continue
            selected=[p for p in picks if p['line_uid']==line.get('uid')];issues=[]
            currency=(line.get('total_money') or {}).get('currency','JPY');net=None;units=None
            try:
                raw_units=Decimal(line.get('quantity','0'))
                if not raw_units.is_finite() or raw_units<=0:raise ValueError('Invalid sold units')
                units=float(raw_units)
                total=square_money(line.get('total_money'),currency)
                tax=square_money(line.get('total_tax_money'),currency,0)
                service=square_money(line.get('total_service_charge_money'),currency,0)
                if total is not None:net=total-tax-service
                else:issues.append('Sale price missing')
            except (ValueError,ArithmeticError):issues.append('Sale price missing')
            refunded=0;refund_qty=Decimal(0)
            for ret in returns.get(sale['id'],[]):
                for item in ret.get('return_line_items',[]):
                    if item.get('source_line_item_uid')!=line.get('uid'):continue
                    try:
                        returned=square_money(item.get('total_money'),currency)
                        if returned is None:raise ValueError()
                        refunded+=returned-square_money(item.get('total_tax_money'),currency,0)-square_money(item.get('total_service_charge_money'),currency,0)
                        refund_qty+=Decimal(item['quantity'])
                    except (ValueError,ArithmeticError,KeyError):issues.append('Refund allocation needs review')
                if ret.get('return_line_items') is None:issues.append('Refund allocation needs review')
            # Amount-only refunds have no reliable bean allocation (mixed café receipts).
            if payload.get('has_returns') and not returns.get(sale['id']):issues.append('Refund allocation needs review');net=None
            if any(x.get('status') not in ('APPROVED','COMPLETED') for x in payload.get('refunds',[])):issues.append('Refund payment needs review');net=None
            if net is not None:
                net-=refunded
                if net<0:issues.append('Refund exceeds sale amount');net=None
            if payload.get('refunds') and returns.get(sale['id']):
                try:
                    refunded_total=sum(square_money(x.get('amount_money'),currency) for x in payload['refunds'])
                    itemized_total=sum(square_money(x.get('total_money'),currency) for ret in returns[sale['id']] for x in ret.get('return_line_items',[]))
                    if refunded_total!=itemized_total:issues.append('Refund allocation needs review');net=None
                except (ValueError,TypeError):issues.append('Refund allocation needs review');net=None
            if any(any(not x.get('source_line_item_uid') for x in ret.get('return_line_items',[])) or not ret.get('return_line_items') for ret in returns.get(sale['id'],[])):issues.append('Refund allocation needs review');net=None
            if not mapping or mapping['kind']!='coffee' or mapping['review']:issues.append('Product mapping needs review')
            if sale['status']=='source_review':issues.append('Receipt changed after batch pick')
            if currency not in CURRENCIES:issues.append('Unsupported currency')
            original=next((l for l in posted['line_items'] if l.get('uid')==line.get('uid')),line)
            try:
                expected=Decimal(original.get('quantity','0'))*(mapping['weight_mg'] or 0) if mapping else Decimal(0)
                if not expected.is_finite() or expected<=0:raise ValueError()
            except (ValueError,ArithmeticError):expected=0;issues.append('Sold quantity needs review')
            cost,why,basis,cost_note=sale_cost(selected,costs,currency,expected,mapping['coffee_id'],sale['completed_at'],context) if mapping and mapping['kind']=='coffee' and not mapping['review'] else (None,'Product mapping needs review','missing','Approve the coffee mapping first.')
            if why:issues.append(why)
            if not selected and expected==0:cost=None;issues.append('Batch pick missing or changed')
            result.append(finish({'id':'square:'+sale['id']+':'+line.get('uid',''),'order_id':sale['id'],'number':'Square · '+sale['id'][-8:], 'source':'square','sold_at':sale['completed_at'],'currency':currency,'coffee_id':mapping['coffee_id'] if mapping else None,'coffee':mapping['coffee'] if mapping else line.get('name','Unmapped item'),'profile':mapping['profile'] if mapping else '', 'package_id':mapping['package_id'] if mapping else None,'weight_mg':mapping['weight_mg'] if mapping else None,'units':units,'net_units':(units-float(refund_qty)) if units is not None else None,'net_sales_minor':net,'shipping_income_minor':0,'bean_cost_minor':cost,'cost_basis':basis,'cost_note':cost_note,'shipping_cost_minor':0,'issues':issues,'batches':list(dict.fromkeys(p['code'] for p in selected)),'can_ship':False,'shipping':None}))
    financials={r['order_id']:r for r in rows(db,'SELECT * FROM order_financials')}
    for order in rows(db,"SELECT * FROM orders WHERE source='shopify' AND payment IN ('PAID','PARTIALLY_REFUNDED','REFUNDED')"):
        # Include fulfilled sales and refunded sales with a physical fulfillment.
        fulfilled=db.execute('SELECT 1 FROM fulfillment_events WHERE order_id=?',(order['id'],)).fetchone()
        if order['fulfillment']!='FULFILLED' and not (order['payment'] in ('REFUNDED','PARTIALLY_REFUNDED') and fulfilled):continue
        financial=financials.get(order['id']);data=json.loads(financial['payload']) if financial else {};currency=financial['currency'] if financial else 'JPY'
        lines=rows(db,'SELECT l.*,v.kind,v.coffee_id,v.package_id,p.weight_mg,c.name coffee,c.profile FROM lines l LEFT JOIN variants v ON v.id=l.variant_id LEFT JOIN coffees c ON c.id=v.coffee_id LEFT JOIN packages p ON p.id=v.package_id WHERE l.order_id=?',(order['id'],))
        amounts={l['id']:l for l in data.get('lines',[])}
        weights={l['id']:amounts.get(l['id'],{}).get('basis_minor') for l in lines}
        entry=shipping.get(order['id']);ship_total=sum(p['cost_minor'] for p in entry['parcels']) if entry and entry['currency']==currency else None
        income=allocate(data.get('shipping_minor'),weights);expenses=allocate(ship_total,weights)
        for line in lines:
            if line['kind']=='noncoffee':continue
            money_line=amounts.get(line['id'],{});issues=list(data.get('warnings',[]))
            net=money_line.get('net_minor')
            if data.get('warnings'):net=None
            if net is None:issues.append('Sale price or refund needs review')
            if line['kind']!='coffee':issues.append('Product mapping needs review')
            picks=rows(db,'SELECT p.*,s.batch_id,b.code FROM fulfillment_picks p JOIN stocks s ON s.id=p.stock_id JOIN batches b ON b.id=s.batch_id WHERE p.line_id=? AND NOT EXISTS(SELECT 1 FROM movements m WHERE m.reversal_of=p.movement_id)',(line['id'],))
            expected=0
            for f in rows(db,'SELECT payload FROM fulfillment_events WHERE order_id=?',(order['id'],)):
                expected+=sum(int(x['quantity'])*(line['weight_mg'] or 0) for x in json.loads(f['payload'])['lines'] if x['line_id']==line['id'])
            if not expected and (fulfilled or order['fulfillment']=='FULFILLED'):
                expected=int(money_line.get('original_units',line['quantity']))*(line['weight_mg'] or 0)
            cost,why,basis,cost_note=sale_cost(picks,costs,currency,expected,line['coffee_id'],financial['sold_at'] if financial else order['created_at'],context) if line['kind']=='coffee' else (None,'Product mapping needs review','missing','Approve the coffee mapping first.')
            if why:issues.append(why)
            if (order['id'],line['id']) in historical_lines:cost_note='Shipped from pre-dashboard stock; actual batch history unavailable. '+cost_note
            if not fulfilled and basis!='estimated':cost=None;issues.append('Batch pick missing or changed')
            if expenses.get(line['id']) is None:issues.append('Shipping cost missing' if not entry else 'Shipping allocation or currency needs review')
            if income.get(line['id']) is None:issues.append('Shipping revenue missing')
            result.append(finish({'id':'shopify:'+line['id'],'order_id':order['id'],'number':order['number'],'source':'shopify','sold_at':financial['sold_at'] if financial else order['created_at'],'currency':currency,'coffee_id':line['coffee_id'],'coffee':line['coffee'] or line['title'],'profile':line['profile'],'package_id':line['package_id'],'weight_mg':line['weight_mg'],'units':money_line.get('original_units',line['quantity']),'net_units':money_line.get('net_units',line['quantity']),'net_sales_minor':net,'shipping_income_minor':income.get(line['id']),'bean_cost_minor':cost,'cost_basis':basis,'cost_note':cost_note,'shipping_cost_minor':expenses.get(line['id']),'issues':issues,'batches':list(dict.fromkeys(p['code'] for p in picks)),'can_ship':shipping_eligible(db,order),'shipping':entry}))
    return {'rows':result,'currencies':sorted({r['currency'] for r in result}) or ['JPY'],'generated_at':now(db),'method':'moving_weighted_average'}
