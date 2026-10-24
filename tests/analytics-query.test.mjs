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
  const window = {}, location = { pathname: '/', hash: '#analitica' };
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
