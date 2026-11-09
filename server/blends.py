"""Versioned pre-roast blends. All quantities are integer mg; no premixed inventory."""
import json
from decimal import Decimal,InvalidOperation
from .db import rows,one,uid
from .domain import now,stamp,dt,begin_move,audit,positive


def profile(db,coffee):return db.execute('SELECT * FROM blend_profiles WHERE coffee_id=?',(coffee,)).fetchone()


def recipe(db,coffee,at,override=None):
    if override:
        r=db.execute('SELECT r.* FROM blend_recipes r WHERE r.id=? AND r.coffee_id=? AND NOT EXISTS(SELECT 1 FROM blend_recipe_cancellations c WHERE c.recipe_id=r.id)',(override,coffee)).fetchone()
    else:r=db.execute('SELECT r.* FROM blend_recipes r WHERE r.coffee_id=? AND r.effective_at<=? AND NOT EXISTS(SELECT 1 FROM blend_recipe_cancellations c WHERE c.recipe_id=r.id) ORDER BY r.effective_at DESC,r.version DESC LIMIT 1',(coffee,stamp(at))).fetchone()
    return {**dict(r),'ingredients':json.loads(r['ingredients'])} if r else None


def split(total,ingredients):
    parts=[total*i['bp']//10000 for i in ingredients];left=total-sum(parts)
    for n in sorted(range(len(parts)),key=lambda n:(-(total*ingredients[n]['bp']%10000),ingredients[n]['bean_id']))[:left]:parts[n]+=1
    if any(q<=0 for q in parts):raise ValueError('The charge is too small for this recipe’s proportions.')
    return [{**i,'quantity_mg':q} for i,q in zip(ingredients,parts)]


def labels(value):
    if isinstance(value,str):return [value.strip().casefold()]
    if isinstance(value,list):return [label for v in value for label in labels(v)]
    if isinstance(value,dict):return labels(value.get('name') or value.get('tag') or value.get('label') or '')
    return []


def route(db,record):
    values=set(labels(record.get('tags'))+labels(record.get('roastName')))
    matched=[dict(p) for p in db.execute('SELECT * FROM blend_profiles') if p['source_tag'].strip().casefold() in values]
    if len(matched)>1:return None,'More than one blend tag matched. Choose the coffee and recipe for this roast.'
    if matched:return matched[0]['coffee_id'],None
    mapping=db.execute('SELECT coffee_id FROM bean_mappings WHERE external_id=?',(str(record.get('beanId') or ''),)).fetchone()
    return (mapping['coffee_id'],None) if mapping else (None,'Bean assignment / mapping missing')


def charge(db,coffee,at,total,override=None,check_stock=True):
    if not profile(db,coffee):
        if override:raise ValueError('Select a blend coffee to use a recipe override.')
        return None
    r=recipe(db,coffee,at,override)
    if not r:raise ValueError('Espresso recipe missing for this roast date. Set a recipe or choose a saved version.')
    components=split(total,r['ingredients'])
    if check_stock:
        for i in components:
            # A later absolute count already includes earlier roasts. Do not require
            # that their original green supply still exists in today’s balance.
            if db.execute("SELECT 1 FROM green_events WHERE bean_id=? AND kind='count' AND effective_at>?",(i['bean_id'],stamp(at))).fetchone():continue
            q=0
            for e in rows(db,"SELECT * FROM green_events WHERE bean_id=? AND effective_at<=? ORDER BY effective_at,CASE WHEN kind='count' THEN 1 ELSE 0 END,id",(i['bean_id'],stamp(at))):q=e['count_mg'] if e['kind']=='count' else q+e['delta_mg']
            lowest=q
            for e in rows(db,'SELECT delta_mg FROM green_events WHERE bean_id=? AND effective_at>? ORDER BY effective_at,id',(i['bean_id'],stamp(at))):
                q+=e['delta_mg'];lowest=min(lowest,q)
            if lowest<i['quantity_mg']:raise ValueError('Recipe needs '+str(i['quantity_mg']/1000)+' g of '+i['name']+'; only '+str(lowest/1000)+' g is available after recorded green usage. Review its receipts/counts.')
    return {**r,'ingredients':components}


def attach(db,batch,override=None):
    b=one(db,'SELECT * FROM batches WHERE id=?',(batch,))
    r=charge(db,b['coffee_id'],b['roasted_at'],b['green_mg'],override,not b['history_only'])
    if r:db.execute('INSERT INTO batch_blends VALUES (?,?,?)',(batch,r['id'],json.dumps(r['ingredients'])))


def save_profile(db,d,actor,key):
    m,repeat=begin_move(db,'blend_profile',actor,d,key)
    if repeat:return {'duplicate':True}
    coffee=one(db,'SELECT * FROM coffees WHERE id=?',(d['coffee_id'],))
    if db.execute('SELECT 1 FROM coffee_archives WHERE coffee_id=?',(coffee['id'],)).fetchone():raise ValueError('Restore this coffee before setting up its blend.')
    if db.execute('SELECT 1 FROM green_coffee_links WHERE coffee_id=?',(coffee['id'],)).fetchone():raise ValueError('Remove this coffee’s single-bean link in Green beans before configuring it as a blend.')
    tag=str(d.get('source_tag') or '').strip()
    if not tag or len(tag)>80:raise ValueError('Enter a source tag, up to 80 characters.')
    old=profile(db,coffee['id'])
    if int(d.get('version',0))!=(old['version'] if old else 0):raise ValueError('Blend setup changed. Refresh before editing.')
    conflict=db.execute('SELECT coffee_id FROM blend_profiles WHERE source_tag=? COLLATE NOCASE',(tag,)).fetchone()
    if conflict and conflict['coffee_id']!=coffee['id']:raise ValueError('That tag already belongs to another blend.')
    db.execute('INSERT INTO blend_profiles VALUES (?,?,1) ON CONFLICT(coffee_id) DO UPDATE SET source_tag=excluded.source_tag,version=blend_profiles.version+1',(coffee['id'],tag))
    audit(db,actor,'blend_profile',d);return {'coffee_id':coffee['id']}


def save_recipe(db,d,actor,key):
    m,repeat=begin_move(db,'blend_recipe',actor,d,key)
    if repeat:return {'duplicate':True}
    coffee=d['coffee_id']
    if not profile(db,coffee):raise ValueError('Connect the Espresso coffee first.')
    last=db.execute('SELECT MAX(version) n FROM blend_recipes WHERE coffee_id=?',(coffee,)).fetchone()['n'] or 0
    if int(d.get('version',0))!=last:raise ValueError('Another recipe was saved. Refresh before creating the next version.')
    at=stamp(d['effective_at']);latest=db.execute('SELECT MAX(r.effective_at) at FROM blend_recipes r WHERE r.coffee_id=? AND NOT EXISTS(SELECT 1 FROM blend_recipe_cancellations c WHERE c.recipe_id=r.id)',(coffee,)).fetchone()['at']
    if latest and dt(at)<=dt(latest):raise ValueError('The new recipe must start after the previous version. Cancel an unused scheduled version first if needed.')
    incoming=d.get('ingredients');ingredients=[];seen=set();currencies=set()
    if not isinstance(incoming,list) or not 1<=len(incoming)<=20:raise ValueError('Choose between 1 and 20 green beans.')
    for item in incoming:
        b=one(db,'SELECT * FROM green_beans WHERE id=?',(item['bean_id'],))
        if b['id'] in seen:raise ValueError('Choose each green bean only once.')
        seen.add(b['id']);currencies.add(b['currency'])
        try:v=Decimal(str(item['percent']))*100
        except (InvalidOperation,KeyError):raise ValueError('Enter percentages with up to two decimal places.')
        if not v.is_finite() or v<=0 or v>10000 or v!=v.to_integral_value():raise ValueError('Use positive percentages with up to two decimal places.')
        ingredients.append({'bean_id':b['id'],'name':b['name'],'bp':int(v),'currency':b['currency']})
    if sum(i['bp'] for i in ingredients)!=10000:raise ValueError('Recipe percentages must total exactly 100%.')
    if len(currencies)!=1:raise ValueError('Blend component costs must use the same currency; currency conversion is not automatic.')
    note=str(d.get('notes') or '').strip()
    if not note or len(note)>2000:raise ValueError('Add a recipe name or short change note.')
    id=uid();db.execute('INSERT INTO blend_recipes VALUES (?,?,?,?,?,?,?,?)',(id,coffee,last+1,at,json.dumps(ingredients),note,now(db),actor))
    audit(db,actor,'blend_recipe_saved',{'id':id,**d});return {'id':id,'version':last+1}


def cancel_recipe(db,d,actor,key):
    m,repeat=begin_move(db,'blend_recipe_cancel',actor,d,key)
    if repeat:return {'duplicate':True}
    r=one(db,'SELECT * FROM blend_recipes WHERE id=?',(d['id'],))
    if db.execute('SELECT 1 FROM batch_blends WHERE recipe_id=?',(r['id'],)).fetchone():raise ValueError('A batch already uses this recipe. Create a new version instead.')
    reason=str(d.get('reason') or '').strip()
    if not reason:raise ValueError('Enter a cancellation note.')
    db.execute('INSERT OR IGNORE INTO blend_recipe_cancellations VALUES (?,?,?,?)',(r['id'],now(db),actor,reason[:2000]))
    audit(db,actor,'blend_recipe_cancelled',d);return {'id':r['id']}


def snapshot(db):
    recipes=rows(db,'SELECT r.*,EXISTS(SELECT 1 FROM blend_recipe_cancellations c WHERE c.recipe_id=r.id) cancelled,EXISTS(SELECT 1 FROM batch_blends b WHERE b.recipe_id=r.id) used FROM blend_recipes r ORDER BY r.version DESC')
    for r in recipes:r['ingredients']=json.loads(r['ingredients'])
    return {'profiles':rows(db,'SELECT * FROM blend_profiles'),'recipes':recipes}


def batch_snapshot(db):
    result={}
    for b in rows(db,'SELECT b.*,r.version,r.notes,r.effective_at FROM batch_blends b JOIN blend_recipes r ON r.id=b.recipe_id'):
        b['ingredients']=json.loads(b['ingredients']);result[b['batch_id']]=b
    return result


def planned_components(db):
    totals={}
    for p in rows(db,"SELECT * FROM plans WHERE status='planned' AND EXISTS(SELECT 1 FROM blend_profiles b WHERE b.coffee_id=plans.coffee_id)"):
        r=recipe(db,p['coffee_id'],p['roast_at'])
        if not r:continue
        for i in split(p['green_mg'],r['ingredients']):totals[i['bean_id']]=totals.get(i['bean_id'],0)+i['quantity_mg']
    return totals
