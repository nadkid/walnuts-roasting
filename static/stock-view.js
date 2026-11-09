export const hasStock=s=>(s.quantity_mg||0)+(s.overfill_mg||0)>0;
export function compareStockAge(a,b){
  // Unknown roast dates remain visible but never jump ahead of dated batches.
  return (a.roasted_at||'9999').localeCompare(b.roasted_at||'9999')||String(a.code||'').localeCompare(String(b.code||''))||String(a.id).localeCompare(String(b.id));
}
export function selectStocks(stocks,f={},localInput=s=>s?s.slice(0,10):''){
  return stocks.filter(s=>(f.balance==='all'||hasStock(s))&&
    (!f.coffee||s.coffee_id===f.coffee)&&(!f.location||s.location_id===f.location)&&
    (!f.form||(f.form==='bulk'?s.package_id==='bulk':s.package_id!=='bulk'))&&
    (!f.reservation||(f.reservation==='reserved'?s.reserved_mg>0:s.free_mg>0))&&
    (!f.readiness||(f.readiness==='ready'?s.readiness[f.use||'brew'].eligible:!s.readiness[f.use||'brew'].eligible))&&
    (!f.date||localInput(s.roasted_at).slice(0,10)===f.date)).sort(compareStockAge);
}
export function stockActions(s,batch={},admin=false){
  const actions=[];
  if(s.free_mg>0){
    actions.push(['transfer','Transfer']);
    actions.push(s.package_id==='bulk'?['pack','Pack bags']:['unpack','Open bags into bulk']);
    if(s.package_id==='bulk'&&s.readiness.brew.eligible)actions.push(['consume','Café consumption']);
    if(s.package_id!=='bulk'&&s.readiness.retail.eligible)actions.push(['sale','Retail sale']);
    actions.push(['waste','Waste / samples']);
    if(s.roasted_at&&!s.held&&!s.archived)actions.push(['reserve','Reserve to demand']);
  }
  actions.push(['count','Count remaining']);
  if(batch.history_only&&!batch.stock_only)actions.push(['opening','Historical opening count']);
  if(admin&&s.held)actions.push(['return','Confirmed physical return']);
  return actions;
}
export function stockPage(S,h,f){
  const {heading,btn,options,esc,date,grams,badge,empty,localInput,readyLabel}=h;
  const ss=selectStocks(S.stocks,f,localInput),emptyCount=selectStocks(S.stocks,{...f,balance:'all'},localInput).filter(s=>!hasStock(s)).length;
  const batches=new Map(S.batches.map(b=>[b.id,b]));
  return heading('BATCH BY BATCH','Stock you can account for.','On-hand, reserved and free quantities. Oldest roast first.',btn('Count stock','count-stock-page')+btn('+ Add roasted stock','add-roasted-stock')+btn('+ Record a roast','new-batch',{},'primary'))+
  `<section class="panel"><div class="filters"><label>Balances<select data-filter="balance">${options([['on-hand','On hand only'],['all','Show empty too']],f.balance||'on-hand')}</select></label><label>Readiness for<select data-filter="use">${options([['brew','Café brewing'],['dispatch','Online dispatch'],['retail','Retail sale']],f.use)}</select></label><label>Coffee<select data-filter="coffee">${options([['','All coffees'],...S.coffees.map(c=>[c.id,c.name])],f.coffee)}</select></label><label>Location<select data-filter="location">${options([['','All locations'],...S.locations.map(l=>[l.id,l.name])],f.location)}</select></label><label>Form<select data-filter="form">${options([['','All forms'],['bulk','Bulk'],['bags','Packaged']],f.form)}</select></label><label>Allocation<select data-filter="reservation">${options([['','All stock'],['reserved','Reserved'],['free','Free available']],f.reservation)}</select></label><label>Readiness<select data-filter="readiness">${options([['','Any readiness'],['ready','Ready'],['other','Resting / held / exception']],f.readiness)}</select></label><label>Roast date<input type="date" data-filter="date" value="${esc(f.date)}"></label>${btn('Clear filters','clear-stock-filters',{},'small-btn')}</div>
  ${ss.length?`<div class="table-wrap"><table><thead><tr><th>Coffee / batch</th><th>Location & form</th><th>Roasted</th><th>On hand</th><th>Reserved net</th><th>Free net</th><th>Readiness</th><th></th></tr></thead><tbody>${ss.map(s=>`<tr><td><b>${esc(s.coffee)}</b><button class="cell-link" data-action="batch-detail" data-id="${esc(s.batch_id)}">${esc(s.code)}</button>${batches.get(s.batch_id)?.stock_only?badge('Stock adjustment','outline'):''}</td><td>${esc(s.location)}<small>${esc(s.form)}${s.package_mg?' · '+s.quantity_mg/s.package_mg+' bags':''}</small></td><td>${s.roasted_at?`${date(s.roasted_at)}<small>${Math.floor((new Date(S.clock)-new Date(s.roasted_at))/86400000)} days old</small>`:'Unknown<small>Review the batch to set its roast date</small>'}</td><td><b>${grams(s.quantity_mg+s.overfill_mg)}</b>${s.overfill_mg?`<small>Includes ${grams(s.overfill_mg)} measured overfill</small>`:''}${!hasStock(s)?badge('Empty','outline'):''}</td><td>${grams(s.reserved_mg)}</td><td><b>${grams(s.free_mg)}</b></td><td>${badge(s.readiness[f.use].label,s.readiness[f.use].eligible?'green':s.held?'red':'amber')}<small>${readyLabel(s.readiness[f.use])}${s.readiness[f.use].ready_at?'<br>'+date(s.readiness[f.use].ready_at,true):''}</small></td><td>${btn('Action ↓','stock-action',{id:s.id},'small-btn')}</td></tr>`).join('')}</tbody></table></div>`:empty('No matching stock','Add roasted stock, record a roast, or change the filters. Empty balances are available under “Show empty too”.')}
  <div class="table-foot">${ss.length} stock ${ss.length===1?'row':'rows'} · ${grams(ss.reduce((a,s)=>a+s.quantity_mg+s.overfill_mg,0))} on hand · ${f.balance==='all'?'Empty balances included':emptyCount+' empty '+(emptyCount===1?'balance':'balances')+' hidden'} · Batch history is retained</div></section>`;
}

