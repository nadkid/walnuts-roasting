// One set of status rules for the daily brief, orders and production plan.
const at=value=>value?Date.parse(value):NaN;
const past=(value,clock)=>Number.isFinite(at(value))&&at(value)<at(clock);
const health=(tone,label,reason)=>({tone,label,reason});
const attention=reason=>health('yellow','Needs attention',reason);
const coverageProblem=(row,S)=>{
  for(const allocation of row.allocations||[]){
    if(allocation.kind!=='planned')continue;
    if(allocation.batch==='Suggestion carryover')return 'Coverage depends on an unapproved roast suggestion.';
    const plan=S.plans?.find(p=>p.status==='planned'&&allocation.batch==='Plan '+p.id.slice(0,6));
    if(!plan||!Number.isFinite(at(plan.roast_at)))return 'Review the scheduled production covering this requirement.';
    if(past(plan.roast_at,S.clock))return 'A covering roast is overdue; record completion or reschedule it.';
  }
  return null;
};

export function orderHealth(order,S){
  const lines=order.lines||[],remaining=lines.filter(l=>l.unfulfilled>0);
  if(order.cancelled)return health('yellow','Cancelled','This order is no longer an active commitment.');
  if(order.wholesale?.status==='DRAFT')return health('yellow','Draft order','Confirm the wholesale order before production.');
  const needsPick=(S.fulfillments||[]).some(f=>f.order_id===order.id);
  if(order.fulfillment==='FULFILLED'||(lines.length&&!remaining.length))return needsPick?attention('Shipment confirmed; record the actual stock pick.'):health('green','Fulfilled','All items have been fulfilled.');
  if(order.closed_at)return attention('Archived order still has unfulfilled items.');
  if(past(order.due_at,S.clock))return health('red','Overdue','The dispatch or pickup deadline has passed.');
  if(needsPick)return attention('Shipment confirmed; record the actual stock pick.');
  if(!Number.isFinite(at(order.due_at)))return attention('Add a dispatch or pickup deadline.');
  if(!lines.length)return attention('Order line items are missing.');
  for(const line of remaining){
    if(line.kind==='noncoffee'||line.status==='Non-coffee')continue;
    if(line.status==='Needs allocation / roasting'){
      const row=S.planner?.rows?.find(r=>r.type==='line_id'&&r.id===line.id);
      if(row&&row.shortage_mg===0&&!row.warnings?.length){
        const problem=coverageProblem(row,S);
        if(problem)return attention(problem);
        continue;
      }
      return attention(row?.warnings?.[0]||'Allocate stock or schedule production for the remaining coffee.');
    }
    if(!['Packed / allocated','Ready to pack','Resting'].includes(line.status))return attention(line.status||'Review the missing order information.');
  }
  return health('green','On track','Stock or scheduled production covers this commitment.');
}

export function requirementHealth(row,S){
  const order=row.type==='line_id'?S.orders?.find(o=>o.lines.some(l=>l.id===row.id)):null;
  const orderState=order?orderHealth(order,S):null;
  if(orderState?.tone==='red'||orderState?.label==='Fulfilled')return orderState;
  if(!Number.isFinite(at(row.due_at)))return attention('Add a deadline for this requirement.');
  if(row.shortage_mg>0&&past(row.due_at,S.clock))return health('red','Overdue','The requirement deadline has passed with coffee still uncovered.');
  if(row.shortage_mg>0&&past(row.latest_roast_at,S.clock))return health('red','Roast deadline missed','The latest roast time has passed with coffee still uncovered.');
  if(row.warnings?.length)return attention(row.warnings[0]);
  if(row.shortage_mg>0)return health('yellow','Needs production','Roast or allocate coffee to cover this requirement.');
  if(orderState?.tone==='yellow')return orderState;
  const problem=coverageProblem(row,S);
  if(problem)return attention(problem);
  return health('green',row.allocations?.some(a=>a.kind==='planned')?'On track':'Covered','Stock or scheduled production covers this requirement.');
}

export function roastPlanHealth(plan,clock){
  if(!Number.isFinite(at(plan.roast_at)))return attention('Add a roast date and time.');
  return past(plan.roast_at,clock)?health('red','Roast overdue','The scheduled roast time has passed; record completion or reschedule.'):health('green','Scheduled','This roast is scheduled ahead of its deadline.');
}

export function statusSummary(state,esc){
  return `<div class="commitment-status"><strong>${esc(state.label)}</strong><span>${esc(state.reason)}</span></div>`;
}

export function statusLegend(){
  return '<div class="status-legend" aria-label="Status color guide"><span><i class="status-key-green"></i>On track / fulfilled</span><span><i class="status-key-yellow"></i>Needs attention</span><span><i class="status-key-red"></i>Overdue</span></div>';
}
