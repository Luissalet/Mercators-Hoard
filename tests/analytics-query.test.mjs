import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

test('the shipped analytics form sends raw dates and keeps late/error results distinct from the final copilot draft', async () => {
  class Element {
    constructor() { this.children = []; this.style = {}; this.handlers = {}; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
    querySelectorAll() { return buttons; }
  }
  const buttons = [new Element(), new Element()];
  const form = new Element(), status = new Element(), output = new Element();
  form.elements = Object.fromEntries(Object.entries({ project: 'fake', site_id: 'fake.invalid', date_range: 'custom', date_from: '2026-09-01', date_to: '2026-09-15', dimension: 'time:day' }).map(([name,value]) => [name,{ value }]));
  const nodes = { '#analytics-form': form, '#analytics-status': status, '#analytics-results': output, '#analytics-custom-dates': new Element(), '#analytics-date-note': new Element(), '#analytics-history': buttons[1] };
  const requests = [];
  const window = {addEventListener() {}}, location = { pathname: '/', hash: '#analitica' };
  const sandbox = vm.createContext({ window, location, console,
    document: { querySelector: key => nodes[key], createElement: () => new Element() },
    FormData: class { constructor(form) { this.entries = Object.entries(form.elements).filter(([,e]) => !e.disabled).map(([k,e]) => [k,e.value]); } [Symbol.iterator]() { return this.entries[Symbol.iterator](); } },
    fetch: (url,options) => new Promise(resolve => requests.push({ url, body: options?.body ? JSON.parse(options.body) : null, resolve })),
  });
  for (const name of ['copilot-context.js','analytics.js']) vm.runInContext(await fs.readFile(new URL('../static/' + name, import.meta.url),'utf8'),sandbox);
  const plain = x => JSON.parse(JSON.stringify(x));
  const flush = async () => { await new Promise(setImmediate); await new Promise(setImmediate); };
  const submit = () => form.onsubmit({ preventDefault() {} });
  const context = () => window.hoardCopilot.context({view:{}});
  submit();
  assert.deepEqual(requests[0].body.date_range,['2026-09-01','2026-09-15']);
  form.elements.date_to.value = '2026-09-20'; form.handlers.input();
  requests[0].resolve({ok:true,json:async()=>({ id:'old',project:'fake',query:requests[0].body,response:{results:[]},observed_at:'first',origin:'fixture' })});
  await flush();
  assert.equal(output.children.length,0); assert.equal((await context()).view.analytics.applied,null);
  assert.equal((await context()).view.editor.fields.date_to,'2026-09-20');
  submit(); requests[1].resolve({ok:false,json:async()=>({error:'Fixture failure'})}); await flush();
  assert.equal(status.textContent,'Fixture failure'); assert.equal(form.elements.date_to.value,'2026-09-20');
  submit();
  const saved = {id:'new',project:'fake',query:requests[2].body,response:{results:[{dimensions:['2026-09-20'],metrics:[0,null]}]},observed_at:'second',origin:'fixture'};
  requests[2].resolve({ok:true,json:async()=>saved}); await flush();
  assert.equal(output.children.length,1);
  const final = await context();
  assert.deepEqual(plain(final.view.editor.query.date_range),['2026-09-01','2026-09-20']);
  assert.equal(final.view.analytics.applied.snapshots[0].id,'new');
  assert.deepEqual(plain(final.view.analytics.applied.snapshots[0].query.date_range),requests[2].body.date_range);
  form.elements.date_range.value = 'month'; form.handlers.change();
  assert.equal(nodes['#analytics-custom-dates'].hidden,true); assert.equal(form.elements.date_from.disabled,true);
  assert.equal((await context()).view.editor.query.date_range,'month');
  assert.equal((await context()).view.editor.fields.date_from,'2026-09-01');
  assert.equal((await context()).view.analytics.applied,null);
  form.elements.date_range.value = 'custom'; form.handlers.change();
  assert.equal(form.elements.date_from.value,'2026-09-01'); assert.equal(form.elements.date_to.value,'2026-09-20');
});

test('repeat preserves the full saved query, same-query retry and dedup identity without changing the form; context edits reject late results', async () => {
  class Element {
    constructor() { this.children=[];this.style={};this.handlers={}; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children=children; }
    addEventListener(name,fn) { this.handlers[name]=fn; }
    querySelectorAll() { return buttons; }
  }
  const buttons=[new Element(),new Element()],form=new Element(),status=new Element(),output=new Element();
  form.elements=Object.fromEntries(Object.entries({project:'',site_id:'draft.invalid',date_range:'month',date_from:'2026-01-01',date_to:'2026-01-31',dimension:''}).map(([name,value])=>[name,{value}]));
  const nodes={'#analytics-form':form,'#analytics-status':status,'#analytics-results':output,'#analytics-custom-dates':new Element(),'#analytics-date-note':new Element(),'#analytics-history':buttons[1]};
  const requests=[],handlers={},window={addEventListener:(name,fn)=>{handlers[name]=fn}},location={pathname:'/',hash:'#analitica'};
  const sandbox=vm.createContext({window,location,console,document:{querySelector:key=>nodes[key],createElement:()=>new Element()},FormData:class{constructor(f){this.entries=Object.entries(f.elements).filter(([,e])=>!e.disabled).map(([k,e])=>[k,e.value])}[Symbol.iterator](){return this.entries[Symbol.iterator]()}},fetch:(url,options)=>new Promise(resolve=>requests.push({url,body:options?.body?JSON.parse(options.body):null,resolve}))});
  for(const name of ['copilot-context.js','analytics.js'])vm.runInContext(await fs.readFile(new URL('../static/'+name,import.meta.url),'utf8'),sandbox);
  const saved={id:'source-id',project:'saved',observed_at:'2026-09-01T12:00:00Z',origin:'https://historical.invalid',query:{site_id:'saved.invalid',date_range:['2026-08-01','2026-08-31'],metrics:['visitors','pageviews','bounce_rate'],dimensions:['event:page','visit:country_name'],filters:[['contains','event:page',['/ño'],{case_sensitive:false}]],order_by:[['pageviews','desc']],pagination:{limit:3,offset:1}},response:{results:[{dimensions:['/ño','España'],metrics:[0,null,50]}],query:{site_id:'not-the-request.invalid'}}};
  const original=JSON.stringify(saved),flush=async()=>{await new Promise(setImmediate);await new Promise(setImmediate)};
  const resolve=async(index,value,ok=true)=>{requests[index].resolve({ok,json:async()=>value});await flush()};
  const all=root=>[root,...root.children.flatMap(all)],click=text=>all(output).find(e=>e.textContent===text).onclick();
  buttons[1].onclick();await resolve(0,{snapshots:[saved]});click('Volver a consultar y guardar');
  const expected={...saved.query,project:'saved',page_size:3,offset:1};delete expected.pagination;
  assert.deepEqual(requests[1].body,expected);await resolve(1,{error:'Fallo antes de guardar'},false);
  assert.equal(form.elements.site_id.value,'draft.invalid');assert.equal(form.elements.project.value,'');
  click('Reintentar consulta guardada');assert.deepEqual(requests[2].body,expected);
  await resolve(2,{...saved,added:false});assert.match(status.textContent,/ID y fecha originales, sin crear otro registro/);
  const context=await window.hoardCopilot.context({view:{}});assert.equal(context.view.analytics.applied.source_snapshot_id,'source-id');assert.equal(context.view.analytics.applied.project,'saved');assert.equal(context.view.editor.fields.project,'');
  assert.equal(context.view.analytics.applied.snapshots[0].observed_at,saved.observed_at);assert.equal(JSON.stringify(saved),original);
  click('Volver a consultar y guardar');form.elements.site_id.value='later.invalid';form.handlers.input();
  await resolve(3,{...saved,id:'late-new',added:true});assert.equal(output.children.length,0);
  assert.equal((await window.hoardCopilot.context({view:{}})).view.analytics.repeating,null);
  buttons[1].onclick();await resolve(4,{snapshots:[saved]});click('Volver a consultar y guardar');
  location.hash='#ventas';handlers.hashchange();await resolve(5,{...saved,added:false});assert.equal(output.children.length,0);
  assert.equal(form.elements.site_id.value,'later.invalid');
});
