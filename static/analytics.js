/* Uses the same handlers as the family API. Credentials remain in the service. */
(() => {
  const form = document.querySelector('#analytics-form'), status = document.querySelector('#analytics-status'), output = document.querySelector('#analytics-results');
  const node = (tag, text) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; };
  async function request(path, body) {
    const response = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data;
  }
  function show(rows) {
    output.replaceChildren();
    if (!rows.length) { output.append(node('p','No hay consultas guardadas.')); return; }
    for (const snapshot of rows) {
      const details = node('details'); details.open = rows.length === 1;
      details.append(node('summary',`${snapshot.project} · ${snapshot.query.site_id} · ${snapshot.observed_at}`));
      details.append(node('p',`${snapshot.origin} · Periodo: ${JSON.stringify(snapshot.query.date_range)}`));
      const wrap = node('div'); wrap.className = 'table-wrap'; const table = node('table');
      table.append(node('caption','Valores devueltos por Plausible'));
      const head = node('tr'); for (const name of [...snapshot.query.dimensions,...snapshot.query.metrics]) head.append(node('th',name));
      const thead = node('thead'); thead.append(head); table.append(thead); const tbody = node('tbody');
      for (const row of snapshot.response.results) { const tr = node('tr'); for (const value of [...row.dimensions,...row.metrics]) tr.append(node('td',value === null ? 'No disponible' : typeof value === 'object' ? JSON.stringify(value) : String(value))); tbody.append(tr); }
      table.append(tbody); wrap.append(table); details.append(wrap);
      const raw = node('details'); raw.append(node('summary','Consulta y respuesta completas')); const pre = node('pre',JSON.stringify(snapshot,null,2)); pre.style.whiteSpace='pre-wrap'; pre.style.overflowWrap='anywhere'; raw.append(pre); details.append(raw);
      const download = node('button','Exportar JSON'); download.type='button'; download.onclick=()=>{ const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'})); const a=node('a'); a.href=url; a.download=`plausible-${snapshot.id}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }; details.append(download); output.append(details);
    }
  }
  async function work(fn) { for(const button of form.querySelectorAll('button')) button.disabled=true; status.textContent='Consultando…'; try { await fn(); status.textContent='Lectura completada.'; } catch(e) { status.textContent=e.message; } finally { for(const button of form.querySelectorAll('button')) button.disabled=false; } }
  form.onsubmit=e=>{e.preventDefault(); void work(async()=>{const fields=new FormData(form), dimension=fields.get('dimension'); show([await request('/api/analytics/query',{project:fields.get('project'),site_id:fields.get('site_id'),date_range:fields.get('date_range'),metrics:['visitors','pageviews'],dimensions:dimension?[dimension]:[]})]);});};
  document.querySelector('#analytics-history').onclick=()=>void work(async()=>show((await request('/api/analytics/history?project='+encodeURIComponent(form.elements.project.value))).snapshots));
})();
