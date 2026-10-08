(() => {
  const root = document.querySelector('#crm');
  if (!root) return;
  const $ = s => root.querySelector(s);
  const labels = {lead:'Contacto inicial',qualified:'Cualificada',proposal:'Propuesta',negotiation:'Negociación',won:'Ganada',lost:'Perdida',archived:'Archivada'};
  const filters = $('#crm-filters'), editor = $('#crm-editor'), message = $('#crm-message');
  let offset = 0, total = 0, busy = false, currentKind = '', current = null, activityRequest = '';
  let loadVersion = 0;
  let fieldId = 0;
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
    try {await fn(); message.textContent='Operación completada.';} catch(e){message.textContent=e.message;}
    finally {lock(false);}
  }
  async function load() {
    const version=++loadVersion, qs=query(); qs.set('offset',offset);qs.set('limit',50);
    const [listing, stats] = await Promise.all([request('/api/crm?'+qs),request('/api/crm/summary?'+query())]);
    if(version!==loadVersion)return;
    total=Math.max(listing.deal_total,listing.company_total);$('#crm-count').textContent=`${listing.deal_total} oportunidades · ${listing.company_total} empresas en este filtro`;
    $('#crm-page').textContent=total ? `Página ${Math.floor(offset/50)+1} de ${Math.ceil(total/50)}` : 'Sin registros';
    const table=$('#crm-deals');table.replaceChildren();
    if(!listing.deals.length){const tr=node('tr'),td=node('td',total?'No hay más resultados en esta página.':'Añade una empresa y su primera oportunidad, o cambia los filtros.');td.colSpan=5;tr.append(td);table.append(tr);}
    for(const row of listing.deals){const tr=node('tr');const first=node('td'),button=node('button',row.title);button.type='button';button.onclick=()=>void work(()=>edit('deal',row.id));first.append(button,node('small',row.company_name));tr.append(first,node('td',row.project||'Sin proyecto'),node('td',labels[row.stage]),node('td',`${row.amount} ${row.currency}`));const next=node('td',row.next_action||'Sin próxima acción');next.append(node('small',row.due_on||'Sin fecha'));tr.append(next);table.append(tr);}
    const companies=$('#crm-companies');companies.replaceChildren();
    for(const row of listing.companies){const button=node('button',row.name);button.type='button';button.onclick=()=>void work(()=>edit('company',row.id));companies.append(button);}
    if(listing.company_total>listing.companies.length)companies.append(node('p',`Se muestran ${listing.companies.length} de ${listing.company_total} empresas. Usa los filtros o la paginación.`));
    const summary=$('#crm-summary');summary.replaceChildren(node('p',stats.note));
    for(const [currency, values] of Object.entries(stats.currencies)){const line=node('p');line.append(node('strong',currency+' · '),node('span',`Abierto ${values.open} · Ponderado ${values.weighted} · Ganado ${values.won}`));summary.append(line);}
    lock(busy);
  }
  function field(form,key,label,value,type='text',options=null,required=false) {
    const wrap=node('div'),caption=node('label',label),input=node(options?'select':type==='textarea'?'textarea':'input');
    wrap.className='crm-field'; input.id='crm-field-'+(++fieldId); caption.htmlFor=input.id;
    input.name=key;input.required=required;
    if(options){for(const [id,text] of options)input.append(option(id,text));}else if(type!=='textarea'){input.type=type;input.maxLength=key==='notes'?8000:key==='document_refs'?16000:1000;}
    input.value=value??'';if(type==='number'){input.min=0;input.max=100;input.step=1;}
    if(type==='textarea')wrap.classList.add('crm-wide');wrap.append(caption,input);form.append(wrap);return input;
  }
  async function edit(kind,id=null) {
    let row=id?await request('/api/crm/get?'+new URLSearchParams({kind,id})):{};
    const companies=[];
    if(kind==='deal'){
      let start=0, companyTotal=1;
      while(start<companyTotal){const page=await request('/api/crm?limit=500&offset='+start);companies.push(...page.companies);companyTotal=page.company_total;start+=500;}
      if(!companies.length)throw new Error('Añade una empresa antes de crear una oportunidad.');
    }
    currentKind=kind;current=row;activityRequest=crypto.randomUUID();editor.replaceChildren();editor.hidden=false;
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
    const actions=node('div');actions.className='crm-actions';const save=node('button','Guardar'),cancel=node('button','Cerrar editor');save.type='submit';save.className='primary';cancel.type='button';cancel.onclick=()=>{editor.hidden=true;editor.replaceChildren();};actions.append(save,cancel);form.append(actions);
    form.onsubmit=e=>{e.preventDefault();void work(async()=>{const payload=Object.fromEntries(new FormData(form));if(currentKind==='deal'){payload.probability=Number(payload.probability);payload.document_refs=payload.document_refs.split('\n').map(v=>v.trim()).filter(Boolean);}if(current.id){payload.id=current.id;payload.expected_revision=current.revision;}const result=await request('/api/crm/'+currentKind,payload);await load();await edit(currentKind,result[currentKind].id);});};editor.append(form);
    if(kind==='deal'&&id){
      editor.append(node('h3','Interacciones e historial'));
      const noteForm=node('form'),note=field(noteForm,'note','Anotar una interacción real','', 'textarea',null,true);field(noteForm,'source_ref','Fuente de la interacción (referencia Hoard)','');
      const add=node('button','Guardar interacción');add.type='submit';noteForm.append(add);
      noteForm.onsubmit=e=>{e.preventDefault();void work(async()=>{await request('/api/crm/activity',{deal_id:id,...Object.fromEntries(new FormData(noteForm)),request_id:activityRequest});await edit('deal',id);});};editor.append(noteForm);
      const history=node('ul');history.className='crm-history';
      for(const activity of row.activities||[]){const li=node('li'),time=node('time',new Date(activity.observed_at).toLocaleString('es-ES'));time.dateTime=activity.observed_at;li.append(time);if(activity.kind==='change'){const details=node('details');details.append(node('summary','Cambio registrado'),node('pre',JSON.stringify(JSON.parse(activity.note),null,2)));li.append(details);}else li.append(node('p',activity.note),node('small',activity.source_ref));history.append(li);}editor.append(history);
      if((row.activities||[]).length===200)editor.append(node('p','Se muestran las 200 actividades más recientes. La exportación JSON incluye el historial completo.'));
    }
    grid.querySelector('input,select')?.focus();
    lock(busy);
  }
  filters.onsubmit=e=>{e.preventDefault();offset=0;void work(load);};
  $('#crm-new-company').onclick=()=>void work(()=>edit('company'));
  $('#crm-new-deal').onclick=()=>void work(()=>edit('deal'));
  $('#crm-prev').onclick=()=>{offset=Math.max(0,offset-50);void work(load);};
  $('#crm-next').onclick=()=>{offset+=50;void work(load);};
  for(const format of ['json','csv'])$('#crm-export-'+format).onclick=()=>void work(async()=>{const data=await request('/api/crm/export?'+query());const payload=format==='csv'?'\ufeff'+data.csv:JSON.stringify(data,null,2),url=URL.createObjectURL(new Blob([payload],{type:format==='csv'?'text/csv;charset=utf-8':'application/json'})),a=node('a');a.href=url;a.download='mercator-crm.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  void work(load);
})();
