import assert from 'node:assert/strict';
import {upcomingDeadlines,productionPriorities,beanOverview,todayPage} from '../static/today-view.js';

const clock='2026-11-05T03:00:00Z';
const order=(id,due_at,extra={})=>({id,number:'#'+id,source:'shopify',due_at,cancelled:0,closed_at:null,fulfillment:'UNFULFILLED',lines:[{title:'Coffee',unfulfilled:1,required_mg:100000,status:'Ready to pack'}],...extra});
const orders=[
  order(1,'2026-11-06T00:00:00Z'),
  order(2,'2026-11-05T16:00:00Z'), // Same Tokyo day as order 1.
  order(3,'2026-11-07T03:00:00Z'),
  order(4,null),order(5,'invalid'),
  order(6,'2026-11-01T00:00:00Z',{cancelled:1}),
  order(7,'2026-11-01T00:00:00Z',{closed_at:clock}),
  order(8,'2026-11-01T00:00:00Z',{lines:[{unfulfilled:0}]}),
  order(9,'2026-11-01T00:00:00Z',{wholesale:{status:'DRAFT'}}),
];
let next=upcomingDeadlines(orders,clock);
assert.deepEqual(next.orders.map(o=>o.id),[2,1]);
assert.equal(next.missing,2);
assert.equal(next.overdue,0);
next=upcomingDeadlines([...orders,order(10,'2026-11-04T00:00:00Z')],clock);
assert.deepEqual(next.orders.map(o=>o.id),[10]);
assert.equal(next.overdue,1);
assert.deepEqual(upcomingDeadlines([],clock).orders,[]);
assert.equal(orders[0].id,1,'selection must not reorder source data');

const priorities=[
  {id:'later',shortage_mg:100,warnings:[],latest_roast_at:'2026-11-06T00:00:00Z',due_at:'2026-11-08T00:00:00Z'},
  {id:'first',shortage_mg:100,warnings:['Deadline at risk: latest roast slot has passed'],latest_roast_at:'2026-11-03T00:00:00Z',due_at:'2026-11-09T00:00:00Z'},
  {id:'covered',shortage_mg:0,warnings:[],due_at:'2026-11-02T00:00:00Z'},
  {id:'policy',shortage_mg:0,warnings:['Configure dispatch rest policy'],latest_roast_at:null,due_at:'2026-11-10T00:00:00Z'}
];
assert.deepEqual(productionPriorities(priorities).map(r=>r.id),['first','later','policy']);

const stock=(coffee_id,quantity_mg,extra={})=>({coffee_id,quantity_mg,overfill_mg:0,free_mg:quantity_mg,location_id:'roastery',package_id:'bulk',package_mg:0,readiness:{brew:{eligible:true},dispatch:{eligible:true}},...extra});
const S={clock,orders,planner:{rows:[]},coffees:[{id:'filter',name:'Kiri',profile:'Filter'},{id:'espresso',name:'Kiri espresso',profile:'Espresso'},{id:'unlinked',name:'Nagi',profile:'Filter'}],
  green:{beans:[{id:'kiri',name:'Kiri',quantity_mg:4999000,coffee_ids:['filter','espresso']},{id:'empty',name:'Empty',quantity_mg:0,coffee_ids:[]},{id:'exact',name:'At threshold',quantity_mg:5000000,coffee_ids:[]}]},
  stocks:[
    stock('filter',1000000), // Bulk is rested, but still needs packing.
    stock('espresso',400000,{location_id:'wall',package_mg:200000,overfill_mg:4000,free_mg:0}), // Allocated, still on hand.
    stock('filter',300000,{location_id:'cafe'}),
    stock('filter',200000,{location_id:'wall',package_mg:100000,held:1,readiness:{brew:{eligible:false},dispatch:{eligible:false}}}),
    stock('filter',100000,{archived:1,package_mg:100000,readiness:{brew:{eligible:false},dispatch:{eligible:false}}}),
    stock('espresso',100000,{package_mg:100000,readiness:{brew:{eligible:false},dispatch:{eligible:false}}}), // Still resting.
    stock('unlinked',100000,{location_id:'cafe'}),
    stock('espresso',50000,{location_id:'wall'}) // Unpacked retail stock remains visible, with no extra bag count.
  ]};
const before=JSON.stringify(S),beans=beanOverview(S),kiri=beans.find(b=>b.id==='kiri');
assert.equal(kiri.green_mg,4999000,'shared green stock is counted once');
assert.equal(kiri.rested_mg,1754000,'rested includes physical overfill and allocated stock, excludes ineligible stock');
assert.equal(kiri.ship_mg,400000,'ready to ship is eligible packed net weight, including allocations');
assert.equal(kiri.cafe_mg,300000);
assert.equal(kiri.wall_mg,654000);
assert.equal(kiri.wall_held_mg,200000);
assert.equal(kiri.wall_bags,4);
assert.equal(kiri.wall_bulk_mg,50000);
assert.equal(beans.find(b=>b.id==='coffee:unlinked').green_mg,null);
assert.equal(beans.find(b=>b.id==='empty').rested_mg,0);
assert.equal(JSON.stringify(S),before,'aggregation must not mutate state');

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const h={esc,kg:n=>n/1e6+' kg',grams:n=>n/1000+' g',date:s=>s||'Not set',btn:(label,action)=>`<button data-action="${action}">${label}</button>`,badge:(s,k)=>`<span class="badge ${k}">${esc(s)}</span>`,empty:(title,body)=>`<p>${esc(title)} ${esc(body)}</p>`,heading:(k,title)=>`<h1>${title}</h1>`};
const html=todayPage(S,h);
assert.equal((html.match(/class="low-stock"/g)||[]).length,2,'only below 5 kg is red, including zero');
assert(html.indexOf('Upcoming deadlines')<html.indexOf('Production priorities'));
assert(html.indexOf('Production priorities')<html.indexOf('Bean overview'));
assert(html.indexOf('Bean overview')<html.indexOf('Café stock'));
assert(!html.includes('Connections & exceptions'));
assert(html.includes('Green bean not linked'));
const malicious=structuredClone(S);
malicious.green.beans[0].name='<img src=x onerror=alert(1)>';
malicious.orders[1].lines[0].title='<script>bad()</script>';
const safe=todayPage(malicious,h);
assert(!safe.includes('<img src=x'));
assert(!safe.includes('<script>bad()'));
const blank=todayPage({clock,orders:[],planner:{rows:[]},stocks:[],coffees:[],green:{beans:[]}},h);
assert(blank.includes('No upcoming order deadlines')&&blank.includes('No beans yet')&&blank.includes('No café stock')&&blank.includes('No retail stock'));
console.log('Today view: Tokyo deadlines, overdue/undated orders, priority sorting, shared beans, stock policies, threshold, empty states and escaping passed.');
