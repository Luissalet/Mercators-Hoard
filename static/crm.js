(() => {
  const root = document.querySelector('#crm');
  if (!root) return;
  const $ = s => root.querySelector(s);
  const labels = {lead:'Contacto inicial',qualified:'Cualificada',proposal:'Propuesta',negotiation:'Negociación',won:'Ganada',lost:'Perdida',archived:'Archivada'};
  const filters = $('#crm-filters'), editor = $('#crm-editor'), message = $('#crm-message');
  let offset = 0, total = 0, busy = false, currentKind = '', current = null, activityAttempt = null;
  let loadVersion = 0;
  let fieldId = 0;
  let formBaseline = {};
  const values = form => {
    const fields = Object.fromEntries(new FormData(form));
    if (currentKind === 'deal') {
      fields.probability = Number(fields.probability);
      fields.document_refs = fields.document_refs.split('\n').map(v => v.trim()).filter(Boolean);
    }
    return fields;
  };
  window.mercatorCopilot?.register('crm', {
    async context() {
      if (location.hash !== '#crm') return null;
      const kind = currentKind, id = current?.id;
      const form = editor.hidden ? null : editor.querySelector('form');
      const fields = form ? window.mercatorCopilot.changed(values(form), formBaseline) : {};
      const activity = editor.querySelectorAll('form')[1];
      const activityFields = activity ? Object.fromEntries(new FormData(activity)) : null;
      const filterFields = Object.fromEntries(new FormData(filters));
      let row = null;
      if (form && id) {
        try { row = await request('/api/crm/get?' + new URLSearchParams({kind, id})); }
        catch { /* A removed row is no longer an active object. Keep its local draft. */ }
      }
      return { active_objects: row ? [{ kind: 'crm-' + kind,
        object_id: row.id, title: row.name || row.title }] : [],
        view: { editor: form ? { kind: 'crm-' + kind, object_id: row?.id || null,
          missing: Boolean(id && !row),
          dirty: Object.keys(fields).length > 0, fields,
          activity: activityFields } : null, filters: filterFields } };
    },
    refresh() { void work(load); },
  });
  const node = (tag, text) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; };
  const option = (value, text) => {const el = node('option',text); el.value=value; return el;};
  for (const [id, label] of Object.entries(labels)) filters.elements.stage.append(option(id,label));
  const query = () => new URLSearchParams([...new FormData(filters)].filter(([,v]) => v !== ''));
  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json(); if (!response.ok || data.ok === false) throw new Error(data.error || 'No se pudo completar la operación. Reintenta.'); return data;
  }
  function lock(value) {busy=value; for(const button of root.querySelectorAll('button')) button.disabled=value; if(!value){$('#crm-prev').disabled=offset===0;$('#crm-next').disabled=offset+50>=total;}}
  async function work(fn) {
    if(busy) return; lock(true); message.textContent='Cargando…';
    try {if(await fn()!==false)message.textContent='Operación completada.';} catch(e){message.textContent=e.message;}
    finally {lock(false);}
  }
  async function load() {
    const version=++loadVersion, scope=query().toString(), page=offset, qs=new URLSearchParams(scope); qs.set('offset',page);qs.set('limit',50);
    clearListing('Leyendo oportunidades con los filtros actuales…');
    let listing,stats;
    try { [listing,stats]=await Promise.all([request('/api/crm?'+qs),request('/api/crm/summary?'+scope)]); }
    catch(error) {if(version!==loadVersion || scope!==query().toString() || page!==offset)return false;clearListing('No se pudieron leer las oportunidades. Pulsa Filtrar para reintentar.');throw error;}
    if(version!==loadVersion || scope!==query().toString() || page!==offset)return false;
    total=Math.max(listing.deal_total,listing.company_total);$('#crm-count').textContent=`${listing.deal_total} ${listing.deal_total===1?'oportunidad':'oportunidades'} · ${listing.company_total} ${listing.company_total===1?'empresa':'empresas'} en este filtro`;
    $('#crm-page').textContent=total ? `Página ${Math.floor(offset/50)+1} de ${Math.ceil(total/50)}` : 'Sin registros';
    const table=$('#crm-deals');table.replaceChildren();
    if(!listing.deals.length){const tr=node('tr'),td=node('td',filters.elements.company_id.value?'No hay oportunidades de esta empresa con los filtros actuales.':total?'No hay más resultados en esta página.':'Añade una empresa y su primera oportunidad, o cambia los filtros.');td.colSpan=5;tr.append(td);table.append(tr);}
    for(const row of listing.deals){const tr=node('tr');const first=node('td'),button=node('button',row.title);button.type='button';button.onclick=()=>void work(()=>edit('deal',row.id));first.append(button,node('small',row.company_name));tr.append(first,node('td',row.project||'Sin proyecto'),node('td',labels[row.stage]),node('td',`${row.amount} ${row.currency}`));const next=node('td',row.next_action||'Sin próxima acción');next.append(node('small',row.due_on||'Sin fecha'));tr.append(next);table.append(tr);}
    const companies=$('#crm-companies');companies.replaceChildren();
    for(const row of listing.companies){const button=node('button',row.name);button.type='button';button.onclick=()=>void work(()=>edit('company',row.id));companies.append(button);}
    if(listing.company_total>listing.companies.length)companies.append(node('p',`Se muestran ${listing.companies.length} de ${listing.company_total} empresas. Usa los filtros o la paginación.`));
    const summary=$('#crm-summary');summary.replaceChildren(node('p',stats.note));
    for(const [currency, values] of Object.entries(stats.currencies)){const line=node('p');line.append(node('strong',currency+' · '),node('span',`Abierto ${values.open} · Ponderado ${values.weighted} · Ganado ${values.won}`));summary.append(line);}
    lock(busy);
  }
  function clearListing(text) {
    total=0;$('#crm-count').textContent=text;$('#crm-page').textContent='';
    $('#crm-deals').replaceChildren();$('#crm-summary').replaceChildren();$('#crm-companies').replaceChildren();
    $('#crm-prev').disabled=true;$('#crm-next').disabled=true;
  }
  function companyScope(company) {
    filters.elements.company_id.value=company?.id||'';
    $('#crm-company-scope').hidden=!company;
    $('#crm-company-name').textContent=company?.name||'';
    $('#crm-company-id').textContent=company?'ID: '+company.id:'';
    offset=0;void work(load);
  }
  function field(form,key,label,value,type='text',options=null,required=false) {
    const wrap=node('div'),caption=node('label',label),input=node(options?'select':type==='textarea'?'textarea':'input');
    wrap.className='crm-field'; input.id='crm-field-'+(++fieldId); caption.htmlFor=input.id;
    input.name=key;input.required=required;
    if(options){for(const [id,text] of options)input.append(option(id,text));}else if(type!=='textarea'){input.type=type;input.maxLength=key==='notes'?8000:key==='document_refs'?16000:1000;}
    input.value=value??'';if(type==='number'){input.min=0;input.max=100;input.step=1;}
    if(type==='textarea')wrap.classList.add('crm-wide');wrap.append(caption,input);form.append(wrap);return input;
  }
  async function edit(kind,id=null,previous=null) {
    let row=id?await request('/api/crm/get?'+new URLSearchParams({kind,id})):{};
    const companies=[];
    if(kind==='deal'){
      let start=0, companyTotal=1;
      while(start<companyTotal){const page=await request('/api/crm?limit=500&offset='+start);companies.push(...page.companies);companyTotal=page.company_total;start+=500;}
      if(!companies.length)throw new Error('Añade una empresa antes de crear una oportunidad.');
    }
    if(previous && !previous.form.isConnected) return;
    const pending = previous ? window.mercatorCopilot.changed(values(previous.form), previous.sent) : {};
    const active = document.activeElement;
    const oldActivity = previous ? editor.querySelectorAll('form')[1] : null;
    const activityFields = oldActivity ? Object.fromEntries(new FormData(oldActivity)) : null;
    if (activityFields && previous.activitySent) {
      for (const [key,value] of Object.entries(previous.activitySent)) {
        if (activityFields[key] === value) activityFields[key] = '';
      }
    }
    const focus = previous && (previous.form.contains(active) || oldActivity?.contains(active))
      ? {index: oldActivity?.contains(active) ? 1 : 0, name: active.name,
          start: active.selectionStart, end: active.selectionEnd} : null;
    currentKind=kind;current=row;if(!previous)activityAttempt=null;editor.replaceChildren();editor.hidden=false;
    editor.append(node('h3',`${id?'Editar':'Añadir'} ${kind==='company'?'empresa':'oportunidad'}`));
    const form=node('form'),grid=node('div');grid.className='crm-fields';form.append(grid);
    if(kind==='company'){field(grid,'name','Empresa',row.name,'text',null,true);field(grid,'segment','Segmento',row.segment);}
    else {field(grid,'company_id','Empresa',row.company_id||companies[0].id,'text',companies.map(c=>[c.id,c.name]),true);field(grid,'title','Oportunidad',row.title,'text',null,true);}
    field(grid,'project','Proyecto',row.project||filters.elements.project.value);field(grid,'owner','Responsable',row.owner);
    if(kind==='deal'){
      field(grid,'stage','Etapa',row.stage||'lead','text',Object.entries(labels));
      const money=field(grid,'amount','Importe estimado',row.amount||'0.00');money.inputMode='decimal';money.pattern='[0-9]{1,12}(\\.[0-9]{1,2})?';money.required=true;
      const currency=field(grid,'currency','Moneda',row.currency||'EUR');currency.pattern='[A-Z]{3}';currency.maxLength=3;currency.required=true;
      field(grid,'probability','Probabilidad estimada por ti (%)',row.probability??0,'number',null,true);
      field(grid,'next_action','Próxima acción',row.next_action);field(grid,'due_on','Fecha de seguimiento',row.due_on,'date');
      field(grid,'document_refs','Documentos (una referencia Atlas, Kafka o Plato por línea)',(row.document_refs||[]).join('\n'),'textarea');
    }
    field(grid,'people_ref','Contacto en People (hoard://people/…)',row.people_ref);
    field(grid,'source_ref','Fuente (referencia Hoard)',row.source_ref);field(grid,'notes','Notas',row.notes,'textarea');
    const actions=node('div');actions.className='crm-actions';const save=node('button','Guardar'),cancel=node('button','Cerrar editor');save.type='submit';save.className='primary';cancel.type='button';cancel.onclick=()=>{editor.hidden=true;editor.replaceChildren();};actions.append(save,cancel);
    if(kind==='company'&&id){const related=node('button','Ver sus oportunidades');related.type='button';related.onclick=()=>companyScope({id:row.id,name:row.name});actions.append(related);}
    form.append(actions);
    formBaseline = values(form);
    for (const [key,value] of Object.entries(pending)) {
      const input = form.elements.namedItem(key);
      if(input) input.value = Array.isArray(value) ? value.join('\n') : value;
    }
    form.onsubmit=e=>{e.preventDefault();void work(async()=>{
      const payload=values(form);
      const savedKind=currentKind;
      const result=current.id
        ? await request('/api/crm/patch', {kind:currentKind,id:current.id,
            fields:window.mercatorCopilot.changed(payload,formBaseline)})
        : await request('/api/crm/'+currentKind,payload);
      await load();await edit(savedKind,result[savedKind].id,{form,sent:payload});
    });};editor.append(form);
    if(kind==='deal'&&id){
      editor.append(node('h3','Interacciones e historial'));
      const noteForm=node('form'),note=field(noteForm,'note','Anotar una interacción real','', 'textarea',null,true);field(noteForm,'source_ref','Fuente de la interacción (referencia Hoard)','');
      const observed=field(noteForm,'observed_at','Fecha real de la interacción (ISO con zona, opcional)','');
      observed.placeholder='2026-10-01T09:30:00-03:00';
      const dateHelp=node('p','Déjala vacía para usar la hora del servidor al guardar. Si indicas una fecha, incluye la hora y la zona: Z o un desfase como +02:00. No se deduce una zona ni se programa un aviso.');
      dateHelp.className='crm-help';dateHelp.id=observed.id+'-help';observed.setAttribute('aria-describedby',dateHelp.id);noteForm.append(dateHelp);
      const add=node('button','Guardar interacción');add.type='submit';noteForm.append(add);
      if(activityFields) for(const [key,value] of Object.entries(activityFields)) {
        const input=noteForm.elements.namedItem(key);if(input) input.value=value;
      }
      noteForm.onsubmit=e=>{e.preventDefault();void work(async()=>{
        const sent=Object.fromEntries(new FormData(noteForm)), fields={...sent};
        if(!fields.observed_at)delete fields.observed_at;
        const fingerprint=JSON.stringify({deal_id:id,...fields});
        if(activityAttempt?.fingerprint!==fingerprint)activityAttempt={fingerprint,id:crypto.randomUUID()};
        const baseline={...formBaseline};
        await request('/api/crm/activity',{deal_id:id,...fields,request_id:activityAttempt.id});
        await edit('deal',id,{form,sent:baseline,activitySent:sent});
        activityAttempt=null;
      });};editor.append(noteForm);
      const orderHelp=node('p','Ordenado por fecha de registro, más recientes primero. Se muestran hasta 200 actividades; la exportación JSON incluye el historial completo.');orderHelp.className='crm-help';editor.append(orderHelp);
      const history=node('ul');history.className='crm-history';
      for(const activity of row.activities||[]){
        const li=node('li'),dates=node('dl');dates.className='crm-activity-dates';
        for(const [label,value] of [['Ocurrió',activity.observed_at],['Registrado',activity.recorded_at]]){
          const group=node('div'),definition=node('dd'),time=node('time',new Date(value).toLocaleString('es-ES',{timeZoneName:'short'}));
          time.dateTime=value;definition.append(time,node('code',value));group.append(node('dt',label),definition);dates.append(group);
        }
        li.append(dates);
        if(activity.kind==='change'){const details=node('details');details.append(node('summary','Cambio registrado'),node('pre',JSON.stringify(JSON.parse(activity.note),null,2)));li.append(details);}else li.append(node('p',activity.note),node('small',activity.source_ref));history.append(li);
      }editor.append(history);
    }
    if(focus) {
      const input=editor.querySelectorAll('form')[focus.index]?.elements.namedItem(focus.name);
      input?.focus();
      if(input && typeof focus.start==='number') input.setSelectionRange(focus.start,focus.end);
    } else if(!previous) grid.querySelector('input,select')?.focus();
    lock(busy);
  }
  filters.onsubmit=e=>{e.preventDefault();offset=0;void work(load);};
  filters.addEventListener('input',()=>{loadVersion++;clearListing('Filtros pendientes de aplicar');message.textContent='Pulsa Filtrar para aplicar los cambios.';});
  $('#crm-all-companies').onclick=()=>companyScope(null);
  $('#crm-new-company').onclick=()=>void work(()=>edit('company'));
  $('#crm-new-deal').onclick=()=>void work(()=>edit('deal'));
  $('#crm-prev').onclick=()=>{offset=Math.max(0,offset-50);void work(load);};
  $('#crm-next').onclick=()=>{offset+=50;void work(load);};
  for(const format of ['json','csv'])$('#crm-export-'+format).onclick=()=>void work(async()=>{const data=await request('/api/crm/export?'+query());const payload=format==='csv'?'\ufeff'+data.csv:JSON.stringify(data,null,2),url=URL.createObjectURL(new Blob([payload],{type:format==='csv'?'text/csv;charset=utf-8':'application/json'})),a=node('a');a.href=url;a.download='mercator-crm.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  void work(load);
})();
