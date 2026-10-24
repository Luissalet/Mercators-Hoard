import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

test('actual catalog consumer keeps native pages, discards old reads and retries the requested page', async () => {
  class Element {
    constructor() { this.children = []; this.events = {}; this.value = ''; this.hidden = false; this.disabled = false; this.textContent = ''; this.style = {}; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    setAttribute(key, value) { this[key] = value; }
    addEventListener(name, fn) { this.events[name] = fn; }
    querySelectorAll() { return []; }
    focus() {}
    fire(name) { this.events[name]?.({preventDefault() {}, currentTarget: this}); }
  }
  const nodes = new Map(), get = key => {
    if (!nodes.has(key)) nodes.set(key, new Element());
    return nodes.get(key);
  };
  get('#catalog-mode').value = 'all';
  get('#sales-file').value = 'unsaved.csv';
  const reads = [], providers = new Map();
  const summary = {projects: [], statuses: [], metrics: [], history: [], sales_count: 0, product_sales: [], monthly_sales: [], catalog: {state: 'ok', count: 103, with_listing: 103, items: []}};
  const response = (body, ok = true) => ({ok, json: async () => body});
  const sandbox = {document: {querySelector: get, createElement: () => new Element(), createTextNode: text => ({textContent: text})},
    window: {mercatorCopilot: {register: (name, provider) => providers.set(name, provider)}}, location: {hash: '#catalogo'},
    URLSearchParams, Intl, console, setTimeout, fetch: async url => {
      if (url === '/api/summary') return response(summary);
      return new Promise(resolve => reads.push({url, resolve}));
    }};
  vm.runInNewContext(await readFile(new URL('../static/app.js', import.meta.url), 'utf8'), sandbox);
  const tick = () => new Promise(resolve => setImmediate(resolve));
  const data = (prefix, offset = 0, total = 103) => ({state: 'ok', total, offset, items: Array.from({length: Math.min(50, total - offset)}, (_, n) => ({id: `${prefix}-${offset + n}`, title: `Título ${offset + n}`, has_listing: true, tags: 0, updated_at: null}))});
  const text = node => String(node.textContent) + node.children.map(text).join('');
  await tick(); assert.equal(reads.length, 1);
  reads[0].resolve(response(data('initial'))); await tick();
  assert.equal(get('#catalog-items').children.length, 50);
  assert.match(get('#catalog-showing').textContent, /1–50 de 103/);
  get('#catalog-next').onclick(); await tick();
  assert.equal(new URLSearchParams(reads[1].url.split('?')[1]).get('offset'), '50');
  get('#catalog-search').value = 'nuevo'; get('#catalog-search').fire('input');
  assert.equal(get('#catalog-items').children.length, 0);
  assert.equal(providers.get('dashboard').context().view.catalog.applied, null);
  get('#catalog-filters').fire('submit'); await tick();
  reads[1].resolve(response(data('stale', 50))); await tick();
  assert.equal(get('#catalog-items').children.length, 0);
  reads[2].resolve(response(data('new'))); await tick();
  assert.equal(providers.get('dashboard').context().view.catalog.applied.ids[0], 'new-0');
  get('#catalog-next').onclick(); await tick();
  reads[3].resolve(response({error: 'Fallo temporal'}, false)); await tick();
  assert.equal(get('#catalog-retry').hidden, false);
  assert.equal(get('#catalog-search').value, 'nuevo');
  get('#catalog-retry').onclick(); await tick();
  assert.equal(reads[4].url, reads[3].url);
  reads[4].resolve(response(data('retry', 50))); await tick();
  assert.match(text(get('#catalog-items')), /retry-99/);
  assert.match(get('#catalog-showing').textContent, /51–100 de 103/);
  get('#catalog-mode').value = 'untagged'; get('#catalog-mode').fire('change');
  const count = reads.length;
  providers.get('dashboard').refresh(); await tick();
  assert.equal(reads.length, count, 'refresh preserves unapplied selector instead of querying it');
  assert.equal(providers.get('dashboard').context().view.catalog.pending, true);
  get('#catalog-filters').fire('submit'); await tick();
  assert.equal(new URLSearchParams(reads[5].url.split('?')[1]).get('untagged'), 'true');
  reads[5].resolve(response({state: 'ok', total: 0, offset: 0, items: []})); await tick();
  assert.match(text(get('#catalog-items')), /No hay productos que coincidan/);
  get('#catalog-filters').fire('submit'); await tick();
  reads[6].resolve(response({state: 'needs_access', total: 0, offset: 0, items: []})); await tick();
  assert.match(text(get('#catalog-items')), /No hay acceso/);
  assert.equal(get('#sales-file').value, 'unsaved.csv');
});
