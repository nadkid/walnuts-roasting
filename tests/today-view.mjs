import assert from 'node:assert/strict';
import {beanOverview,todayPage} from '../static/today-view.js';

const clock='2026-11-05T03:00:00Z';
const orders=[];
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
assert.equal(kiri.ship_mg,0,'ready to ship excludes floor stock and ineligible roastery stock');
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
assert(html.indexOf('Coffee to roast')<html.indexOf('Bean overview'));
assert(!html.includes('Upcoming deadlines')&&!html.includes('Production priorities'));
assert(html.indexOf('Bean overview')<html.indexOf('Café stock'));
assert(!html.includes('Connections & exceptions'));
assert(html.includes('Green bean not linked'));
const malicious=structuredClone(S);
malicious.green.beans[0].name='<img src=x onerror=alert(1)>';

const safe=todayPage(malicious,h);
assert(!safe.includes('<img src=x'));
assert(!safe.includes('<script>bad()'));
const blank=todayPage({clock,orders:[],planner:{rows:[]},stocks:[],coffees:[],green:{beans:[]}},h);
assert(blank.includes('Coffee to roast')&&blank.includes('No beans yet')&&blank.includes('No café stock')&&blank.includes('No retail stock'));
console.log('Today view: shared beans, stock policies, threshold, empty states and escaping passed.');

const deleted=structuredClone(S);deleted.coffees.push({id:'deleted',name:'Deleted unlinked coffee',profile:'Filter',archived:1});
deleted.coffees.push({id:'deleted-linked',name:'Deleted linked coffee',profile:'Filter',archived:1});
deleted.green.beans.push({id:'deleted-green',name:'Exhausted green bean',quantity_mg:0,coffee_ids:['deleted-linked']});
assert.ok(!beanOverview(deleted).some(r=>r.name==='Deleted unlinked coffee'||r.name==='Exhausted green bean'));
deleted.green.beans.find(b=>b.id==='deleted-green').quantity_mg=1000;
assert.ok(beanOverview(deleted).some(r=>r.name==='Exhausted green bean'),'new green stock remains visible');
const shared=structuredClone(S);shared.coffees.find(c=>c.id==='espresso').archived=1;
assert.deepEqual(beanOverview(shared).find(b=>b.id==='kiri').profiles.map(c=>c.id),['filter']);
console.log('Deleted coffees are hidden on Today; shared beans and returning green stock stay visible.');

const roasteryPacked=structuredClone(S);
roasteryPacked.stocks.push(stock('filter',200000,{location_id:'roastery',package_mg:100000,overfill_mg:2000,free_mg:0}));
assert.equal(beanOverview(roasteryPacked).find(b=>b.id==='kiri').ship_mg,200000,'ready-to-ship uses eligible roastery bag net weight, including reservations');
assert.equal(beanOverview(roasteryPacked).find(b=>b.id==='kiri').wall_mg,kiri.wall_mg,'retail totals retain their physical stock');
