import assert from 'node:assert/strict';
import {money,day,dateRange,selectProfit,summarize,metricTotal,periods,csv,bucket,shippingSummary,setProfit,profitPage} from '../static/profit-view.js';
assert.equal(day('2026-11-07T15:00:00Z'),'2026-11-08');
assert.deepEqual(dateRange('30','2026-11-08'),['2026-10-10','2026-11-08']);
assert.deepEqual(dateRange('month','2026-11-08'),['2026-11-01','2026-11-08']);
assert.equal(bucket('2026-11-08','week'),'2026-11-02');
assert.equal(money(null),'—');assert.ok(money(1234,'USD').includes('12.34'));
const row={id:'1',currency:'JPY',source:'square',order_id:'o',number:'#1',coffee_id:'c',coffee:'Coffee',profile:'Filter',package_id:'p',sold_at:'2026-11-07T15:00:00Z',batches:['BATCH-1'],issues:[],status:'complete',net_units:1,net_sales_minor:1000,shipping_income_minor:0,bean_cost_minor:250,shipping_cost_minor:0,revenue_minor:1000,profit_minor:750};
const data=[row,{...row,id:'2',currency:'USD'}, {...row,id:'3',order_id:'other',sold_at:'2026-11-06T14:59:59Z'}, {...row,id:'4',coffee_id:'d',status:'incomplete',bean_cost_minor:null,profit_minor:null,issues:['Green purchase cost missing']}];
const f={currency:'JPY',from:'2026-11-08',to:'2026-11-08',group:'day'};
assert.equal(selectProfit(data,f).length,2);assert.equal(selectProfit(data,{...f,status:'complete'}).length,1);assert.equal(selectProfit(data,{...f,search:'batch-1'}).length,2);assert.equal(selectProfit(data,{...f,source:'shopify'}).length,0);
const s=summarize(selectProfit(data,f));assert.equal(s.net_sales_minor,2000);assert.equal(s.profit_minor,null);assert.equal(s.bean_cost_minor_known,250);assert.equal(s.complete,1);assert.equal(s.orders,1);
const ps=periods([row],{...f,from:'2026-11-07',to:'2026-11-09'});assert.equal(ps.length,3);assert.equal(ps[0].net_sales_minor,0);assert.equal(ps[1].profit_minor,750);assert.equal(ps[2].net_sales_minor,0);
const exported=csv([{...row,coffee:'=HYPERLINK("x")'},{...row,status:'incomplete',bean_cost_minor:null,profit_minor:null}]);assert.ok(exported.includes("'=HYPERLINK"));assert.ok(exported.includes('"750"'));assert.ok(exported.includes('"incomplete"'));assert.equal(exported.split('\r\n').length,3);
const H={esc:String,btn:(text)=>text};assert.equal(shippingSummary({can_record_shipping:false},H),'');assert.ok(shippingSummary({can_record_shipping:true,shipping:null},H).includes('Add shipping details'));assert.ok(shippingSummary({can_record_shipping:true,shipping:{mode:'pickup',currency:'JPY',parcels:[]}},H).includes('Pickup / no shipping cost'));
console.log('Profit date boundaries, filters, coverage, aggregation, CSV and shipping UI passed.');

// Render the whole screen with the historical mapping gaps that caused the crash.
const renderH={...H,options:()=>'',heading:()=>'',empty:()=>'',notice:String,badge:String,grams:String,date:String};
const state={clock:'2026-11-08T03:00:00Z',coffees:[],packages:[],sync:{}};
for(const names of [[null,'Coffee'],[undefined,'Coffee'],['','Coffee'],[null,null]]){
 const records=names.map((coffee,i)=>({...row,id:String(i),coffee_id:coffee?'c':null,coffee,profile:null,status:'incomplete',profit_minor:null,issues:['Product mapping needs review']}));
 setProfit({rows:records,currencies:['JPY'],generated_at:state.clock});
 const html=profitPage(state,renderH);
 assert.ok(html.includes('By bean'));assert.ok(html.includes('Sales detail'));assert.ok(html.includes('Unmapped bean'));assert.ok(html.includes('Needs information'));
 assert.equal(summarize(records).net_sales_minor,2000);
 assert.ok(csv(records).includes('Unmapped bean'));
}
console.log('Full profit-screen rendering passed with null, missing and empty bean names.');

setProfit({rows:[{...row,cost_basis:'estimated',cost_note:'Current green price / configured yield'}],currencies:['JPY'],generated_at:state.clock});
const estimatedHTML=profitPage(state,renderH);
assert.ok(estimatedHTML.includes('Estimated COGS'));assert.ok(estimatedHTML.includes('Includes estimates'));
assert.equal(selectProfit([{...row,cost_basis:'estimated'}],{...f,status:'estimated'}).length,1);
assert.ok(csv([{...row,cost_basis:'estimated',cost_note:'Current price'}]).includes('Current price'));
console.log('Estimated COGS labels, filter and CSV passed.');

