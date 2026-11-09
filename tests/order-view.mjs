import assert from 'node:assert/strict';
import {selectOrders,orderStatus} from '../static/order-view.js';
const orders=[
 {number:'#1256',created_at:'2026-11-03T00:00:00Z',due_at:null,cancelled:0,closed_at:null,payment:'PAID',fulfillment:'UNFULFILLED',lines:[{title:'Kiri',status:'Needs mapping'}]},
 {number:'#1237',created_at:'2026-10-05T10:00:00+09:00',due_at:'2026-11-10T00:00:00Z',cancelled:0,closed_at:'2026-10-06T00:00:00Z',payment:'PAID',fulfillment:'FULFILLED',lines:[{title:'Espresso',status:'Shopify fulfilled / removed'}]},
 {number:'#1238',created_at:'2026-10-05T02:00:00Z',due_at:'2026-11-08T00:00:00Z',cancelled:1,closed_at:null,payment:'REFUNDED',fulfillment:'FULFILLED',lines:[]},
 {number:'#1000',created_at:null,due_at:null,cancelled:0,closed_at:null,payment:'PENDING',fulfillment:'UNFULFILLED',lines:[]}
];
assert.deepEqual(selectOrders(orders,{sort:'oldest'}).map(o=>o.number),['#1237','#1238','#1256','#1000']);
assert.deepEqual(selectOrders(orders,{sort:'newest'}).map(o=>o.number),['#1256','#1238','#1237','#1000']);
assert.equal(selectOrders(orders,{sort:'due-first'})[0].number,'#1238');
assert.equal(selectOrders(orders,{status:'cancelled'})[0].number,'#1238');
assert.equal(selectOrders(orders,{status:'archived',payment:'PAID',fulfillment:'FULFILLED'})[0].number,'#1237');
assert.equal(selectOrders(orders,{production:'Needs mapping',search:'1256'})[0].number,'#1256');
assert.equal(selectOrders(orders,{payment:'PAID',search:'absent'}).length,0);
assert.equal(selectOrders(orders,{}).length,orders.length);assert.equal(orders[0].number,'#1256');
console.log('Order view: chronological/timezone sorting, combined status filters, empty results and non-mutating selection passed.');

const {orderAllocationStocks}=await import('../static/order-view.js');
const scope={coffee_id:'c',free_mg:100000,package_id:'bulk',location_id:'roastery',roasted_at:'2026-11-01T00:00:00Z'};
const stocks=[{...scope,id:'roastery-bulk'},{...scope,id:'roastery-packed',package_id:'p',roasted_at:'2026-11-02T00:00:00Z'},...['cafe','wall','packing'].map(location_id=>({...scope,id:location_id,location_id})),{...scope,id:'other-coffee',coffee_id:'other'},{...scope,id:'reserved',free_mg:0},{...scope,id:'wrong-size',package_id:'other-size'}];
assert.deepEqual(orderAllocationStocks(stocks,{coffee_id:'c',package_id:'p'}).map(s=>s.id),['roastery-bulk','roastery-packed']);
assert.equal(stocks.length,8,'choosing order stock does not mutate inventory');
console.log('Customer allocations offer only compatible free roastery stock.');
