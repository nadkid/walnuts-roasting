import {beanOverview,floorPanel} from './today-view.js';
import {orderHealth,statusSummary} from './status-view.js';
import {compareStockAge} from './stock-view.js';

export const cafeRequests=S=>S.orders.filter(o=>o.source==='cafe');
export const requestOpen=o=>!o.cancelled&&!o.closed_at&&o.lines.some(l=>l.required_mg>0);
const lineQuantity=(l,h,total=false)=>l.request_form==='bulk'?h.kg(total?l.requested_mg:l.required_mg):`${total?l.quantity:l.unfulfilled} × ${h.grams(l.weight_mg)}`;

export function cafePage(S,h){
 const {heading,btn,esc,date,empty}=h,requests=cafeRequests(S),open=requests.filter(requestOpen).sort((a,b)=>a.due_at.localeCompare(b.due_at)),history=requests.filter(o=>!requestOpen(o)),rows=beanOverview(S);
 return heading('CAFÉ & RETAIL','Ready for the next service.','Stock on hand, and what the café needs next.',btn('+ New café request','cafe-new',{},'primary'))+
 `<div class="today-dashboard"><div class="today-floor">${floorPanel('cafe',rows,h)}${floorPanel('wall',rows,h)}</div><section class="panel"><div class="panel-heading"><div><span class="eyebrow">FROM THE ROASTERY</span><h2>Café requests</h2><p>${open.length} open · Ready to brew or sell by the requested date</p></div></div>${open.map(o=>{const health=orderHealth(o,S);return `<article class="commitment-card cafe-request"><header class="commitment-header status-${health.tone}"><div><h3>${esc(o.number)}</h3><p>Needed ${date(o.due_at,true)} JST</p></div>${statusSummary(health,esc)}</header><div class="cafe-request-body">${o.lines.filter(l=>l.required_mg>0).map(l=>`<div class="cafe-request-line"><div><b>${esc(S.coffees.find(c=>c.id===l.coffee_id)?.name)}</b><small>${l.request_form==='bulk'?'Bulk · Café brewing':'Bags · Retail shelf'}</small></div><strong>${lineQuantity(l,h)}</strong></div>`).join('')}<div class="actions">${btn('View in Orders','today-order',{id:o.id},'small-btn')}${btn('Edit request','cafe-edit',{id:o.id},'small-btn')}${btn('Record delivery','cafe-deliver',{id:o.id},'primary small-btn')}</div></div></article>`}).join('')||empty('Nothing requested yet','Request bulk coffee for the bar or bags for the retail shelf.')}</section>${history.length?`<details class="panel"><summary>Request history (${history.length})</summary>${history.slice().reverse().map(o=>`<div class="list-row"><div><b>${esc(o.number)}</b><small>${o.cancelled?'Cancelled':'Delivered'} · ${date(o.due_at,true)} JST</small></div>${btn('View in Orders','today-order',{id:o.id},'small-btn')}</div>`).join('')}</details>`:''}</div>`;
}

export function cafeRequestForm(order,S,h){
 const {modal,notice,select,field,area,options,esc,localInput,iso,api}=h;
 let counter=0;const saved={};
 const row=(l={})=>{
  const n=counter++;saved[n]=l.id;
  const coffees=S.coffees.filter(c=>!c.archived||c.id===l.coffee_id);
  return `<fieldset class="cafe-line" data-cafe-row="${n}"><div class="cafe-line-heading"><h3>Coffee ${n+1}</h3><button type="button" class="text-btn" data-remove-cafe="${n}">Remove</button></div>${select('Coffee / profile','coffee_'+n,options(coffees.map(c=>[c.id,c.name+' · '+c.profile]),l.coffee_id))}${select('Request as','form_'+n,options([['bulk','Bulk for café'],['bags','Retail bags']],l.request_form||'bulk'))}<div class="cafe-bulk-fields">${field('Weight (kg)','kg_'+n,'number',l.requested_mg?l.requested_mg/1e6:'','required min="0.001" step="0.001" placeholder="e.g. 4"')}</div><div class="cafe-bag-fields">${select('Bag size','package_'+n,options(S.packages.map(p=>[p.id,p.name+' · '+h.grams(p.weight_mg)]),l.package_id))}${field('Number of bags','quantity_'+n,'number',l.request_form==='bags'?l.quantity:'','required min="1" max="10000" step="1" placeholder="e.g. 3"')}</div>${l.delivered_mg?`<small>${h.grams(l.delivered_mg)} already delivered. Enter the total request, including delivered coffee.</small>`:''}</fieldset>`;
 };
 modal(order?'Edit café request':'New café request',notice('Request coffee from the roastery. Bulk must meet café brewing rest; bags must meet retail rest by the needed date.')+field('Needed at café by (JST)','due_at','datetime-local',localInput(order?.due_at),'required')+`<div class="cafe-request-lines">${(order?.lines||[{}]).map(row).join('')}</div><button type="button" class="secondary" id="add-cafe-line">+ Add another coffee</button>`+area('Notes (optional)','notes',order?.notes||'')+(order?'<button type="button" class="text-btn danger-text" id="cancel-cafe-request">Cancel this request</button>':''),async(x,key)=>{
  const lines=[...document.querySelectorAll('#modal [data-cafe-row]')].map(el=>{const n=el.dataset.cafeRow,form=x['form_'+n];return {...(saved[n]?{id:saved[n]}:{}),coffee_id:x['coffee_'+n],form,...(form==='bulk'?{kg:x['kg_'+n]}:{package_id:x['package_'+n],quantity:x['quantity_'+n]})}});
  await api('cafe-order',{...(order?{id:order.id,version:order.cafe.version}:{}),due_at:iso(x.due_at),notes:x.notes,lines},key);
 },order?'Save request':'Place café request','cafe-editor');
 const bind=()=>document.querySelectorAll('#modal [data-cafe-row]').forEach(el=>{
  const n=el.dataset.cafeRow,form=el.querySelector(`[name="form_${n}"]`);
  const update=()=>{for(const [selector,show] of [['.cafe-bulk-fields',form.value==='bulk'],['.cafe-bag-fields',form.value==='bags']]){const group=el.querySelector(selector);group.hidden=!show;group.querySelectorAll('input,select').forEach(input=>input.disabled=!show)}};
  form.onchange=update;update();el.querySelector('[data-remove-cafe]').onclick=()=>el.remove();
 });
 document.querySelector('#add-cafe-line').onclick=()=>{document.querySelector('.cafe-request-lines').insertAdjacentHTML('beforeend',row());bind()};bind();
 const cancel=document.querySelector('#cancel-cafe-request');if(cancel)cancel.onclick=()=>cafeCancelForm(order,h);
}