// Each metric has its own coverage; margin uses exactly the profit-covered cohort.
const mixed=[
 {...row,id:'known',net_sales_minor:1000,shipping_income_minor:100,bean_cost_minor:200,shipping_cost_minor:50,revenue_minor:1100,profit_minor:850},
 {...row,id:'missing-sale',status:'incomplete',net_sales_minor:null,shipping_income_minor:50,bean_cost_minor:300,shipping_cost_minor:60,revenue_minor:null,profit_minor:null},
 {...row,id:'missing-cost',status:'incomplete',net_sales_minor:2000,shipping_income_minor:100,bean_cost_minor:null,shipping_cost_minor:null,revenue_minor:2100,profit_minor:null}
];
const partial=summarize(mixed);
assert.equal(partial.net_sales_minor,null,'a subtotal must not become a complete total');
assert.deepEqual(metricTotal(partial,'net_sales_minor'),{value:3000,known:2,missing:1,partial:true});
assert.deepEqual(metricTotal(partial,'bean_cost_minor'),{value:500,known:2,missing:1,partial:true});
assert.deepEqual(metricTotal(partial,'shipping_cost_minor'),{value:110,known:2,missing:1,partial:true});
assert.equal(metricTotal(partial,'shipping_income_minor').value,250);
assert.equal(metricTotal(partial,'profit_minor').value,850);
assert.equal(partial.covered_margin_pct,850/1100*100,'exclude revenue from lines without calculable profit');
const unknown={...row,status:'incomplete',...Object.fromEntries(['net_sales_minor','shipping_income_minor','bean_cost_minor','shipping_cost_minor','revenue_minor','profit_minor'].map(k=>[k,null]))};
assert.equal(metricTotal(summarize([unknown]),'shipping_cost_minor').value,null,'all unknown is not zero');
assert.equal(metricTotal(summarize([]),'shipping_cost_minor').value,0,'no sales is a known empty total');
assert.deepEqual(metricTotal(summarize([row,unknown]),'shipping_cost_minor'),{value:0,known:1,missing:1,partial:true},'a recorded zero remains a valid known amount');
const grouped=periods(mixed,{...f,group:'week'});assert.equal(grouped.length,1);assert.equal(metricTotal(grouped[0],'shipping_cost_minor').value,110);
setProfit({rows:mixed,currencies:['JPY'],generated_at:state.clock});
const partialHTML=profitPage(state,renderH);
const cardHTML=label=>partialHTML.slice(partialHTML.indexOf('<span>'+label),partialHTML.indexOf('</div>',partialHTML.indexOf('<span>'+label)));
assert.ok(cardHTML('Net bean sales').includes(money(3000)));assert.ok(cardHTML('Actual shipping cost').includes(money(110)));assert.ok(cardHTML('Gross profit').includes(money(850)));
assert.ok(cardHTML('Net bean sales').includes('Partial'));assert.ok(cardHTML('Net bean sales').includes('2 of 3 sale lines known'));
assert.ok(cardHTML('Gross profit').includes('77.3% margin on complete lines'));
assert.ok(partialHTML.includes('Partial · 2/3 lines'),'bean breakdown shows available amounts too');
assert.match(partialHTML,/class="profit-dot [^"]*partial/,'trend plots covered profit for a partial period');
assert.ok(partialHTML.includes('1 of 3 complete sale lines'));
assert.ok(partialHTML.includes('Shipping cost: '+money(110)+' (2 of 3 sale lines known)'));
setProfit({rows:[unknown],currencies:['JPY'],generated_at:state.clock});
const unknownHTML=profitPage(state,renderH);assert.ok(unknownHTML.includes('No amounts available'));assert.ok(unknownHTML.includes('no complete sale lines'));
const loss={...row,bean_cost_minor:1250,profit_minor:-250};setProfit({rows:[loss,unknown],currencies:['JPY'],generated_at:state.clock});
const lossHTML=profitPage(state,renderH);assert.match(lossHTML,/profit-stat profit-negative/);assert.ok(lossHTML.includes(money(-250)));
assert.ok(csv(mixed).includes('"incomplete"'));assert.equal(csv(mixed).split('\r\n').length,4,'CSV keeps the original sale lines and missing values');
console.log('Partial Profit totals: independent coverage, matched margin, unknown/zero/empty values, bean totals, charts, losses and CSV passed.');