export function addRoastedStockForm(S,h){
  const {modal,notice,select,field,area,options,esc,grams,date,localInput,iso,api}=h;
  if(!S.coffees.some(c=>!c.archived))return modal('Set up coffees first',notice('Add your coffee profiles and rest policies in Settings before adding roasted stock.'),null);
  const batches=S.batches.filter(b=>!b.archived);
  const batchOptions=[['','New / unrecorded batch'],...batches.map(b=>[b.id,`${b.code} · ${b.coffee} · ${date(b.roasted_at)} · ${grams(b.remaining_mg)} on hand`])];
  modal('Add roasted stock',notice('Record coffee that is already roasted. This adds to roasted inventory without recording production or deducting green beans. For a recount of stock already listed, use Count stock and enter its actual total instead.')+
    select('Batch','batch_id',options(batchOptions))+'<div class="stock-add-fields wide" id="stock-add-batch"></div>'+
    select('Location','location_id',options(S.locations.map(l=>[l.id,l.name]),'roastery'))+
    select('Stock form','package_id',options([['bulk','Bulk'],...S.packages.map(p=>[p.id,p.name+' · '+grams(p.weight_mg)])],'bulk'))+
    '<div class="stock-add-fields wide" id="stock-add-quantity"></div>'+area('Reason for adding stock (required)','reason','','required'),async(d,key)=>{
      const quantity=d.package_id==='bulk'?{grams:d.grams}:{units:d.units,overfill_g:d.overfill_g||0};
      const identity=d.batch_id?{batch_id:d.batch_id}:{coffee_id:d.coffee_id,code:d.code,roasted_at:iso(d.roasted_at)};
      await api('roasted-stock',{...identity,...quantity,location_id:d.location_id,package_id:d.package_id,reason:d.reason},key);
    },'Add to roasted stock');
  const dialog=document.querySelector('#modal'),batch=dialog.querySelector('[name=batch_id]'),form=dialog.querySelector('[name=package_id]');
  function renderBatch(){
    const b=batches.find(b=>b.id===batch.value);
    dialog.querySelector('#stock-add-batch').innerHTML=b?notice(`<b>${esc(b.coffee)} · ${esc(b.profile)}</b><br>Roasted ${b.roasted_at?date(b.roasted_at,true)+' JST':'date unknown'}. This keeps the existing batch’s rest rules${b.held?' and quality hold':''}.`):
      select('Coffee / profile','coffee_id',options(S.coffees.filter(c=>!c.archived).map(c=>[c.id,c.name+' · '+c.profile])))+
      field('Original roast date (JST, if known)','roasted_at','datetime-local','','max="'+localInput(S.clock)+'"')+
      field('Batch code (optional)','code')+notice('Leave the roast date blank if unknown. This stock will remain unavailable for brewing or dispatch until an administrator sets the date in the batch details.');
  }
  function renderQuantity(){
    dialog.querySelector('#stock-add-quantity').innerHTML=form.value==='bulk'?field('Additional roasted coffee found (g)','grams','number','','required min="0.001" step="0.001"'):
      field('Additional whole bags found','units','number','','required min="1" step="1"')+field('Total measured overfill in these bags (g, optional)','overfill_g','number','','min="0" step="0.001"');
  }
  batch.onchange=renderBatch;form.onchange=renderQuantity;renderBatch();renderQuantity();
}
