export function pendingShipments(shipments,S,h){
 if(!shipments.length)return '';
 const {esc,date,btn,admin}=h;
 return `<section class="panel"><div class="panel-heading commitment-header status-yellow"><div><h2>Confirmed shipments needing a physical pick</h2><p>Record the coffee shipped, or reconcile stock used before the dashboard.</p></div></div>${shipments.map(f=>`<div class="list-row"><div><b>${esc(S.orders.find(o=>o.id===f.order_id)?.number)}</b><small>${date(f.at,true)} JST · ${esc(f.id)}</small></div><div class="actions">${btn('Record actual pick','fulfillment',{id:f.id})}${admin()?btn('Shipped from pre-dashboard stock','shipment-historical',{id:f.id},'small-btn'):''}</div></div>`).join('')}</section>`;
}

export function shipmentHistory(order,h){
 const records=order.shipment_reconciliations||[];
 if(!records.length)return '';
 const {esc,date,btn,admin}=h;
 return `<details class="panel"><summary>Pre-dashboard stock · ${records.length} shipment${records.length===1?'':'s'}</summary>${records.map(r=>`<div class="list-row"><div><b>Shipped ${date(r.shipment_at,true)} JST</b><small>${esc(r.reason)}<br>Recorded by ${esc(r.actor)} · ${date(r.at,true)} JST · No stock deducted</small></div>${admin()?btn('Reopen stock pick','shipment-reopen',{id:r.fulfillment_id},'small-btn'):''}</div>`).join('')}</details>`;
}

export function shipmentReconciliationForm(f,S,h,reopen=false){
 const order=S.orders.find(o=>o.id===f.order_id);
 const {esc,date,modal,notice,area,api}=h;
 const title=reopen?'Reopen shipment stock pick':'Shipped from pre-dashboard stock';
 const explanation=reopen?'Return this shipment to the stock-pick reminders. This does not change stock.':'Use this when the shipment used coffee from before the dashboard and no batch record is available. This clears the stock-pick reminder without deducting current stock. Bean costs remain estimated or unknown where batch history is missing.';
 return modal(title,notice(`<b>${esc(order?.number)}</b> · Shipped ${date(f.shipment_at||f.at,true)} JST<br>${explanation}`)+area(reopen?'Reason for reopening':'Reconciliation note','reason','','required maxlength="2000"'),(x,key)=>api('fulfillment-reconcile',{fulfillment_id:f.fulfillment_id||f.id,action:reopen?'reopen':'pre_dashboard',reason:x.reason},key),reopen?'Reopen stock pick':'Confirm historical shipment');
}
