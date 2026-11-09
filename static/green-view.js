// Shared green stock screen. Source profiles can share one physical green bean.
let filters={bean:'',kind:'',search:''};
const kilos=n=>new Intl.NumberFormat('en',{maximumFractionDigits:3}).format(n/1e6)+' kg';
const cash=(v,c)=>v==null?'Not recorded':new Intl.NumberFormat('en',{style:'currency',currency:c,maximumFractionDigits:c==='JPY'?0:2}).format(v);
const major=(v,c)=>v==null?null:v/(c==='JPY'?1:100);
const gramsFromKg=x=>(Number(x)*1000).toFixed(3);
function purchaseFields(h,currency,prefix='',required=false){
 const {field}=h;
 return `<fieldset class="green-purchase-fields wide"><legend>${prefix?'Purchase / received stock (optional)':'Purchase price & quantity'}</legend><p>${prefix?'Enter a quantity to save a linked purchase with this bean. Leave it blank to save the bean only. ':''}Enter either price per kg or the total price. Prices are kept per receipt for future costing.</p>`+
 field('Quantity received (kg)',prefix+'kg','number','',`${required?'required ':''}min="0.001" step="0.001"`)+
 field('Received at (JST)',prefix+'received_at','datetime-local',h.localInput(h.clock()),'required')+
 field('Price per kg ('+currency+')',prefix+'price_per_kg','number','','min="0" step="0.000001"')+
 field('Total purchase price ('+currency+')',prefix+'total','number','','min="0" step="'+(currency==='JPY'?'1':'0.01')+'"')+
 `<input type="hidden" name="${prefix}price_basis" value="total"><div class="notice" id="${prefix}price-preview">No price recorded yet. Blank prices remain unknown; enter 0 only for a free receipt.</div>`+
 field('Supplier',prefix+'supplier')+field('Invoice / reference',prefix+'reference')+field('Lot / bag reference',prefix+'lot')+h.area('Purchase notes',prefix+'reason')+'</fieldset>';
}
function bindPurchaseFields(h,currencyFor,prefix=''){
 const el=n=>document.querySelector('#modal [name="'+prefix+n+'"]'),qty=el('kg'),unit=el('price_per_kg'),total=el('total'),basis=el('price_basis');
 function update(){
  const currency=currencyFor(),precision=currency==='JPY'?0:2,q=Number(qty.value);
  unit.previousSibling.textContent='Price per kg ('+currency+')';total.previousSibling.textContent='Total purchase price ('+currency+')';total.step=precision?'0.01':'1';
  if(basis.value==='per_kg')total.value=unit.value!==''&&q>0?(Number(unit.value)*q).toFixed(precision):'';
  else unit.value=total.value!==''&&q>0?(Number(total.value)/q).toFixed(6).replace(/\.?0+$/,''):'';
  document.querySelector('#'+prefix+'price-preview').textContent=total.value!==''&&q>0?cash(Number(total.value),currency)+' for '+qty.value+' kg · '+cash(Number(total.value)/q,currency)+' / kg':'No price recorded yet. Blank prices remain unknown; enter 0 only for a free receipt.';
 }
 qty.oninput=update;unit.oninput=()=>{basis.value='per_kg';update()};total.oninput=()=>{basis.value='total';update()};
 return update;
}
function purchasePayload(x,h,prefix='',optional=false){
 if(optional&&x[prefix+'kg']===''){
  if(['price_per_kg','total','supplier','reference','lot','reason'].some(k=>x[prefix+k]))throw Error('Enter the quantity received to save these purchase details.');
  return null;
 }
 return {grams:gramsFromKg(x[prefix+'kg']),received_at:h.iso(x[prefix+'received_at']),...Object.fromEntries(['price_per_kg','price_basis','total','supplier','reference','lot','reason'].map(k=>[k,x[prefix+k]]))};
}
export function bindGreen(draw){document.querySelectorAll('[data-green-filter]').forEach(el=>el.onchange=()=>{filters[el.dataset.greenFilter]=el.value;draw()})}
function eventTable(events,S,h,allowReverse=false){const {esc,date,btn,badge}=h,reversed=new Set(S.green.events.filter(e=>e.reversal_of).map(e=>e.reversal_of));return `<div class="table-wrap"><table><thead><tr><th>Date (JST) / activity</th><th>Bean / source</th><th>Weight</th><th>Purchase price</th><th>Supplier / lot / reference</th><th>Recorded by / note</th>${allowReverse?'<th></th>':''}</tr></thead><tbody>${events.map(e=>{const b=S.green.beans.find(b=>b.id===e.bean_id);return `<tr><td><b>${date(e.effective_at,true)}</b><small>${esc(e.kind)}${reversed.has(e.id)?' · reversed':''}</small></td><td><b>${esc(b.name)}</b>${e.batch_code?`<small>${esc(e.batch_code)}</small>`:''}</td><td><b>${e.kind==='count'?'Count: ':e.delta_mg>0?'+':''}${kilos(e.kind==='count'?e.count_mg:e.delta_mg)}</b></td><td>${e.kind==='purchase'?cash(major(e.total_minor,b.currency),b.currency):'—'}${e.kind==='purchase'&&e.total_minor!=null?`<small>${cash(major(e.total_minor,b.currency)*1e6/e.delta_mg,b.currency)} / kg</small>`:''}</td><td>${esc(e.supplier)||'—'}<small>${esc([e.lot,e.reference].filter(Boolean).join(' · '))}</small></td><td>${esc(e.actor)}<small>${esc(e.reason)}</small></td>${allowReverse?`<td>${h.admin()&&e.kind==='purchase'&&!reversed.has(e.id)?btn('Reverse purchase','green-reverse',{id:e.id},'text-btn'):''}</td>`:''}</tr>`}).join('')}</tbody></table></div>`}
export function greenPage(S,h){const {esc,heading,btn,badge,options,empty,date}=h,g=S.green,beans=g.beans.filter(b=>(!filters.bean||b.id===filters.bean)&&(!filters.search||[b.name,b.origin,b.variety,b.process].some(v=>v.toLowerCase().includes(filters.search.toLowerCase())))),events=g.events.filter(e=>(!filters.bean||e.bean_id===filters.bean)&&(!filters.kind||e.kind===filters.kind));
 return heading('BEFORE THE ROAST','Green beans, accounted for.','Receive purchases, count your stock, and see what each roast uses.',btn('+ Add green bean','green-new')+btn('+ Record purchase','green-purchase',{},'primary'))+
 `<section class="metrics green-metrics"><article><span>Expected green stock</span><strong>${kilos(g.beans.reduce((a,b)=>a+b.quantity_mg,0))}</strong><small>${g.beans.length} beans · ${g.beans.filter(b=>b.quantity_mg<0).length} negative balances to review</small></article><article><span>Green needed for scheduled roasts</span><strong>${kilos(g.beans.reduce((a,b)=>a+b.planned_mg,0))}</strong><small>Plans become deductions only when roasted</small></article><article><span>Roasts awaiting a green link</span><strong>${g.unlinked.length}<em>batches</em></strong><small>Link the coffee profile to deduct its measured charge</small></article></section>`+
 `<div class="notice">Start with <b>Count stock</b> for the beans physically here now, then record new purchases as they arrive. Each roast uses its measured <b>green input</b>. Earlier roasts imported after a count are already covered by that count. Roast.World imports also need their bean-to-coffee mapping under Settings.</div>`+
 `<section class="panel"><div class="filters"><label>Bean<select data-green-filter="bean">${options([['','All beans'],...g.beans.map(b=>[b.id,b.name])],filters.bean)}</select></label><label>Find bean<input type="search" data-green-filter="search" value="${esc(filters.search)}" placeholder="Name, origin, variety…"></label></div><div class="table-wrap"><table><thead><tr><th>Green bean</th><th>Expected stock</th><th>Scheduled / after plans</th><th>Latest purchase price</th><th>Linked roast profiles</th><th></th></tr></thead><tbody>${beans.map(b=>`<tr><td><b>${esc(b.name)}</b><small>${esc([b.origin,b.variety,b.process].filter(Boolean).join(' · '))}</small></td><td><b>${kilos(b.quantity_mg)}</b>${b.quantity_mg<0?badge('Check receipts / count','red'):''}<small>${b.counted_at?'Last counted '+date(b.counted_at,true):'No physical count yet'}</small></td><td>${kilos(b.planned_mg)} scheduled<small>${kilos(b.after_plans_mg)} after plans ${b.after_plans_mg<0?'· shortfall':''}</small></td><td>${b.last_price_per_kg==null?'Not recorded':cash(b.last_price_per_kg,b.currency)+' / kg'}<small>${esc(b.currency)} · bean cost only</small></td><td>${b.coffee_ids.length?b.coffee_ids.map(id=>{const c=S.coffees.find(c=>c.id===id);return `<small>${esc(c.name)} · ${esc(c.profile)}</small>`}).join(''):badge('Link a profile','amber')}</td><td><div class="green-row-actions">${btn('Purchase','green-purchase',{id:b.id},'small-btn')}${btn('Count stock','green-count',{id:b.id},'small-btn')}${btn('Edit / link','green-edit',{id:b.id},'text-btn')}${btn('History','green-history',{id:b.id},'text-btn')}</div></td></tr>`).join('')}</tbody></table></div>${!beans.length?empty(g.beans.length?'No matching beans':'Add your first green bean','Create the bean, link its roast profiles, then enter an opening count or a received purchase.'):''}</section>`+
 (g.unlinked.length?`<section class="panel"><div class="panel-heading"><h2>Link these roast profiles to green stock</h2></div>${[...new Set(g.unlinked.map(b=>b.coffee_id))].map(id=>{const b=g.unlinked.find(b=>b.coffee_id===id);return `<div class="list-row"><div><b>${esc(b.coffee)} · ${esc(b.profile)}</b><small>${g.unlinked.filter(b=>b.coffee_id===id).length} roast(s) awaiting a green deduction</small></div>${btn('Add / link green bean','green-link',{coffee:id},'small-btn')}</div>`}).join('')}</section>`:'')+
 `<section class="panel"><div class="panel-heading"><div><span class="eyebrow">RECEIPTS & USAGE</span><h2>Green stock history</h2></div></div><div class="filters"><label>Activity<select data-green-filter="kind">${options([['','All activity'],['purchase','Purchases'],['roast','Roast deductions'],['count','Physical counts'],['reversal','Corrections']],filters.kind)}</select></label></div>${events.length?eventTable(events.slice(0,200),S,h):empty('No green stock activity yet')}<div class="table-foot">Showing ${Math.min(events.length,200)} of ${events.length} entries · Original records are kept for corrections · Full history available per bean and in the ledger export</div></section>`;
}
export function greenAction(d,S,h){const {esc,modal,field,select,area,notice,options,api,localInput,iso,clock,btn}=h,g=S.green;
 if(d.action==='green-link'){
  if(!g.beans.length)return greenAction({action:'green-new',coffee:d.coffee},S,h);
  const c=S.coffees.find(c=>c.id===d.coffee);
  modal('Link roast profile to green stock',notice(esc(c.name)+' · '+esc(c.profile)+'<br>Existing unlinked roasts will be deducted at their original roast time. Earlier roasts are already covered by any later physical count.')+select('Green bean in stock','bean_id',options(g.beans.map(b=>[b.id,b.name])))+`<div class="quick-actions"><button type="button" class="secondary" id="green-create-instead">+ Create a new green bean</button></div>`,(x,key)=>{const b=g.beans.find(b=>b.id===x.bean_id);return api('green-bean',{...b,coffee_ids:[...b.coffee_ids,d.coffee]},key)},'Link profile');
  document.querySelector('#green-create-instead').onclick=()=>greenAction({action:'green-new',coffee:d.coffee},S,h);return;
 }
 if(d.action==='green-new'||d.action==='green-edit'){
  const b=g.beans.find(b=>b.id===d.id)||{currency:'JPY',coffee_ids:d.coffee?[d.coffee]:[]};
  modal(b.id?'Edit green bean & roast links':'Add green bean & purchase',field('Bean name','name','text',b.name||'','required maxlength="200"')+select('Purchase currency','currency',options(['JPY','USD','EUR','GBP','AUD','CAD'].map(c=>[c,c]),b.currency))+
  purchaseFields(h,b.currency,'first_')+
  field('Origin / farm','origin','text',b.origin||'')+field('Variety','variety','text',b.variety||'')+field('Process','process','text',b.process||'')+area('Bean notes','notes',b.notes||'')+
  `<fieldset class="green-links wide"><legend>Roast profiles using this green bean</legend><p>All selected profiles draw from this one balance. Posted deductions keep their original bean if you change links later.</p>${S.coffees.filter(c=>(!c.archived||b.coffee_ids.includes(c.id))&&!(S.blends?.profiles||[]).some(p=>p.coffee_id===c.id)).map(c=>{const owner=g.beans.find(other=>other.id!==b.id&&other.coffee_ids.includes(c.id));return `<label><input type="checkbox" name="green_profile" value="${esc(c.id)}" ${b.coffee_ids.includes(c.id)?'checked':''} ${owner?'disabled':''}> <span>${esc(c.name)} · ${esc(c.profile)}${c.archived?' · deleted':''}${owner?`<small>Linked to ${esc(owner.name)}</small>`:''}</span></label>`}).join('')||'<p>Add roast profiles under Settings → Coffees first.</p>'}</fieldset>`,(x,key)=>{
   const purchase=purchasePayload(x,h,'first_',true);
   return api('green-bean',{...Object.fromEntries(['name','currency','origin','variety','process','notes'].map(k=>[k,x[k]])),...(b.id?{id:b.id,version:b.version}:{}),...(purchase?{purchase}:{}),coffee_ids:[...document.querySelectorAll('#modal [name=green_profile]:checked')].map(el=>el.value)},key)
  },'Save bean & purchase');
  const currency=document.querySelector('#modal [name=currency]'),update=bindPurchaseFields(h,()=>currency.value,'first_');currency.onchange=update;return;
 }
 if(d.action==='green-purchase'){
  if(!g.beans.length){greenAction({action:'green-new'},S,h);return}
  const b=g.beans.find(b=>b.id===d.id)||g.beans[0];
  modal('Record green-bean purchase',notice('Record beans physically received. Purchase costs stay linked to this bean and receipt. You can enter price per kg or a total; leave both blank only if the price is unknown.')+select('Green bean','bean_id',options(g.beans.map(b=>[b.id,b.name+' · '+b.currency]),b.id))+purchaseFields(h,b.currency,'',true),(x,key)=>api('green-purchase',{bean_id:x.bean_id,...purchasePayload(x,h)},key),'Receive purchase');
  const bean=document.querySelector('#modal [name=bean_id]'),update=bindPurchaseFields(h,()=>g.beans.find(b=>b.id===bean.value).currency);bean.onchange=update;return;
 }
 if(d.action==='green-count'){
  const b=g.beans.find(b=>b.id===d.id);
  modal('Count green stock · '+b.name,notice('Enter all of this bean physically here now. This sets the balance as of now; record usage with a count or a roast, so the same usage is not deducted twice.')+field('Actual remaining green beans (kg)','kg','number',Math.max(0,b.quantity_mg)/1e6,'required min="0" step="0.001"')+area('Count reason / location notes','reason','','required'),(x,key)=>api('green-count',{bean_id:b.id,version:b.version,grams:gramsFromKg(x.kg),reason:x.reason},key),'Save physical count');return;
 }
 if(d.action==='green-history'){
  const b=g.beans.find(b=>b.id===d.id);modal('Green stock history · '+b.name,notice(`Expected stock: <b>${kilos(b.quantity_mg)}</b>. Physical counts set a fresh baseline; late entries dated before a count remain in history.`)+eventTable(g.events.filter(e=>e.bean_id===b.id),S,h,true),null,'','large');document.querySelectorAll('#modal [data-action]').forEach(el=>el.onclick=()=>greenAction(el.dataset,S,h));return;
 }
 if(d.action==='green-reverse'){
  modal('Reverse green purchase',notice('Use this for a duplicated or incorrect receipt. The original purchase remains in history. Then enter the corrected purchase if needed.')+area('Correction reason','reason','','required'),(x,key)=>api('green-reverse',{event_id:Number(d.id),reason:x.reason},key),'Reverse purchase');return;
 }
}
