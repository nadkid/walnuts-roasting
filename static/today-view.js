import {coffeeRoastPanel} from './coffee-roast-view.js';

export function beanOverview(S){
  const coffees=new Map(S.coffees.map(c=>[c.id,c]));
  const blendIds=new Set((S.blends?.profiles||[]).map(p=>p.coffee_id));
  const visibleBeans=(S.green?.beans||[]).filter(b=>!b.coffee_ids.length||b.coffee_ids.some(id=>!coffees.get(id)?.archived)||b.quantity_mg!==0);
  const rows=visibleBeans.map(b=>({
    id:b.id,name:b.name,origin:b.origin,green_mg:b.quantity_mg,
    profiles:b.coffee_ids.map(id=>coffees.get(id)).filter(c=>c&&!c.archived)
  }));
  const linked=new Set(rows.flatMap(r=>r.profiles.map(c=>c.id)));
  // Unlinked profiles remain visible; an unknown green balance is never zero.
  rows.push(...S.coffees.filter(c=>!c.archived&&!linked.has(c.id)).map(c=>({id:'coffee:'+c.id,name:c.name,green_mg:null,profiles:[c],is_blend:blendIds.has(c.id)})));
  const owners=new Map();
  for(const r of rows){
    Object.assign(r,{rested_mg:0,ship_mg:0,cafe_mg:0,wall_mg:0,cafe_held_mg:0,wall_held_mg:0,wall_bags:0,wall_bulk_mg:0});
    for(const c of r.profiles)owners.set(c.id,r);
  }
  for(const s of S.stocks){
    const r=owners.get(s.coffee_id);
    if(!r)continue;
    const physical=(s.quantity_mg||0)+(s.overfill_mg||0);
    if(s.readiness.brew.eligible)r.rested_mg+=physical;
    // Packaged coffee only: eligible bulk still needs packing before dispatch.
    if(s.package_mg>0&&s.readiness.dispatch.eligible)r.ship_mg+=s.quantity_mg;
    if(s.location_id==='cafe'||s.location_id==='wall'){
      const prefix=s.location_id;
      r[prefix+'_mg']+=physical;
      if(s.held||s.archived)r[prefix+'_held_mg']+=physical;
      if(prefix==='wall'){
        if(s.package_mg>0)r.wall_bags+=s.quantity_mg/s.package_mg;
        else r.wall_bulk_mg+=physical;
      }
    }
  }
  return rows.sort((a,b)=>a.name.localeCompare(b.name,'en')||a.id.localeCompare(b.id));
}

function beansPanel(rows,h){
  const {esc,kg,badge,empty}=h;
  return `<section class="panel bean-overview" aria-labelledby="beans-title"><div class="panel-heading"><div><span class="eyebrow">FROM GREEN TO DISPATCH</span><h2 id="beans-title">Bean overview</h2><p>One balance per bean, across its roast profiles and locations.</p></div><a href="#green">Manage green beans ↗</a></div>
    ${rows.length?`<div class="table-wrap"><table><thead><tr><th scope="col">Bean / roast profiles</th><th scope="col">Green stock<small>Alert below 5 kg</small></th><th scope="col">Rested<small>Meets café rest policy</small></th><th scope="col">Ready to ship<small>Packed · dispatch eligible</small></th></tr></thead><tbody>${rows.map(r=>`<tr><th scope="row"><b>${esc(r.name)}</b><small>${r.profiles.map(c=>esc(c.name)+' · '+esc(c.profile)).join('<br>')||esc(r.origin)||'No linked roast profiles'}</small></th><td data-label="Green stock" class="${r.green_mg!==null&&r.green_mg<5000000?'low-stock':''}">${r.is_blend?'<b>Blend recipe</b><small>Green stock tracked by ingredient</small>':r.green_mg===null?'<span class="unknown-stock">—</span><small>Green bean not linked</small>':`<b>${kg(r.green_mg)}</b>${r.green_mg<5000000?badge(r.green_mg<0?'Check stock balance':'Low stock','red'):''}`}</td><td data-label="Rested"><b>${kg(r.rested_mg)}</b></td><td data-label="Ready to ship"><b>${kg(r.ship_mg)}</b></td></tr>`).join('')}</tbody></table></div><div class="dashboard-note">Rested and ready-to-ship quantities may overlap and include allocated stock. Ready to ship uses bag net weight; held, archived and out-of-policy coffee is excluded from both.</div>`:empty('No beans yet','Add green beans and link roast profiles to see your stock here.')}</section>`;
}

function floorPanel(id,rows,h){
  const {esc,grams,badge,empty,btn}=h,visible=rows.filter(r=>r[id+'_mg']>0);
  return `<section class="panel floor-panel" aria-labelledby="${id}-stock-title"><div class="panel-heading"><div><span class="eyebrow">${id==='cafe'?'BEHIND THE BAR':'ON THE SHELF'}</span><h2 id="${id}-stock-title">${id==='cafe'?'Café stock':'Retail stock'}</h2></div><a href="#stock">View stock ↗</a></div>
    ${visible.length?`<ul class="bean-stock-list">${visible.map(r=>`<li><div><b>${esc(r.name)}</b><small>${r.profiles.map(c=>esc(c.profile)).filter((p,i,a)=>a.indexOf(p)===i).join(' · ')||'No roast profile'}${id==='wall'?` · ${r.wall_bags} ${r.wall_bags===1?'bag':'bags'}${r.wall_bulk_mg?' · '+grams(r.wall_bulk_mg)+' bulk':''}`:''}</small>${r[id+'_held_mg']?badge(grams(r[id+'_held_mg'])+' held / archived','red'):''}</div><strong>${grams(r[id+'_mg'])}</strong></li>`).join('')}</ul>`:empty(id==='cafe'?'No café stock':'No retail stock','Transfer coffee here to see a breakdown by bean.')}
    <div class="floor-panel-footer"><p>Physical stock · includes allocations, overfill and held coffee</p><div class="quick-actions">${id==='cafe'?btn('Record usage','quick-use'):btn('Record sale','quick-sale')}${btn('Count stock','quick-count',{location:id})}</div></div></section>`;
}

export function todayPage(S,h){
  const rows=beanOverview(S);
  return h.heading('THE DAILY BRIEF','Today at the roastery.','What to roast, and what’s on hand.',h.btn('+ Record a roast','new-batch',{},'primary'))+
    `<div class="today-dashboard">${coffeeRoastPanel(S,h)}${beansPanel(rows,h)}<div class="today-floor">${floorPanel('cafe',rows,h)}${floorPanel('wall',rows,h)}</div></div>`;
}
