import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const window = {};
vm.runInNewContext(readFileSync(new URL('../static/publication-draft.js',import.meta.url),'utf8'), {window});
const fromContent = value => JSON.parse(JSON.stringify(window.mercatorDraft.fromContent(value)));

test('a new publication keeps editable content and excludes identity, dates and observations', () => {
  const source = {platform:'youtube', title:'Recorded source', caption:'Current visible edit', hashtags:'#qa #video',
    media_ref:'hoard://lumiere/render/fake', notes:'Visible note', post_id:17, id:17, external_id:'old-network-id',
    status:'published', scheduled_at:'2026-10-20', published_at:'2026-10-21', url:'https://example.com/old', metrics:[{views:250}]};
  const before = structuredClone(source);
  const draft = fromContent(source);
  assert.deepEqual(draft, {platform:'youtube', title:'Recorded source', caption:'Current visible edit', hashtags:'#qa #video',
    media_ref:'hoard://lumiere/render/fake', notes:'Visible note', status:'draft'});
  assert.deepEqual(source,before);
});

test('missing content remains empty and a hashtag array belongs to the new draft', () => {
  const source = {platform:'tiktok', hashtags:['qa','local']};
  const draft = window.mercatorDraft.fromContent(source);
  draft.hashtags.push('copy');
  assert.deepEqual(source.hashtags,['qa','local']);
  assert.equal(draft.caption,''); assert.equal(draft.media_ref,''); assert.equal(draft.notes,'');
});

test('the actual copilot provider exposes unsaved base content without a source object or stale metrics', async () => {
  const values = {platform:'tiktok',status:'draft',title:'Unsaved adaptation',caption:'Visible caption',hashtags:'#qa',
    media_ref:'QA/fake.txt',notes:'Visible notes',scheduled_at:'',published_at:'',url:''};
  const fields = Object.fromEntries(Object.entries(values).map(([key,value])=>[key,{value}]));
  const generic = {value:'',files:[],querySelectorAll:()=>[]};
  const nodes = {'#editor':{open:true},'#editor-form':{elements:fields},'#importer':{open:false}};
  const sandbox = {window:{},location:{pathname:'/publicacion',hash:''},
    document:{querySelector:key=>nodes[key]||generic},
    FormData:class { *[Symbol.iterator](){yield ['views','999'];} },
    fetch:()=>{throw Error('An unsaved publication has no source object to fetch.');}};
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(new URL('../static/copilot-context.js',import.meta.url),'utf8'),sandbox);
  const source = readFileSync(new URL('../static/publicacion.js',import.meta.url),'utf8');
  // Exercise the real registered provider without starting the DOM wiring/network bootstrap.
  vm.runInContext(source.slice(0,source.lastIndexOf('\nwire();'))+"\nstate.basedOn={id:17,title:'Original'}; formBaseline={};",sandbox);
  const context = JSON.parse(JSON.stringify(await sandbox.window.hoardCopilot.context({view:{}})));
  assert.deepEqual(context.active_objects,[]);
  assert.equal(context.view.editor.object_id,null);
  assert.equal(context.view.editor.dirty,true);
  assert.equal(context.view.editor.fields.title,values.title);
  assert.deepEqual(context.view.editor.metrics,{});
  assert.equal(context.view.editor.comparison,null);
  assert.deepEqual(context.view.editor.based_on,{id:17,title:'Original'});
});
