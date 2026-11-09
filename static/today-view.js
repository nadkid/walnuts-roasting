// Today is a read-only view of the same orders, policies and physical stock.
const DAY=86400000;
const tokyoDay=s=>new Date(Date.parse(s)+9*3600000).toISOString().slice(0,10);
const validDate=s=>s&&Number.isFinite(Date.parse(s));
const sum=(items,key)=>items.reduce((n,item)=>n+(item[key]||0),0);
const pretty=s=>String(s||'Not supplied').toLowerCase().replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());

export function upcomingDeadlines(orders,clock){
  const open=orders.filter(o=>!o.cancelled&&!o.closed_at&&o.wholesale?.status!=='DRAFT'&&o.lines.some(l=>l.unfulfilled>0));
  const dated=open.filter(o=>validDate(o.due_at)).sort((a,b)=>Date.parse(a.due_at)-Date.parse(b.due_at)||String(a.number).localeCompare(String(b.number),'en',{numeric:true}));
  const next=dated[0];
  return {
    due_at:next?.due_at,
    orders:next?dated.filter(o=>tokyoDay(o.due_at)===tokyoDay(next.due_at)):[],
    missing:open.filter(o=>!validDate(o.due_at)).length,
    overdue:dated.filter(o=>Date.parse(o.due_at)<Date.parse(clock)).length
  };
}

export function productionPriorities(rows){
  return rows.filter(r=>r.shortage_mg>0||r.warnings.length).sort((a,b)=>{
    const at=Date.parse(a.latest_roast_at||a.due_at),bt=Date.parse(b.latest_roast_at||b.due_at);
    return at-bt||Date.parse(a.due_at)-Date.parse(b.due_at);
  });
}

