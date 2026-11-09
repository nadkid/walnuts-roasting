import {compareStockAge} from './stock-view.js';
export const isOrderStock=s=>s.location_id==='roastery';
export function orderAllocationStocks(stocks,line){return stocks.filter(s=>isOrderStock(s)&&s.coffee_id===line.coffee_id&&s.free_mg>0&&['bulk',line.package_id].includes(s.package_id)).sort(compareStockAge)}
export function orderStatus(o){return o.cancelled?'cancelled':o.closed_at?'archived':'open'}
export function selectOrders(orders,f={}){
 const needle=(f.search||'').trim().toLowerCase();
 const result=orders.filter(o=>(!f.source||o.source===f.source)&&(!f.status||orderStatus(o)===f.status)&&(!f.fulfillment||o.fulfillment===f.fulfillment)&&(!f.payment||o.payment===f.payment)&&(!f.production||o.lines.some(l=>l.status===f.production))&&(!needle||[o.number,o.wholesale?.customer?.business,o.wholesale?.customer?.contact,o.wholesale?.reference,...o.lines.map(l=>l.title)].some(v=>String(v||'').toLowerCase().includes(needle))));
 const sort=f.sort||'newest',field=sort.startsWith('due')?'due_at':'created_at',direction=['oldest','due-first'].includes(sort)?1:-1;
 return result.sort((a,b)=>{
  const at=a[field]?Date.parse(a[field]):NaN,bt=b[field]?Date.parse(b[field]):NaN;
  if(Number.isFinite(at)&&Number.isFinite(bt)&&at!==bt)return direction*(at-bt);
  if(Number.isFinite(at)!==Number.isFinite(bt))return Number.isFinite(at)?-1:1;
  return direction*String(a.number).localeCompare(String(b.number),'en',{numeric:true});
 });
}