export function cafeCancelForm(order,h){
 h.modal('Cancel café request',h.notice(h.esc(order.number)+'<br>Cancel the remaining request and release its allocations. Coffee already delivered stays at the café or retail shelf.')+h.area('Reason','reason','','required'),(x,key)=>h.api('cafe-cancel',{order_id:order.id,version:order.cafe.version,reason:x.reason},key),'Cancel request');
}

export function cafeDeliveryStocks(S,line){
 return S.stocks.filter(s=>s.location_id==='roastery'&&s.coffee_id===line.coffee_id&&s.package_id===line.package_id&&s.free_mg+(S.reservations||[]).filter(r=>r.line_id===line.id&&r.stock_id===s.id).reduce((a,r)=>a+r.quantity_mg,0)>0).sort(compareStockAge);
}

export function cafeDeliveryForm(order,S,h){
 const {modal,notice,select,field,options,esc,grams,api}=h,lines=order.lines.filter(l=>l.required_mg>0),choices=[];
 const row=l=>{const n=choices.length;choices.push(l);return `<div class="cafe-pick-row"><h3>${esc(S.coffees.find(c=>c.id===l.coffee_id)?.name)} · ${lineQuantity(l,h)} remaining</h3>${select('Roastery batch','stock_'+n,options(cafeDeliveryStocks(S,l).map(s=>[s.id,`${s.code} · ${s.form} · ${s.readiness[l.use].label}`]),'',true))}${field(l.request_form==='bulk'?'Weight delivered (g)':'Bags delivered','amount_'+n,'number','0',`required min="0" step="${l.request_form==='bulk'?'0.001':'1'}"`)}</div>`};
 modal('Deliver café request · '+order.number,notice('Confirm the coffee actually moved: bulk goes to Café, retail bags to Retail wall. Stock must be ready for brewing or retail sale now. For bags, pack any bulk allocations in Orders first.')+`<div id="cafe-picks">${lines.map(row).join('')}</div><div class="quick-actions">${lines.map((l,i)=>`<button type="button" class="secondary" data-cafe-pick="${i}">+ Another batch · ${esc(S.coffees.find(c=>c.id===l.coffee_id)?.name)}</button>`).join('')}</div>`,async(x,key)=>{
  const picks=choices.flatMap((l,n)=>{const amount=x['amount_'+n];if(!Number(amount))return [];if(l.request_form==='bags'&&!Number.isInteger(Number(amount)))throw Error('Enter whole bags.');return [{line_id:l.id,stock_id:x['stock_'+n],grams:l.request_form==='bulk'?amount:Number(amount)*l.weight_mg/1000}]});
  await api('cafe-delivery',{order_id:order.id,version:order.cafe.version,picks},key);
 },'Confirm transfer','cafe-editor');
 document.querySelectorAll('[data-cafe-pick]').forEach(b=>b.onclick=()=>document.querySelector('#cafe-picks').insertAdjacentHTML('beforeend',row(lines[Number(b.dataset.cafePick)])));
}
