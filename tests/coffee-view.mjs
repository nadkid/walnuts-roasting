import assert from 'node:assert/strict';
import {coffeeSettings,coffeeVisibilityAction} from '../static/coffee-view.js';
const S={coffees:[{id:'active',name:'Active coffee',profile:'Filter',brew_days:2,fresh_days:30},{id:'old',name:'Old coffee',profile:'Filter',archived:1}]};
const H={esc:String,btn:(label,action)=>`<button data-action="${action}">${label}</button>`,badge:String,empty:String,admin:()=>true};
const html=coffeeSettings(S,H);assert.ok(html.includes('Delete coffee'));assert.ok(html.includes('Deleted coffees (1)'));assert.ok(html.includes('Restore'));assert.ok(html.indexOf('Old coffee')>html.indexOf('Deleted coffees'));
assert.ok(!coffeeSettings(S,{...H,admin:()=>false}).includes('<button'));
let submit,data;
await coffeeVisibilityAction({action:'coffee-delete',id:'active'},S,{...H,notice:String,modal:(title,body,fn)=>{submit=fn},api:(route,payload)=>{data=payload}});await submit({},'key');assert.equal(data.archived,true);assert.equal(data.id,'active');
console.log('Coffee delete, deleted list, restore controls and permissions passed.');
