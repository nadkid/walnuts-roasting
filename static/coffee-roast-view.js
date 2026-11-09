let expandedCoffee=null;

export function bindCoffeeRoast(S,h){
 document.querySelectorAll('[data-roast-coffee]').forEach(button=>button.onclick=()=>{
  const id=button.dataset.roastCoffee;
  expandedCoffee=expandedCoffee===id?null:id;
  h.draw();
  const tile=document.querySelector(`[data-roast-coffee="${CSS.escape(id)}"]`);
  tile?.focus({preventScroll:true});
  (expandedCoffee?document.getElementById('coffee-roast-detail'):tile)?.scrollIntoView({block:'nearest',behavior:'smooth'});
 });
 document.querySelector('[data-close-roast-detail]')?.addEventListener('click',()=>{
  const id=expandedCoffee;expandedCoffee=null;h.draw();
  document.querySelector(`[data-roast-coffee="${CSS.escape(id)}"]`)?.focus();
 });
}

function orderDetail(coffee,h){
 const {esc,grams,date}=h;
 return `<section id="coffee-roast-detail" class="coffee-roast-detail" aria-label="${esc(coffee.name+' '+coffee.profile+' order details')}">
  <div class="coffee-roast-detail-heading"><div><span class="eyebrow">CUSTOMER ORDERS</span><h3>${esc(coffee.name)} <span>${esc(coffee.profile)}</span></h3></div><button class="icon-btn" data-close-roast-detail aria-label="Close coffee details">×</button></div>
  ${coffee.orders.length?`<div class="coffee-order-list">${coffee.orders.map(o=>`<div class="coffee-order-row"><div><button class="coffee-order-link" data-action="today-order" data-id="${esc(o.id)}">${esc(o.number)} <span>↗</span></button><small>${o.due_at?'Due '+date(o.due_at,true)+' JST':'Deadline needed'}${o.source==='wholesale'?' · Wholesale':''}</small></div><div class="coffee-order-quantity"><b>${o.roast_mg===null?'Set deadline':o.roast_mg?grams(o.roast_mg)+' to roast':'Stock covered'}</b><small>${o.quantities.map(q=>q.units+' × '+grams(q.unit_mg)).join(' · ')}</small></div></div>`).join('')}</div>`:'<p class="coffee-roast-clear">No unfulfilled customer orders for this coffee.</p>'}
  ${coffee.roast_mg?`<div class="coffee-roast-estimate"><div><span>Approx. green charge</span><b>${grams(coffee.green_mg)}</b></div>${coffee.scheduled_mg?`<p>${grams(coffee.scheduled_mg)} scheduled${coffee.unplanned_mg?' · '+grams(coffee.unplanned_mg)+' still to schedule':''}</p>`:''}${coffee.blend_components?.length?`<p class="coffee-roast-mix">${coffee.blend_components.map(i=>esc(i.name)+' '+grams(i.quantity_mg)).join(' · ')}</p>`:''}</div>`:''}
  ${coffee.notes?.length?`<div class="coffee-roast-notes">${coffee.notes.map(esc).join('<br>')} <a href="#orders">Review orders →</a></div>`:''}
  ${coffee.roast_mg?`<div class="coffee-roast-detail-footer"><span>Net roasted weight · suitable stock deducted</span><a href="#plan">Open roast plan →</a></div>`:''}
 </section>`;
}

export function coffeeRoastPanel(S,h){
 const {esc,grams,date,empty}=h,summary=S.customer_roast;
 if(!summary)return `<section class="panel coffee-roast-panel"><div class="panel-heading"><h2>Coffee to roast</h2></div><p class="padded">Reload to see the customer-order roast summary.</p></section>`;
 const selected=summary.coffees.find(c=>c.coffee_id===expandedCoffee);
 return `<section class="panel coffee-roast-panel" aria-labelledby="coffee-roast-title"><div class="panel-heading"><div><span class="eyebrow">THE ROASTER’S WORK LIST</span><h2 id="coffee-roast-title">Coffee to roast</h2><p>Customer orders · after available stock</p></div><a href="#orders">All orders ↗</a></div>
  ${summary.coffees.length?`<div class="coffee-roast-grid">${summary.coffees.map(c=>{
   const active=c.coffee_id===expandedCoffee;
   const amount=c.unknown_lines?(c.roast_mg?'≥ '+grams(c.roast_mg):'—'):grams(c.roast_mg);
   const deadline=c.roast_by?'Roast by '+date(c.roast_by,true)+' JST':c.due_at?'Next dispatch '+date(c.due_at,true)+' JST':c.orders.length?'Add an order deadline':'No customer orders';
   return `<button class="coffee-roast-tile ${active?'is-expanded':''}" data-roast-coffee="${esc(c.coffee_id)}" aria-expanded="${active}" ${active?'aria-controls="coffee-roast-detail"':''} aria-label="${esc(c.name+' · '+c.profile+' · '+amount+' to roast · '+c.status)}"><span class="coffee-roast-tile-header status-${c.tone}"><span class="coffee-roast-name">${esc(c.name)}<small>${esc(c.profile)}</small></span><span class="coffee-roast-state">${esc(c.status)}</span></span><span class="coffee-roast-tile-body"><span class="coffee-roast-weight">${esc(amount)}</span><span class="coffee-roast-weight-label">${c.unknown_lines&&!c.roast_mg?'Deadline needed':'still to roast'}${c.scheduled_mg?' · '+grams(c.scheduled_mg)+' scheduled':''}</span><span class="coffee-roast-deadline">${esc(deadline)}</span><span class="coffee-roast-tile-footer"><span>${c.orders.length} ${c.orders.length===1?'order':'orders'}</span><span>${active?'Hide':'View'} details <span class="coffee-roast-chevron" aria-hidden="true">${active?'−':'+'}</span></span></span></span></button>`;
  }).join('')}</div>`:empty('No coffees in your lineup','Add a coffee in Settings to build your roast work list.')}
  ${selected?orderDetail(selected,h):''}
  ${summary.unmapped_orders?`<div class="coffee-roast-review">${summary.unmapped_orders} ${summary.unmapped_orders===1?'order needs':'orders need'} a product mapping before roasting quantities can be calculated. <a href="#orders">Review orders →</a></div>`:''}
 </section>`;
}