export function beanOverview(S){
  const coffees=new Map(S.coffees.map(c=>[c.id,c]));
  const rows=(S.green?.beans||[]).map(b=>({
    id:b.id,name:b.name,origin:b.origin,green_mg:b.quantity_mg,
    profiles:b.coffee_ids.map(id=>coffees.get(id)).filter(Boolean)
  }));
  const linked=new Set(rows.flatMap(r=>r.profiles.map(c=>c.id)));
  // Unlinked profiles remain visible; an unknown green balance is never zero.
  rows.push(...S.coffees.filter(c=>!linked.has(c.id)).map(c=>({id:'coffee:'+c.id,name:c.name,green_mg:null,profiles:[c]})));
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

function dueLabel(at,clock){
  if(Date.parse(at)<Date.parse(clock))return ['Overdue','red'];
  const days=Math.round((Date.parse(tokyoDay(at))-Date.parse(tokyoDay(clock)))/DAY);
  return days===0?['Due today','amber']:days===1?['Due tomorrow','amber']:['In '+days+' days','green'];
}

function deadlinesPanel(S,h){
  const {esc,date,btn,badge,empty,grams}=h;
  const d=upcomingDeadlines(S.orders,S.clock);
  const label=d.due_at?dueLabel(d.due_at,S.clock):null;
  return `<section class="panel upcoming-panel" aria-labelledby="upcoming-title">
    <div class="panel-heading"><div><span class="eyebrow">FIRST THINGS FIRST</span><h2 id="upcoming-title">Upcoming deadlines</h2></div><a href="#orders">All orders ↗</a></div>
    ${d.orders.length?`<div class="deadline-brief"><div><span class="deadline-caption">${label[1]==='red'?'Earliest outstanding deadline':'Next dispatch / pickup day'}</span><div class="deadline-date"><strong>${date(d.due_at)}</strong>${badge(...label)}</div></div><p><b>${d.orders.length} ${d.orders.length===1?'order':'orders'}</b><span>Fulfillment and production status below · JST</span></p></div>
    <div class="deadline-orders">${d.orders.map(o=>{
      const lines=o.lines.filter(l=>l.unfulfilled>0),units=sum(lines,'unfulfilled'),weight=sum(lines,'required_mg');
      const states=[...new Set(lines.map(l=>l.status))];
      const fulfillment=pretty(o.fulfillment),partial=/PARTIAL/i.test(o.fulfillment);
      return `<article class="deadline-order"><div class="deadline-order-main"><h3>${esc(o.number)} ${badge(o.source==='wholesale'?'Wholesale':'Shopify','outline')}</h3>${o.wholesale?.customer?.business?`<p class="deadline-customer">${esc(o.wholesale.customer.business)}</p>`:''}<p>${lines.map(l=>esc(l.title)+' × '+l.unfulfilled).join('<br>')}</p></div><div class="deadline-order-status"><span class="deadline-caption">Fulfillment</span>${badge(fulfillment,partial?'amber':'outline')}<div class="production-states">${states.map(s=>badge(s,s==='Packed / allocated'?'green':/risk|mapping|split-bag/i.test(s)?'red':'amber')).join('')}</div></div><div class="deadline-order-due"><span class="deadline-caption">Due ${date(o.due_at,true)} JST</span><b>${units} ${units===1?'item':'items'} remaining${weight?' · '+grams(weight):''}</b>${btn('View order →','today-order',{id:o.id},'small-btn')}</div></article>`;
    }).join('')}</div>`:empty('No upcoming order deadlines','Orders with a dispatch or pickup date will appear here.')}
    ${d.missing||d.overdue?`<div class="dashboard-note">${[d.overdue?`${d.overdue} overdue ${d.overdue===1?'order needs':'orders need'} attention.`:'',d.missing?`${d.missing} open ${d.missing===1?'order needs a deadline':'orders need deadlines'}.`:''].filter(Boolean).join(' ')} <a href="#orders">Review orders →</a></div>`:''}
  </section>`;
}

function prioritiesPanel(S,h){
  const {esc,date,btn,badge,empty,grams}=h,rows=productionPriorities(S.planner.rows);
  return `<section class="panel today-priorities" aria-labelledby="priorities-title"><div class="panel-heading"><div><span class="eyebrow">WHAT TO ROAST NEXT</span><h2 id="priorities-title">Production priorities</h2><p>${rows.length?`Top ${Math.min(rows.length,3)} of ${rows.length} requirements · Earliest roast deadline first`:'Your dated requirements are covered'}</p></div><a href="#plan">Full roast plan ↗</a></div>
    ${rows.length?rows.slice(0,3).map(r=>{
      const late=r.warnings.some(w=>w.includes('passed'));
      return `<article class="today-priority"><div class="roast-deadline ${late?'is-late':''}"><span class="deadline-caption">Roast by · JST</span><strong>${r.latest_roast_at?date(r.latest_roast_at,true):'Set rest policy'}</strong>${badge(late?'Deadline at risk':r.shortage_mg?'Needs coverage':'Review policy',late?'red':'amber')}</div><div class="today-priority-main"><h3>${esc(r.coffee)} <span>${esc(r.profile)}</span></h3><p>${esc(r.label)} · ${r.channel==='brew'?'Café brewing':r.channel==='dispatch'?'Order dispatch':'Retail replenishment'}</p><b class="requirement-due">Due ${date(r.due_at,true)} JST</b>${r.warnings.filter(w=>!w.includes('passed')).map(w=>`<small>${esc(w)}</small>`).join('')}</div><div class="priority-quantity"><b>${r.shortage_mg?grams(r.shortage_mg)+' short':'Stock covered'}</b>${r.shortage_mg?btn('Review roast','suggestion',{id:r.id},'small-btn'):'<a href="#plan">Review plan →</a>'}</div></article>`;
    }).join(''):empty('A clear production queue','Review the roast plan to add café forecasts, retail targets or order deadlines.')}
    ${rows.length>3?`<a class="panel-link" href="#plan">View ${rows.length-3} more ${rows.length-3===1?'priority':'priorities'} →</a>`:''}</section>`;
}

function beansPanel(rows,h){
  const {esc,kg,badge,empty}=h;
  return `<section class="panel bean-overview" aria-labelledby="beans-title"><div class="panel-heading"><div><span class="eyebrow">FROM GREEN TO DISPATCH</span><h2 id="beans-title">Bean overview</h2><p>One balance per bean, across its roast profiles and locations.</p></div><a href="#green">Manage green beans ↗</a></div>
    ${rows.length?`<div class="table-wrap"><table><thead><tr><th scope="col">Bean / roast profiles</th><th scope="col">Green stock<small>Alert below 5 kg</small></th><th scope="col">Rested<small>Meets café rest policy</small></th><th scope="col">Ready to ship<small>Packed · dispatch eligible</small></th></tr></thead><tbody>${rows.map(r=>`<tr><th scope="row"><b>${esc(r.name)}</b><small>${r.profiles.map(c=>esc(c.name)+' · '+esc(c.profile)).join('<br>')||esc(r.origin)||'No linked roast profiles'}</small></th><td data-label="Green stock" class="${r.green_mg!==null&&r.green_mg<5000000?'low-stock':''}">${r.green_mg===null?'<span class="unknown-stock">—</span><small>Green bean not linked</small>':`<b>${kg(r.green_mg)}</b>${r.green_mg<5000000?badge(r.green_mg<0?'Check stock balance':'Low stock','red'):''}`}</td><td data-label="Rested"><b>${kg(r.rested_mg)}</b></td><td data-label="Ready to ship"><b>${kg(r.ship_mg)}</b></td></tr>`).join('')}</tbody></table></div><div class="dashboard-note">Rested and ready-to-ship quantities may overlap and include allocated stock. Ready to ship uses bag net weight; held, archived and out-of-policy coffee is excluded from both.</div>`:empty('No beans yet','Add green beans and link roast profiles to see your stock here.')}</section>`;
}

function floorPanel(id,rows,h){
  const {esc,grams,badge,empty,btn}=h,visible=rows.filter(r=>r[id+'_mg']>0);
  return `<section class="panel floor-panel" aria-labelledby="${id}-stock-title"><div class="panel-heading"><div><span class="eyebrow">${id==='cafe'?'BEHIND THE BAR':'ON THE SHELF'}</span><h2 id="${id}-stock-title">${id==='cafe'?'Café stock':'Retail stock'}</h2></div><a href="#stock">View stock ↗</a></div>
    ${visible.length?`<ul class="bean-stock-list">${visible.map(r=>`<li><div><b>${esc(r.name)}</b><small>${r.profiles.map(c=>esc(c.profile)).filter((p,i,a)=>a.indexOf(p)===i).join(' · ')||'No roast profile'}${id==='wall'?` · ${r.wall_bags} ${r.wall_bags===1?'bag':'bags'}${r.wall_bulk_mg?' · '+grams(r.wall_bulk_mg)+' bulk':''}`:''}</small>${r[id+'_held_mg']?badge(grams(r[id+'_held_mg'])+' held / archived','red'):''}</div><strong>${grams(r[id+'_mg'])}</strong></li>`).join('')}</ul>`:empty(id==='cafe'?'No café stock':'No retail stock','Transfer coffee here to see a breakdown by bean.')}
    <div class="floor-panel-footer"><p>Physical stock · includes allocations, overfill and held coffee</p><div class="quick-actions">${id==='cafe'?btn('Record usage','quick-use'):btn('Record sale','quick-sale')}${btn('Count stock','quick-count',{location:id})}</div></div></section>`;
}

export function todayPage(S,h){
  const rows=beanOverview(S);
  return h.heading('THE DAILY BRIEF','Today at the roastery.','The next commitments, the production plan and every bean on hand.',h.btn('+ Record a roast','new-batch',{},'primary'))+
    `<div class="today-dashboard">${deadlinesPanel(S,h)}${prioritiesPanel(S,h)}${beansPanel(rows,h)}<div class="today-floor">${floorPanel('cafe',rows,h)}${floorPanel('wall',rows,h)}</div></div>`;
}
