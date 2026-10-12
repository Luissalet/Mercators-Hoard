// Unit tests for the page context builder: node --test tests/copilot_context.test.js
const assert = require('node:assert/strict');
const test = require('node:test');
const { buildContext } = require('../static/copilot.js');

const projects = {
  name: 'projects', page: 'dashboard', sections: ['proyectos'],
  objects: () => [{ kind: 'tracked_project', object_id: 'watchhoard', title: 'WatchHoard', users_total: 12 }],
};
const crm = {
  name: 'crm', page: 'dashboard', sections: ['crm'],
  objects: () => [{ kind: 'crm_deal', object_id: 'd1', title: 'Proposal' }],
  view: () => ({ crm: { deals_total: 3 } }),
  editor: () => ({ kind: 'crm_deal', dirty: true, fields: { title: 'Proposal v2', notes: 'x'.repeat(5000) } }),
};
const sales = {
  name: 'sales', page: 'dashboard', sections: ['ventas'],
  objects: () => [{ kind: 'sales_summary', object_id: 'cults-sales', title: 'Ventas en Cults' }],
  editor: () => ({ kind: 'sales_import', dirty: false, fields: {} }),
};
const post = {
  name: 'publicacion', page: 'publicacion',
  objects: () => [{ kind: 'post', object_id: '7', title: 'Reel' }],
  view: () => ({ publication: { tab: 'calendar' } }),
  editor: () => ({ kind: 'post', dirty: true, fields: { title: 'Reel 2' } }),
};
const parts = [projects, crm, sales, post];

test('only the parts of the page and section in view contribute objects and view', async () => {
  const ctx = await buildContext(parts, { page: 'dashboard', section: 'crm' });
  assert.deepEqual(ctx.active_objects.map((o) => o.object_id), ['d1']);
  assert.equal(ctx.view.page, 'dashboard');
  assert.equal(ctx.view.section, 'crm');
  assert.deepEqual(ctx.view.crm, { deals_total: 3 });
  assert.equal('project' in ctx, false); // Mercator has no projects: never a project, never null
});

test('the section decides what is open; a section without objects gives []', async () => {
  assert.deepEqual((await buildContext(parts, { page: 'dashboard', section: 'proyectos' })).active_objects.map((o) => o.object_id), ['watchhoard']);
  assert.deepEqual((await buildContext(parts, { page: 'dashboard', section: 'catalogo' })).active_objects, []);
});

test('an unsaved form is reported whatever the section, the one in view first, long text clipped', async () => {
  const ctx = await buildContext(parts, { page: 'dashboard', section: 'ventas' });
  assert.equal(ctx.view.editor.kind, 'crm_deal');
  assert.equal(ctx.view.editor.dirty, true);
  assert.ok(ctx.view.editor.fields.notes.length < 2100);
  const inView = await buildContext(parts, { page: 'dashboard', section: 'crm' });
  assert.equal(inView.view.editor.kind, 'crm_deal');
  assert.equal(inView.view.other_editors, undefined);
});

test('an untouched form is not an editor', async () => {
  const ctx = await buildContext([sales], { page: 'dashboard', section: 'ventas' });
  assert.equal(ctx.view.editor, undefined);
});

test('two unsaved forms: the section in view first, the other listed apart', async () => {
  const dirtySales = { ...sales, editor: () => ({ kind: 'sales_import', dirty: true, fields: { file: 'v.csv' } }) };
  const ctx = await buildContext([crm, dirtySales], { page: 'dashboard', section: 'ventas' });
  assert.equal(ctx.view.editor.kind, 'sales_import');
  assert.deepEqual(ctx.view.other_editors.map((e) => e.kind), ['crm_deal']);
});

test('the publishing page reports its post and its editor', async () => {
  const ctx = await buildContext(parts, { page: 'publicacion', section: '' });
  assert.deepEqual(ctx.active_objects.map((o) => [o.kind, o.object_id]), [['post', '7']]);
  assert.equal(ctx.view.page, 'publicacion');
  assert.equal(ctx.view.editor.fields.title, 'Reel 2');
});

test('a part that fails gives no objects and does not break the others', async () => {
  const broken = { name: 'broken', page: 'dashboard', objects: () => { throw new Error('boom'); }, view: () => { throw new Error('boom'); }, editor: () => { throw new Error('boom'); } };
  const rejected = { name: 'rejected', page: 'dashboard', objects: () => Promise.reject(new Error('no')) };
  const ctx = await buildContext([broken, rejected, projects], { page: 'dashboard', section: 'proyectos' });
  assert.deepEqual(ctx.active_objects.map((o) => o.object_id), ['watchhoard']);
});

test('active_objects is always an array', async () => {
  const ctx = await buildContext([], { page: 'dashboard', section: '' });
  assert.deepEqual(ctx.active_objects, []);
  assert.equal(ctx.view.section, 'proyectos');
});
