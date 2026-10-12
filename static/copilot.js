/* What the Faustus copilot panel asks this app for: the real objects open in the view.
   The launcher itself is injected by the server (mercator_copilot.py); this file only answers
   window.hoardCopilot.context() and refreshes the lists after an agent turn. It never throws and never rejects.
   Each script of the app registers a "part" for what it shows:
     { name, page: 'dashboard' | 'publicacion', sections?: [ids], objects?(), view?(), editor?(), refresh?() }
   Mercator has no projects, so the context carries no `project`. */
(() => {
  'use strict';
  const MAX_TEXT = 2000;
  const MAX_OBJECTS = 24;

  const clip = value => {
    if (typeof value === 'string') return value.length > MAX_TEXT ? value.slice(0, MAX_TEXT) + '...' : value;
    if (Array.isArray(value)) return value.map(clip);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, clip(v)]));
    return value;
  };

  /** Pure: the context additions for `env` = { page, section }, from the registered parts. */
  async function buildContext(parts, env) {
    const page = env.page;
    const here = parts.filter(part => part.page === page);
    const active = here.filter(part => !part.sections || part.sections.includes(env.section));
    const out = { active_objects: [], view: { page } };
    if (page === 'dashboard') out.view.section = env.section || 'proyectos';
    for (const part of active) {
      try {
        const objects = await (part.objects ? part.objects() : []);
        if (Array.isArray(objects)) out.active_objects.push(...objects);
      } catch (error) { /* the part could not read its data: no objects, no error */ }
      try {
        const view = part.view ? part.view() : null;
        if (view && typeof view === 'object') Object.assign(out.view, view);
      } catch (error) { /* ignore */ }
    }
    out.active_objects = clip(out.active_objects.slice(0, MAX_OBJECTS));
    const editors = [];
    for (const part of here) {
      try {
        const editor = part.editor ? part.editor() : null;
        if (editor && editor.dirty) editors.push({ editor: { kind: editor.kind, dirty: true, fields: clip(editor.fields || {}) }, active: active.includes(part) });
      } catch (error) { /* ignore */ }
    }
    editors.sort((a, b) => Number(b.active) - Number(a.active));
    if (editors.length) out.view.editor = editors[0].editor;
    if (editors.length > 1) out.view.other_editors = editors.slice(1).map(entry => entry.editor);
    return out;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { buildContext };
  if (typeof window === 'undefined') return;

  const parts = new Map();
  window.hoardCopilotRegister = part => { parts.set(part.name, part); };

  /** The section of the dashboard the user is looking at: the one with the most visible area (the hash decides a tie). */
  function currentSection() {
    let best = '', area = 0;
    for (const node of document.querySelectorAll('main section[id]')) {
      const rect = node.getBoundingClientRect();
      const visible = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
      if (visible > area) { best = node.id; area = visible; }
    }
    return best || location.hash.replace(/^#/, '') || 'proyectos';
  }

  let timer = null;
  window.hoardCopilot = {
    async context() {
      const page = location.pathname.startsWith('/publicacion') ? 'publicacion' : 'dashboard';
      try {
        return await buildContext([...parts.values()], { page, section: page === 'dashboard' ? currentSection() : '' });
      } catch (error) {
        return { active_objects: [], view: { page } };
      }
    },
    onTurnEnd() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        for (const part of parts.values()) {
          try { if (part.refresh) part.refresh(); } catch (error) { /* one page failing must not stop the others */ }
        }
      }, 250);
    },
  };
})();
