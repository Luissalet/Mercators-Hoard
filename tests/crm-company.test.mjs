import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

test('company identity scopes native reads and an input change discards pending rows without rebuilding the draft', async () => {
  class Element {
    children=[];textContent='';hidden=false;disabled=false;listeners={};
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=nodes;}
    addEventListener(name,fn){this.listeners[name]=fn;}
  }
  const elements=new Map(), get=key=>{if(!elements.has(key))elements.set(key,new Element());return elements.get(key);};
  const filters=get('#crm-filters');
  filters.elements=Object.fromEntries(Object.entries({company_id:'',project:'IA',owner:'Ana',stage:'proposal',q:''}).map(([k,value])=>[k,{value,append(){}}]));
  const editor=get('#crm-editor'), draft={notes:'Unsaved company note ñ'};editor.children=[draft];
  const pending=[];
  const sandbox={window:{},location:{hash:'#crm'},URLSearchParams,FormData:class {
    constructor(form){this.form=form;}
    *[Symbol.iterator](){for(const [key,field] of Object.entries(this.form.elements))yield [key,field.value];}
  },document:{querySelector:()=>({querySelector:get,querySelectorAll:()=>[]}),createElement:()=>new Element()},
  fetch:url=>new Promise(resolve=>pending.push({url,resolve}))};
  vm.createContext(sandbox);
  const source=readFileSync(new URL('../static/crm.js',import.meta.url),'utf8');
  vm.runInContext(source.replace('  void work(load);', '  window.review={companyScope};'),sandbox);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  sandbox.window.review.companyScope({id:'company-A',name:'Homonym'});
  assert.equal(pending.length,2);
  for(const request of pending) {
    const q=new URL(request.url,'http://qa').searchParams;
    assert.equal(q.get('company_id'),'company-A');assert.equal(q.get('project'),'IA');assert.equal(q.get('owner'),'Ana');assert.equal(q.get('stage'),'proposal');
  }
  filters.elements.q.value='not found';filters.listeners.input();
  pending.shift().resolve({ok:true,json:async()=>({deals:[{title:'STALE'}],companies:[],deal_total:1,company_total:1})});
  pending.shift().resolve({ok:true,json:async()=>({note:'STALE',currencies:{}})});
  await flush();
  assert.equal(get('#crm-deals').children.length,0);assert.equal(get('#crm-summary').children.length,0);
  assert.match(get('#crm-message').textContent,/Pulsa Filtrar/);
  assert.strictEqual(editor.children[0],draft);
  sandbox.window.review.companyScope({id:'company-B',name:'Homonym'});
  assert.equal(get('#crm-company-id').textContent,'ID: company-B');
  assert.equal(get('#crm-company-name').textContent,'Homonym');
  for(const request of pending)assert.equal(new URL(request.url,'http://qa').searchParams.get('company_id'),'company-B');
  pending.shift().resolve({ok:true,json:async()=>({deals:[],companies:[],deal_total:0,company_total:0})});
  pending.shift().resolve({ok:true,json:async()=>({note:'Native summary',currencies:{}})});
  await flush();
  assert.match(get('#crm-deals').children[0].children[0].textContent,/esta empresa/);
  get('#crm-all-companies').onclick();
  for(const request of pending){const q=new URL(request.url,'http://qa').searchParams;assert.equal(q.has('company_id'),false);assert.equal(q.get('q'),'not found');}
  assert.strictEqual(editor.children[0],draft);assert.equal(filters.elements.stage.value,'proposal');
});
