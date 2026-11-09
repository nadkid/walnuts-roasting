import {recipeSelect} from './blend-view.js';
// Pending source roasts share the batch list but cannot be used as stock yet.
export function roastBatchesPage(S,h){
 const {heading,btn,esc,date,grams,badge,empty}=h;
 const combined=[...S.batches,...(S.pending_roasts||[]).map(r=>({...r,pending:true}))].sort((a,b)=>String(b.roasted_at||'').localeCompare(String(a.roasted_at||'')));
 return heading('FROM THE ROASTER','Every roast has a story.','Measured output, applied rest policy and a complete movement trail.',btn('Import CSV','csv')+btn('+ Record a roast','new-batch',{},'primary'))+`<section class="panel"><div class="table-wrap"><table><thead><tr><th>Batch / coffee</th><th>Roast date</th><th>Green → roasted</th><th>Yield</th><th>Remaining</th><th>Café readiness</th><th></th></tr></thead><tbody>${combined.map(b=>b.pending?pendingRow(b,S,h):`<tr><td><b>${esc(b.code)}</b><small>${esc(b.coffee)} · ${esc(b.profile)}</small>${b.blend?badge('Recipe v'+b.blend.version,'outline'):''}${b.stock_only?badge('Stock adjustment','outline'):b.history_only?badge('History / opening count','outline'):''}${b.external_id?badge('Imported','outline'):''}</td><td>${date(b.roasted_at,true)}</td><td>${b.stock_only?'Added without a roast':grams(b.green_mg)+' → '+grams(b.output_mg)}</td><td>${b.green_mg?(100*b.output_mg/b.green_mg).toFixed(1):'—'}%</td><td><b>${grams(b.remaining_mg)}</b></td><td>${badge(b.readiness.brew.label,b.held?'red':b.readiness.brew.eligible?'green':'amber')}<small>${date(b.readiness.brew.ready_at,true)}</small></td><td>${btn('View batch','batch-detail',{id:b.id},'small-btn')}</td></tr>`).join('')}</tbody></table></div>${!combined.length?empty('Your first batch starts here','Use actual roasted output, not the green charge weight.'):''}</section>`
}
function pendingRow(r,S,h){const {esc,date,grams,badge,btn,admin}=h,coffee=S.coffees.find(c=>c.id===r.coffee_id);
 return `<tr class="roast-needs-info"><td><b>Imported roast · ${esc(r.external_id)}</b><small>${coffee?esc(coffee.name)+' · '+esc(coffee.profile):'Bean not assigned'}</small>${badge('Needs information','red')}<small>${r.missing.map(esc).join('<br>')}</small></td><td>${r.roasted_at?date(r.roasted_at,true):'Date missing'}</td><td>${r.green_mg?grams(r.green_mg):'Input missing'} → ${r.output_mg?grams(r.output_mg):'Output missing'}</td><td>${r.green_mg&&r.output_mg?(100*r.output_mg/r.green_mg).toFixed(1)+'%':'—'}</td><td>Awaiting completion</td><td>${badge('Complete details first','red')}</td><td>${admin()?btn('Add missing information','complete-imported-roast',{id:r.external_id},'small-btn'):'<small>Ask an administrator to complete</small>'}</td></tr>`;
}
export function completeRoastForm(r,S,h){
 const {modal,notice,esc,select,options,field,area,localInput,clock,api,iso}=h;
 modal('Complete imported roast',notice('Source roast: '+esc(r.external_id)+'<br>'+r.missing.map(esc).join('<br>'))+
 select('Bean / roast profile','coffee_id',options(S.coffees.filter(c=>!c.archived||c.id===r.coffee_id).map(c=>[c.id,c.name+' · '+c.profile]),r.coffee_id||'',true))+
 field('Roasted at (JST)','roasted_at','datetime-local',localInput(r.roasted_at),'required max="'+localInput(clock())+'"')+
 field('Measured green input (g)','green_g','number',r.green_mg?r.green_mg/1000:'','required min="0.001" step="0.001"')+
 field('Measured roasted output (g)','output_g','number',r.output_mg?r.output_mg/1000:'','required min="0.001" step="0.001"')+
 (r.bean_id?select('Bean mapping','map_bean',options([['yes','Also map this source bean for future imports'],['no','Assign this roast only']],S.blends?.profiles.some(p=>p.coffee_id===r.coffee_id)?'no':'yes'))+notice('Source bean ID: '+esc(r.bean_id)):notice('The source has no bean ID. Your selection applies to this roast only.'))+
 recipeSelect(S,h)+area('Completion / correction note','reason','','required maxlength="2000"')+
 notice('Once completed, eligible roasts add measured output to roasted stock and deduct green input from the linked bean. Roasts before your inventory cutover remain historical and require an opening count.'),
 (d,key)=>{if(!d.coffee_id)throw Error('Choose a bean / roast profile.');return api('roast-complete',{...d,external_id:r.external_id,source_version:r.source_version,roasted_at:iso(d.roasted_at),map_bean:d.map_bean==='yes'},key)},'Complete roast import');
}
