'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const NS = 'http://www.w3.org/2000/svg';
const state = {config:null, objects:[], categories:new Set(), query:'', selected:null, edit:false, draft:null, tool:null, drawing:[], hover:null, labels:false, session:null, view:[0,0,1440,720], drag:null, busy:false, historyToken:0, dataToken:0, offline:false, exitEditAfterDraft:false, layerDraft:null};
let toastTimer, loginCallback, pendingConfirmation;
const clone = x => JSON.parse(JSON.stringify(x));
const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const category = id => state.config.categories.find(c => c.id === id) || (state.config.archived_categories || []).find(c => c.id === id) || {id,name:'Removed layer',color:'#7c8b99',symbol:'?',aliases:[]};
const selectedObject = () => state.objects.find(o=>o.id===state.selected);
const date = s => new Date(s).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});

function setTheme(theme) {
  document.documentElement.dataset.theme=theme;
  try{localStorage.setItem('freia-theme',theme);}catch{}
  updateThemeButton();
}
function updateThemeButton() {
  const dark=document.documentElement.dataset.theme==='midnight';
  $('#theme-btn').setAttribute('aria-pressed',String(dark));
  $('#theme-btn').title=dark?'Switch to light theme':'Switch to midnight theme';
  $('#theme-label').textContent=dark?'Light mode':'Midnight';
}
function confirmNear(anchor, message, {title='Discard changes?',accept='Discard',cancel='Keep editing'}={}) {
  if(pendingConfirmation)pendingConfirmation(false);
  const dialog=$('#confirm-dialog');
  $('#confirm-title').textContent=title;$('#confirm-message').textContent=message;
  $('#confirm-yes').textContent=accept;$('#confirm-no').textContent=cancel;
  return new Promise(resolve=>{
    const finish=answer=>{pendingConfirmation=null;dialog.close();dialog.oncancel=null;resolve(answer);if(anchor?.isConnected)anchor.focus();};
    pendingConfirmation=finish;
    $('#confirm-yes').onclick=()=>finish(true);$('#confirm-no').onclick=()=>finish(false);
    dialog.oncancel=e=>{e.preventDefault();finish(false);};
    dialog.showModal();
    const r=anchor?.getBoundingClientRect?.() || $('#detail-panel').getBoundingClientRect();
    const box=dialog.getBoundingClientRect(),margin=12;
    dialog.style.left=Math.max(margin,Math.min(window.innerWidth-box.width-margin,r.right-box.width))+'px';
    const above=r.top-box.height-10;
    dialog.style.top=Math.max(margin,Math.min(window.innerHeight-box.height-margin,above>=margin?above:r.bottom+10))+'px';
    $('#confirm-no').focus();
  });
}
function clearDraft() {
  if(state.exitEditAfterDraft)state.edit=false;
  state.exitEditAfterDraft=false;state.draft=null;state.tool=null;state.drawing=[];state.hover=null;
}
function circleRadius(g){return Math.hypot(g.points[1][0]-g.points[0][0],g.points[1][1]-g.points[0][1]);}
function slotMetrics(g) {
  const [a,b,w]=g.points,dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
  const n=length?[-dy/length,dx/length]:[0,1];
  return {a,b,n,length,r:w?Math.abs((w[0]-a[0])*n[0]+(w[1]-a[1])*n[1]):0,mid:[(a[0]+b[0])/2,(a[1]+b[1])/2]};
}
function geometryBounds(g) {
  const points=g.type==='circle'?[g.points[0]]:g.type==='slot'?g.points.slice(0,2):g.points;
  const r=g.type==='circle'?circleRadius(g):g.type==='slot'?slotMetrics(g).r:0;
  return [Math.min(...points.map(p=>p[0]))-r,Math.min(...points.map(p=>p[1]))-r,Math.max(...points.map(p=>p[0]))+r,Math.max(...points.map(p=>p[1]))+r];
}
function slotPath(g) {
  const {a,b,n,r}=slotMetrics(g),off=(p,sign)=>[p[0]+sign*n[0]*r,p[1]+sign*n[1]*r].join(',');
  return `M${off(a,1)} L${off(b,1)} A${r},${r} 0 0 0 ${off(b,-1)} L${off(a,-1)} A${r},${r} 0 0 0 ${off(a,1)} Z`;
}
function boundedRadius(points,r) {return Math.max(0,Math.min(r,...points.flatMap(p=>[p[0],p[1],state.config.width-p[0],state.config.height-p[1]])));}
function circleEdge(center,edge){const dx=edge[0]-center[0],dy=edge[1]-center[1],length=Math.hypot(dx,dy),r=boundedRadius([center],length);return length?[center[0]+dx*r/length,center[1]+dy*r/length]:center.slice();}
function canonicalSlot(g, radius) {const m=slotMetrics(g),r=boundedRadius([m.a,m.b],radius ?? m.r);return {type:'slot',points:[m.a.slice(),m.b.slice(),[m.mid[0]+m.n[0]*r,m.mid[1]+m.n[1]*r]]};}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2),value);
    else if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'style') {for(const [property,v] of Object.entries(value)) {if(property.startsWith('--'))node.style.setProperty(property,v);else node.style[property]=v;}}
    else if (value !== null && value !== false) node.setAttribute(key,value === true ? '' : value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
function svgEl(tag, attrs={}) {const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,String(v));return n;}
function toast(message) {$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4500);}
async function api(path, options={}) {
  const res = await fetch('/api'+path, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json',...options.headers},body:options.body ? JSON.stringify(options.body) : undefined});
  let body; try {body=await res.json();} catch {throw new Error('The server returned an unexpected response.');}
  if (!res.ok) {const err=new Error(body.error || 'Request failed.');err.status=res.status;err.current=body.current;throw err;}
  return body;
}
function matches(obj) {
  if (!state.query.trim()) return true;
  const c=category(obj.category);
  const haystack=norm([obj.title,obj.description,c.name,...c.aliases,...obj.tags,...obj.details.flatMap(r=>[r.label,r.value]),...obj.links.map(l=>l.label)].join(' '));
  return norm(state.query).trim().split(/\s+/).every(t=>haystack.includes(t));
}
function visibleObjects() {return state.objects.filter(o=>!o.deleted && state.categories.has(o.category));}
function matchedObjects() {return visibleObjects().filter(matches);}
function renderCategories() {
  $('#categories').replaceChildren(...state.config.categories.map(c=>{
    const input=el('input',{type:'checkbox','aria-label':c.name,onchange:()=>{input.checked?state.categories.add(c.id):state.categories.delete(c.id);renderResults();renderMap();}});
    input.checked=state.categories.has(c.id);
    return el('label',{class:'layer-row'},input,el('span',{class:'layer-dot',style:{background:c.color}}),c.name,el('span',{class:'layer-count'},state.objects.filter(o=>!o.deleted&&o.category===c.id).length));
  }));
}
function renderResults() {
  const results=matchedObjects();
  $('#results-heading').textContent=state.query.trim()?'Search results':'Objects';$('#result-count').textContent=results.length;
  $('#results').replaceChildren(...(results.length?results.map(o=>{
    const c=category(o.category);
    return el('button',{class:'result'+(o.id===state.selected?' selected':''),role:'listitem',onclick:()=>selectObject(o,true)},el('span',{class:'result-symbol',style:{'--color':c.color}},c.symbol),el('span',{},el('strong',{},o.title),el('small',{},c.name+' · '+(o.status==='sample'?'Sample':o.geometry.type))));
  }):[el('div',{class:'no-results'},'No matching objects. Try another search or enable more layers.')]));
}
function setView(view) {
  state.view=view;$('#map').setAttribute('viewBox',view.join(' '));renderMap();
}
function fitMap() {setView([0,0,state.config.width,state.config.height]);}
function zoom(factor, anchor) {
  const [x,y,w,h]=state.view;
  const nw=Math.max(60,Math.min(state.config.width*3,w*factor)), nh=h*nw/w;
  const point=anchor || [x+w/2,y+h/2];
  setView([point[0]-(point[0]-x)*nw/w,point[1]-(point[1]-y)*nh/h,nw,nh]);
}
function centreObject(o) {
  const [minx,miny,maxx,maxy]=geometryBounds(o.geometry),ratio=state.view[2]/state.view[3];
  const w=Math.max(270,(maxx-minx)*1.6,(maxy-miny)*ratio*1.6),h=w/ratio;
  setView([(minx+maxx-w)/2,(miny+maxy-h)/2,w,h]);
}
function screenUnit() {
  const matrix=$('#map').getScreenCTM();
  return matrix?1/Math.sqrt(matrix.a*matrix.a+matrix.b*matrix.b):1;
}
function geometryNode(geometry, color, selected=false, draft=false) {
  const pts=geometry.points, u=screenUnit();let node;
  const attrs={stroke:color,'stroke-width':selected?3:2,'vector-effect':'non-scaling-stroke',fill:color,'fill-opacity':selected?.19:.10,'stroke-linejoin':'round'};
  if(geometry.type==='point') {
    node=svgEl('g');
    if(selected) node.append(svgEl('circle',{cx:pts[0][0],cy:pts[0][1],r:17*u,fill:color,'fill-opacity':.14,stroke:color,'stroke-width':1,'vector-effect':'non-scaling-stroke'}));
    node.append(svgEl('circle',{cx:pts[0][0],cy:pts[0][1],r:10*u,fill:color,stroke:'white','stroke-width':2.5,'vector-effect':'non-scaling-stroke'}));
    const t=svgEl('text',{x:pts[0][0],y:pts[0][1]+.5*u,'text-anchor':'middle','dominant-baseline':'central',fill:'white','font-size':9*u,'font-weight':'700','pointer-events':'none'});
    t.textContent=category((state.draft&&draft?state.draft.category:geometry.category)||'area')?.symbol||'•';
    node.append(t);
  } else if(geometry.type==='circle') {
    node=svgEl('circle',{...attrs,cx:pts[0][0],cy:pts[0][1],r:circleRadius(geometry)});
  } else if(geometry.type==='slot') {
    node=svgEl('path',{...attrs,d:slotPath(geometry)});
  } else if(geometry.type==='rectangle') {
    node=svgEl('rect',{...attrs,x:Math.min(pts[0][0],pts[1][0]),y:Math.min(pts[0][1],pts[1][1]),width:Math.abs(pts[0][0]-pts[1][0]),height:Math.abs(pts[0][1]-pts[1][1])});
  } else {
    node=svgEl(geometry.type==='polygon'?'polygon':'polyline',{...attrs,points:pts.map(p=>p.join(',')).join(' '),fill:geometry.type==='line'?'none':color});
  }
  if(draft) node.setAttribute('stroke-dasharray','5 3');
  return node;
}
function renderMap() {
  if(!state.config)return;
  const layer=$('#objects-layer'),draftLayer=$('#draft-layer'),handles=$('#handles-layer');layer.replaceChildren();draftLayer.replaceChildren();handles.replaceChildren();
  const u=screenUnit();
  const ordered=visibleObjects().filter(o=>!state.draft||o.id!==state.draft.id).sort((a,b)=>(a.geometry.type==='point')-(b.geometry.type==='point'));
  // Selected objects appear above other shapes.
  ordered.sort((a,b)=>(a.id===state.selected)-(b.id===state.selected));
  for(const o of ordered) {
    const c=category(o.category),selected=o.id===state.selected;
    const g=svgEl('g',{'data-id':o.id,class:'shape',opacity:matches(o)?1:.18});
    const title=svgEl('title');title.textContent=o.title;g.append(title);
    g.append(geometryNode({...o.geometry,category:o.category},c.color,selected));
    if(o.geometry.type==='line') g.append(svgEl('polyline',{points:o.geometry.points.map(p=>p.join(',')).join(' '),fill:'none',stroke:'transparent','stroke-width':16,'vector-effect':'non-scaling-stroke'}));
    if(state.labels||selected) {
      const p=o.geometry.points[0],t=svgEl('text',{x:p[0]+14*u,y:p[1]-12*u,class:'shape-label','font-size':10*u});
      t.style.fontSize=(10*u)+'px';t.style.strokeWidth=(3*u)+'px';t.textContent=o.title;g.append(t);
    }
    layer.append(g);
  }
  if(state.draft) {
    const d=state.draft,c=category(d.category),g=svgEl('g',{'data-draft':'true',class:'draft-shape'});
    g.append(geometryNode({...d.geometry,category:d.category},c.color,true,true));draftLayer.append(g);
    d.geometry.points.forEach((p,i)=>handles.append(svgEl('circle',{cx:p[0],cy:p[1],r:6*u,class:'vertex-handle','data-vertex':i})));
  }
  if(state.tool&&state.drawing.length) {
    const pts=clone(state.drawing);if(state.hover)pts.push(state.hover);
    if(state.tool==='rectangle'&&pts.length>=2)draftLayer.append(geometryNode({type:'rectangle',points:[pts[0],pts[pts.length-1]]},'#087f83',false,true));
    else if(state.tool==='circle'&&pts.length>=2)draftLayer.append(geometryNode({type:'circle',points:[pts[0],circleEdge(pts[0],pts[pts.length-1])]},'#087f83',false,true));
    else if(state.tool==='slot'&&pts.length>=3)draftLayer.append(geometryNode(canonicalSlot({type:'slot',points:pts.slice(0,3)}),'#087f83',false,true));
    else if(pts.length>1)draftLayer.append(geometryNode({type:'line',points:pts},'#087f83',false,true));
    for(const p of state.drawing) handles.append(svgEl('circle',{cx:p[0],cy:p[1],r:4*u,fill:'white',stroke:'#087f83','stroke-width':2,'vector-effect':'non-scaling-stroke'}));
  }
}
async function discardDraft(anchor=document.activeElement) {
  if(state.busy)return false;
  if(state.draft&&!await confirmNear(anchor,'Discard this unsaved object draft? Your last saved version will remain unchanged.'))return false;
  clearDraft();return true;
}
async function selectObject(o, centre=false) {
  if(state.draft&&!await discardDraft())return;
  state.selected=o.id;state.tool=null;state.drawing=[];updateToolbar();renderResults();renderMap();renderDetails();
  if(centre)centreObject(o);
  history.replaceState(null,'','#object='+encodeURIComponent(o.id));
}
async function closeDetails(event) {
  if(!await discardDraft(event?.currentTarget||document.activeElement))return;
  state.selected=null;$('#detail-panel').classList.remove('open');renderResults();renderMap();renderDetails();updateToolbar();history.replaceState(null,'',location.pathname);
}
function renderDetails() {
  state.historyToken++;
  const panel=$('#detail-panel');
  if(state.draft){panel.classList.add('open');renderEditor();return;}
  const o=selectedObject();
  if(!o) {
    panel.replaceChildren(el('div',{class:'empty-details'},el('span',{class:'empty-icon','aria-hidden':'true'},'↗'),el('div',{class:'eyebrow'},'OBJECT INFORMATION'),el('h2',{},'A place for every detail.'),el('p',{},'Select a marker, shape, or search result to see its information and links.'),el('div',{class:'empty-tip'},'Try searching for ',el('button',{class:'text-button',onclick:tryAir},'pressurized air'),'.')));return;
  }
  panel.classList.add('open');const c=category(o.category);
  const header=el('div',{class:'detail-header'},el('div',{class:'detail-topline'},el('span',{class:'category-pill',style:{'--color':c.color}},el('i'),c.name),el('button',{class:'icon-button','aria-label':'Close object',onclick:closeDetails},'×')),el('h2',{},o.title),el('span',{class:'status '+(o.deleted?'deleted':o.status)},o.deleted?'Deleted — recoverable':statusName(o.status)));
  const body=el('div',{class:'detail-body'},el('p',{class:'description'},o.description||'No description added.'));
  if(o.details.length){const dl=el('dl',{class:'details-table'});for(const r of o.details)dl.append(el('dt',{},r.label),el('dd',{},r.value));body.append(dl);}
  if(o.links.length)body.append(el('h3',{},'Related links'),...o.links.map(l=>el('a',{class:'link-card',href:l.url,target:'_blank',rel:'noopener noreferrer'},l.label,el('span',{'aria-hidden':'true'},'↗'))));
  if(o.tags.length)body.append(el('h3',{},'Keywords'),el('div',{class:'tags'},...o.tags.map(t=>el('span',{class:'tag'},t))));
  const meta=el('div',{class:'detail-meta'},'Revision '+o.version+' · '+o.geometry.type,el('br'),'Updated '+date(o.updated_at),el('br'),'By '+o.updated_by);
  const actions=el('div',{class:'detail-actions'});
  if(!o.deleted)actions.append(el('button',{class:'primary',onclick:()=>requireLogin(()=>startEditing(o))},'Edit object'));
  actions.append(el('button',{class:'secondary',onclick:()=>loadHistory(o)},'History'),el('button',{class:'secondary',onclick:()=>copyLink(o)},'Copy link'));
  meta.append(actions);body.append(meta);panel.replaceChildren(header,body,el('div',{class:'history-section',id:'object-history',hidden:true}));
  if(o.deleted)loadHistory(o);
}
function statusName(s){return {'sample':'Sample — invented data','unverified':'Needs verification','verified':'Verified','out-of-service':'Out of service'}[s]||s;}
async function copyLink(o){const link=location.origin+location.pathname+'#object='+encodeURIComponent(o.id);try{await navigator.clipboard.writeText(link);toast('Object link copied.');}catch{prompt('Copy this object link:',link);}}
async function loadHistory(o) {
  const token=++state.historyToken,box=$('#object-history');if(!box)return;box.hidden=false;box.replaceChildren(el('h3',{},'Object history'),el('p',{class:'muted'},'Loading revisions…'));
  try {
    const data=await api('/objects/'+encodeURIComponent(o.id)+'/history');
    if(token!==state.historyToken||state.draft)return;
    const latest=selectedObject();
    box.replaceChildren(el('h3',{},'Object history'),...data.revisions.map(r=>{
      const rev=el('div',{class:'revision'},el('strong',{},'Revision '+r.version+' · '+r.action.replace(':',' ')),el('p',{},date(r.changed_at)+' · '+r.changed_by));
      if(r.version===latest.version)rev.append(el('span',{class:'current-revision'},'Current'));
      const content=el('details',{},el('summary',{},'View saved information and geometry'),el('pre',{},JSON.stringify(r.payload,null,2)));rev.append(content);
      if(!r.deleted&&r.version!==latest.version)rev.append(el('button',{onclick:()=>requireLogin(()=>restoreObject(latest,r.version))},'Restore this revision'));
      return rev;
    }));
  }catch(e){box.replaceChildren(el('p',{class:'error'},e.message));}
}
async function restoreObject(o, version) {
  if(!await confirmNear(document.activeElement,'Restore revision '+version+' of “'+o.title+'”? This creates a new revision.',{title:'Restore revision?',accept:'Restore',cancel:'Cancel'}))return;
  try{const current=await api('/objects/'+o.id+'/restore',{method:'POST',body:{version:o.version,restore_version:version}});replaceObject(current);renderAll();loadHistory(current);toast('Revision restored.');}catch(e){toast(e.message);if(e.status===409)refresh();}
}
function replaceObject(o){const i=state.objects.findIndex(x=>x.id===o.id);if(i===-1)state.objects.push(o);else state.objects[i]=o;}
function requireLogin(callback){if(state.session?.username){callback();return;}loginCallback=callback;openLogin();}
function openLogin(){const accounts=state.config.auth_mode==='accounts';$('#login-title').textContent=accounts?'Sign in to edit':'Choose a display name';$('#login-description').textContent=accounts?'Use your facility-map account. Changes are attributed to your username.':'Local demo mode: this name labels your changes, but is not a verified identity.';$('#password-label').hidden=!accounts;$('#login-error').textContent='';$('#login-dialog').showModal();$('input[name=username]',$('#login-form')).focus();}
function renderIdentity(){const name=state.session?.username;$('#identity-btn').textContent=name?name+' · Sign out':'Sign in to edit';const banner=$('#demo-banner');banner.replaceChildren(el('span',{class:'notice-dot'}),el('strong',{},'Prototype'),el('span',{},'Sample locations and values are illustrative.'+(state.config.auth_mode==='demo'?' Local demo identities are unverified.':'')));}
async function startEditing(o) {
  if(!await discardDraft())return;
  state.edit=true;state.exitEditAfterDraft=true;state.draft=clone(o);state.selected=o.id;updateToolbar();renderDetails();renderMap();
}
function labelField(label, input, hint) {return el('label',{},label,input,hint?el('div',{class:'form-hint'},hint):null);}
function renderEditor() {
  const d=state.draft;
  const form=el('form',{class:'editor-form',id:'editor-form',onsubmit:saveDraft});
  const title=el('input',{name:'title',value:d.title,required:true,maxlength:180});
  const cats=el('select',{name:'category',id:'object-category',onchange:()=>{d.category=cats.value;renderMap();}});
  cats.append(...state.config.categories.map(c=>el('option',{value:c.id},c.name)));cats.value=d.category;
  const statuses=el('select',{name:'status'});statuses.append(...['unverified','verified','out-of-service','sample'].map(s=>el('option',{value:s},statusName(s))));statuses.value=d.status;
  const description=el('textarea',{name:'description',rows:4,maxlength:10000});description.value=d.description;
  const tags=el('input',{name:'tags',value:d.tags.join(', ')});
  const details=el('textarea',{name:'details',rows:3});details.value=d.details.map(r=>r.label+' | '+r.value).join('\n');
  const links=el('textarea',{name:'links',rows:3});links.value=d.links.map(r=>r.label+' | '+r.url).join('\n');
  form.append(labelField('Name',title),labelField('Category',cats),labelField('Verification status',statuses),labelField('Description',description),labelField('Keywords',tags,'Separate keywords with commas. Category aliases are also searched.'),labelField('Technical details',details,'One per line: label | value'),labelField('Related links',links,'One per line: label | https://address. Internal /paths also work.'),el('p',{class:'error',id:'form-error',role:'alert'}),el('div',{id:'conflict-box',hidden:true}));
  const actions=el('div',{class:'editor-actions'},el('button',{type:'submit',class:'primary',id:'save-btn'},'Save object'),el('button',{type:'button',class:'secondary',onclick:async e=>{if(await discardDraft(e.currentTarget)){renderDetails();renderMap();updateToolbar();}}},'Cancel'));
  form.append(actions);
  if(d.id)form.append(el('button',{type:'button',class:'danger',style:{marginTop:'18px'},onclick:deleteDraft},'Delete object'));
  $('#detail-panel').replaceChildren(el('div',{class:'editor-heading'},el('div',{class:'eyebrow'},d.id?'EDIT OBJECT':'NEW OBJECT'),el('h2',{},d.id?'Update the record':'Mark a place'),el('p',{},'Drag the shape to move it, or drag its white handles to reshape it. Changes take effect when you save.'+(state.exitEditAfterDraft?' Saving or cancelling returns to viewing mode.':''))),form);
  title.focus();
}
function collectDraft() {
  const form=$('#editor-form'), data=new FormData(form);
  const rows=(name,key)=>(data.get(name)||'').split('\n').filter(x=>x.trim()).map(line=>{const split=line.indexOf('|');if(split<1||!line.slice(split+1).trim())throw new Error('Use “label | '+(key==='url'?'address':'value')+'” for each '+name+' line.');return {label:line.slice(0,split).trim(),[key]:line.slice(split+1).trim()};});
  return {...state.draft,title:data.get('title').trim(),category:data.get('category'),status:data.get('status'),description:data.get('description').trim(),tags:data.get('tags').split(',').map(t=>t.trim()).filter(Boolean),details:rows('details','value'),links:rows('links','url')};
}
async function saveDraft(event) {
  event.preventDefault();if(state.busy)return;let data;
  try{data=collectDraft();}catch(e){$('#form-error').textContent=e.message;return;}
  $('#form-error').textContent='';state.busy=true;$('#save-btn').disabled=true;
  try {
    const saved=await api(data.id?'/objects/'+data.id:'/objects',{method:data.id?'PUT':'POST',body:data});
    replaceObject(saved);clearDraft();state.selected=saved.id;renderAll();history.replaceState(null,'','#object='+saved.id);toast('Object saved · revision '+saved.version);
  } catch(e) {
    $('#form-error').textContent=e.message;
    if(e.status===409&&e.current) {
      const latest=e.current;replaceObject(latest);
      const conflict=$('#conflict-box');conflict.hidden=false;conflict.className='conflict';conflict.replaceChildren('Latest: revision '+latest.version+' by '+latest.updated_by+' ('+date(latest.updated_at)+'). Your draft remains open.',el('br'),el('button',{type:'button',class:'text-button',onclick:()=>{const current=collectDraft();const view=JSON.stringify(latest,null,2);alert('Latest saved object:\n\n'+view);if(confirm('Keep your draft and use revision '+latest.version+' as its base? Check the differences before saving.')){if(latest.deleted){toast('The object was deleted. Cancel this draft and restore it from history.');return;}state.draft={...current,version:latest.version};conflict.hidden=true;$('#form-error').textContent='Reviewed latest revision. Save again when ready.';}}},'Review latest revision'));
    }
    if(e.status===401){state.session=null;renderIdentity();}
    if(e.status===400){await refreshLayers();}
  } finally {state.busy=false;if($('#save-btn'))$('#save-btn').disabled=false;}
}
async function deleteDraft() {
  const d=state.draft;if(!d?.id||state.busy)return;
  if(!await confirmNear(document.activeElement,'Delete “'+d.title+'”? The saved record remains recoverable in history.',{title:'Delete object?',accept:'Delete',cancel:'Cancel'}))return;
  state.busy=true;
  try{const saved=await api('/objects/'+d.id,{method:'DELETE',body:{version:d.version}});replaceObject(saved);clearDraft();renderAll();toast('Object deleted. Use history to restore it.');}catch(e){$('#form-error').textContent=e.message;}finally{state.busy=false;}
}
function updateToolbar() {
  $('.map-panel').classList.toggle('editing',state.edit);$('#edit-status').hidden=!state.edit;
  $('#edit-toolbar').hidden=!state.edit;$('#edit-mode-btn').classList.toggle('active',state.edit);$('#edit-mode-btn').textContent=state.edit?'Exit edit mode':'Edit mode';$('#map').classList.toggle('drawing',!!state.tool);
  $$('[data-tool]').forEach(b=>b.classList.toggle('active',b.dataset.tool===state.tool));
  $('#finish-btn').hidden=!['polygon','line'].includes(state.tool);$('#cancel-draw-btn').hidden=!state.tool;
  const help=$('#drawing-help');help.hidden=!state.tool;
  if(state.tool)help.textContent={point:'Click a location to add a point.',rectangle:'Click two opposite corners to draw a rectangle.',circle:'Click the centre, then a point on the circle edge.',slot:'Click two end centres, then click to set the slot width.',polygon:'Click vertices, then Finish shape or Enter. Escape cancels.',line:'Click route points, then Finish shape or Enter. Escape cancels.'}[state.tool];
}
function chooseTool(tool){requireLogin(async()=>{if(!await discardDraft())return;state.edit=true;state.exitEditAfterDraft=false;state.tool=tool;state.selected=null;state.drawing=[];renderDetails();renderResults();renderMap();updateToolbar();});}
function finishDrawing() {
  const minimum={point:1,rectangle:2,line:2,polygon:3,circle:2,slot:3}[state.tool];
  if(state.drawing.length<minimum){toast('Add at least '+minimum+' points.');return;}
  const type=state.tool;let geometry={type,points:clone(state.drawing)};
  if(type==='circle'){geometry.points[1]=circleEdge(geometry.points[0],geometry.points[1]);if(circleRadius(geometry)<.1){toast('Choose a larger circle.');state.drawing.pop();return;}}
  if(type==='slot'){geometry=canonicalSlot(geometry);const m=slotMetrics(geometry);if(m.length<.1||m.r<.1){toast('Choose distinct end centres and a nonzero width.');state.drawing.pop();return;}}
  const preferred=type==='line'?'route':type==='point'?'air':'area';
  const cat=state.config.categories.find(c=>c.id===preferred)?.id||state.config.categories[0].id;
  state.draft={title:'',category:cat,status:'unverified',description:'',tags:[],details:[],links:[],geometry};
  state.exitEditAfterDraft=false;state.tool=null;state.drawing=[];state.hover=null;updateToolbar();renderMap();renderDetails();
}
function mapPoint(event) {const p=$('#map').createSVGPoint();p.x=event.clientX;p.y=event.clientY;const q=p.matrixTransform($('#map').getScreenCTM().inverse());return [q.x,q.y];}
function inPlan(p){return p[0]>=0&&p[1]>=0&&p[0]<=state.config.width&&p[1]<=state.config.height;}
function clamp(p){return [Math.max(0,Math.min(state.config.width,p[0])),Math.max(0,Math.min(state.config.height,p[1]))];}
function mapDown(e) {
  if(e.button!==0||!state.config||state.busy)return;
  const vertex=e.target.closest('[data-vertex]'),draft=e.target.closest('[data-draft]');
  const p=mapPoint(e),map=$('#map');
  state.drag={kind:vertex?'vertex':draft?'object':'pan',index:vertex?Number(vertex.dataset.vertex):null,point:p,client:[e.clientX,e.clientY],view:state.view.slice(),geometry:state.draft?clone(state.draft.geometry):null,moved:false,id:e.target.closest('[data-id]')?.dataset.id};
  map.setPointerCapture(e.pointerId);
}
function mapMove(e) {
  if(!state.config)return;
  if(state.tool){state.hover=clamp(mapPoint(e));scheduleMap(true);}
  const d=state.drag;if(!d)return;
  if(Math.hypot(e.clientX-d.client[0],e.clientY-d.client[1])>4)d.moved=true;
  if(!d.moved)return;
  $('#map').classList.add('dragging');
  if((d.kind==='vertex'||d.kind==='object')&&state.draft){
    const p=mapPoint(e),g=d.geometry;
    if(d.kind==='object'||(g.type==='circle'&&d.index===0)){
      let dx=p[0]-d.point[0],dy=p[1]-d.point[1];const [x0,y0,x1,y1]=geometryBounds(g);
      dx=Math.max(-x0,Math.min(state.config.width-x1,dx));dy=Math.max(-y0,Math.min(state.config.height-y1,dy));
      state.draft.geometry.points=g.points.map(q=>[q[0]+dx,q[1]+dy]);
    }else if(g.type==='circle')state.draft.geometry.points[1]=circleEdge(g.points[0],p);
    else if(g.type==='slot'){
      let next=clone(g),m=slotMetrics(g);
      if(d.index<2){next.points[d.index]=[Math.max(m.r,Math.min(state.config.width-m.r,p[0])),Math.max(m.r,Math.min(state.config.height-m.r,p[1]))];next=canonicalSlot(next,m.r);}
      else {next.points[2]=clamp(p);next=canonicalSlot(next);}
      state.draft.geometry=next;
    }else state.draft.geometry.points[d.index]=clamp(p);
    scheduleMap(true);
  }else if(d.kind==='pan'){const matrix=$('#map').getScreenCTM();const u=1/matrix.a;setView([d.view[0]-(e.clientX-d.client[0])*u,d.view[1]-(e.clientY-d.client[1])*u,d.view[2],d.view[3]]);}
}
function mapUp(e) {
  const d=state.drag;state.drag=null;$('#map').classList.remove('dragging');
  if($('#map').hasPointerCapture(e.pointerId))$('#map').releasePointerCapture(e.pointerId);
  if(!d||d.moved||d.kind!=='pan')return;
  if(state.tool){const p=mapPoint(e);if(!inPlan(p)){toast('Place the object inside the plan.');return;}state.drawing.push(p);if(state.tool==='point'||(['rectangle','circle'].includes(state.tool)&&state.drawing.length===2)||(state.tool==='slot'&&state.drawing.length===3))finishDrawing();else renderMap();}
  else if(d.id){const o=state.objects.find(o=>o.id===d.id);if(o)selectObject(o);}
}
function tryAir(){$('#search').value='pressurized air';state.query='pressurized air';state.categories.add('air');renderCategories();renderResults();renderMap();const objects=matchedObjects();if(objects.length){const pts=objects.flatMap(o=>o.geometry.points);const xmin=Math.min(...pts.map(p=>p[0])),xmax=Math.max(...pts.map(p=>p[0])),ymin=Math.min(...pts.map(p=>p[1])),ymax=Math.max(...pts.map(p=>p[1]));const w=Math.max(400,(xmax-xmin)*1.4,(ymax-ymin)*2.8);setView([(xmin+xmax-w)/2,(ymin+ymax-w/2)/2,w,w/2]);}}
function renderAll(){renderCategories();renderResults();renderMap();updateToolbar();renderDetails();}
async function refresh(silent=false) {
  if(state.draft||state.layerDraft||state.busy)return;
  const token=++state.dataToken, previousVersion=selectedObject()?.version;
  try{await refreshLayers();const data=await api('/objects');if(token!==state.dataToken||state.draft)return;const deletedSelected=selectedObject()?.deleted?selectedObject():null;state.objects=data.objects;if(deletedSelected&&!state.objects.some(o=>o.id===deletedSelected.id))state.objects.push(deletedSelected);
    // Retrieve the selected record even if another user has just deleted it.
    if(state.selected&&!state.objects.some(o=>o.id===state.selected)){try{replaceObject(await api('/objects/'+state.selected));}catch{state.selected=null;}}
    state.offline=false;$('#sync-status').textContent='Synced '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});$('#sync-status').classList.remove('offline');renderCategories();renderResults();renderMap();if(!silent||previousVersion!==selectedObject()?.version)renderDetails();
  }catch(e){state.offline=true;$('#sync-status').textContent='Disconnected';$('#sync-status').classList.add('offline');if(!silent)toast('Cannot reach the server. '+e.message);}
}
async function showActivity() {
  $('#activity-dialog').showModal();$('#activity-list').replaceChildren(el('p',{class:'muted'},'Loading changes…'));
  try{const data=await api('/activity');$('#activity-list').replaceChildren(...data.activity.map(r=>el('button',{class:'activity-row',onclick:async()=>{if(state.draft&&!await discardDraft())return;try{const o=await api('/objects/'+r.object_id);replaceObject(o);$('#activity-dialog').close();await selectObject(o,true);loadHistory(o);}catch(e){toast(e.message);}}},el('span',{},el('strong',{},r.title),el('small',{},r.changed_by+' · '+date(r.changed_at))),el('span',{},r.action.replace(':',' ')+' · v'+r.version))));}catch(e){$('#activity-list').replaceChildren(el('p',{class:'error'},e.message));}
}
async function refreshLayers() {
  const config=await api('/config'),previous=new Set(state.config.categories.map(c=>c.id));
  const changed=JSON.stringify(config.categories)!==JSON.stringify(state.config.categories);
  state.config=config;
  for(const id of [...state.categories])if(!config.categories.some(c=>c.id===id))state.categories.delete(id);
  for(const c of config.categories)if(!previous.has(c.id))state.categories.add(c.id);
  const selector=$('#object-category');
  if(changed&&selector){const current=selector.value;selector.replaceChildren(...config.categories.map(c=>el('option',{value:c.id},c.name)));if(!config.categories.some(c=>c.id===current))selector.append(el('option',{value:current,disabled:true},category(current).name+' — removed; choose a layer'));selector.value=current;}
  if(changed){renderCategories();renderResults();renderMap();}
  return changed;
}
async function openLayers() {
  if(!await discardDraft())return;
  renderDetails();renderMap();updateToolbar();state.layerDraft=null;$('#layer-editor').hidden=true;
  const dialog=$('#layers-dialog');if(!dialog.open)dialog.showModal();
  await loadLayerManager();
}
async function loadLayerManager() {
  try {
    const data=await api('/layers');state.layerStats=data.layers;
    const active=data.layers.filter(c=>!c.deleted);
    $('#layers-list').replaceChildren(...active.map(c=>el('div',{class:'layer-manager-row'},el('span',{class:'result-symbol',style:{'--color':c.color}},c.symbol),el('div',{class:'layer-manager-info'},el('strong',{},c.name),el('small',{},c.object_count+' objects'+(c.deleted_object_count?' · '+c.deleted_object_count+' recoverable':'')+' · revision '+c.version)),el('button',{class:'text-button',onclick:()=>editLayer(c)},'Edit'),el('button',{class:'text-button remove-layer',disabled:active.length<=1,title:active.length<=1?'Keep at least one layer':'Remove this layer',onclick:()=>removeLayer(c)},'Remove'))));
  }catch(e){$('#layers-list').replaceChildren(el('p',{class:'error'},e.message));}
}
async function discardLayerDraft(anchor=document.activeElement) {
  if(state.busy)return false;
  if(state.layerDraft&&!await confirmNear(anchor,'Discard the unsaved layer changes?',{title:'Discard layer changes?'}))return false;
  state.layerDraft=null;$('#layer-editor').hidden=true;return true;
}
async function closeLayers(event) {
  if(!await discardLayerDraft(event?.currentTarget||document.activeElement))return;
  $('#layers-dialog').close();
}
async function editLayer(layer) {
  if(!await discardLayerDraft())return;
  state.layerDraft=layer?clone(layer):{name:'',color:'#168ca5',symbol:'•',aliases:[]};
  const d=state.layerDraft,container=$('#layer-editor');container.hidden=false;
  const form=el('form',{id:'layer-form',class:'layer-form',onsubmit:saveLayer});
  const aliases=el('input',{name:'aliases',value:d.aliases.join(', ')});
  form.append(el('h3',{},layer?'Edit layer':'Add a layer'),labelField('Layer name',el('input',{name:'name',value:d.name,required:true,maxlength:100})),el('div',{class:'layer-field-row'},labelField('Colour',el('input',{name:'color',type:'color',value:d.color,required:true})),labelField('Marker symbol',el('input',{name:'symbol',value:d.symbol,required:true,maxlength:3}), 'One to three characters.')),labelField('Search aliases',aliases,'Separate aliases with commas. Objects in this layer inherit these search terms.'),el('p',{id:'layer-error',class:'error',role:'alert'}),el('div',{class:'dialog-actions'},el('button',{type:'button',class:'secondary',onclick:async e=>{await discardLayerDraft(e.currentTarget);}},'Cancel'),el('button',{type:'submit',class:'primary'},'Save layer')));
  container.replaceChildren(form);$('input[name=name]',form).focus();
}
async function saveLayer(event) {
  event.preventDefault();if(state.busy)return;
  const values=new FormData(event.target),d=state.layerDraft;
  const payload={name:values.get('name').trim(),color:values.get('color'),symbol:values.get('symbol').trim(),aliases:values.get('aliases').split(',').map(a=>a.trim()).filter(Boolean),version:d.version};
  const submit=$('button[type=submit]',event.target);submit.disabled=true;state.busy=true;
  try {
    await api(d.id?'/layers/'+d.id:'/layers',{method:d.id?'PUT':'POST',body:payload});
    state.layerDraft=null;$('#layer-editor').hidden=true;await refreshLayers();await loadLayerManager();state.busy=false;await refresh(true);toast('Layer saved.');
  }catch(e){$('#layer-error').textContent=e.message;if(e.status===409){await loadLayerManager();$('#layer-error').append(el('br'),el('button',{type:'button',class:'text-button',onclick:()=>editLayer(state.layerStats.find(l=>l.id===d.id))},'Reload latest layer (discards this draft)'));}}finally{state.busy=false;submit.disabled=false;}
}
async function removeLayer(layer) {
  if(!await discardLayerDraft())return;
  state.layerDraft={...clone(layer),removing:true};
  const container=$('#layer-editor');container.hidden=false;
  const count=layer.object_count+layer.deleted_object_count;
  const targets=state.config.categories.filter(c=>c.id!==layer.id);
  const select=el('select',{name:'replacement',required:count>0});select.append(el('option',{value:''},count?'Choose a destination layer':'No reassignment needed'),...targets.map(c=>el('option',{value:c.id},c.name)));
  const form=el('form',{class:'layer-form',onsubmit:async e=>{
    e.preventDefault();if(state.busy)return;
    const destination=select.value||null;
    if(!await confirmNear($('button[type=submit]',form),'Remove “'+layer.name+'”?'+(count?' Its objects will move to the chosen layer, with their histories preserved.':' No objects will be deleted.'),{title:'Remove layer?',accept:'Remove layer',cancel:'Cancel'}))return;
    const submit=$('button[type=submit]',form);submit.disabled=true;state.busy=true;
    try{const result=await api('/layers/'+layer.id,{method:'DELETE',body:{version:layer.version,replacement_id:destination}});state.layerDraft=null;container.hidden=true;await refreshLayers();await loadLayerManager();state.busy=false;await refresh();toast('Layer removed'+(result.moved_objects?' · '+result.moved_objects+' records reassigned.':'.'));}catch(err){$('#layer-error').textContent=err.message;await loadLayerManager();}finally{state.busy=false;submit.disabled=false;}
  }});
  form.append(el('h3',{},'Remove '+layer.name),el('p',{class:'muted'},count?'This layer has '+count+' records, including deleted records that can be recovered. Choose where to move them.':'This layer currently has no records. Its previous layer definitions remain in the change history.'),labelField('Move records to',select),el('p',{id:'layer-error',class:'error',role:'alert'}),el('div',{class:'dialog-actions'},el('button',{type:'button',class:'secondary',onclick:async e=>{await discardLayerDraft(e.currentTarget);}},'Cancel'),el('button',{type:'submit',class:'danger'},'Remove layer')));container.replaceChildren(form);select.focus();
}

async function exportData(){try{const data=await api('/export');const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=el('a',{href:url,download:'freia-map-'+new Date().toISOString().slice(0,10)+'.json'});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Objects and revision history exported.');}catch(e){toast(e.message);}}
function bindEvents(){
  updateThemeButton();$('#theme-select').onchange=e=>setTheme(e.target.value);$('#plan-theme').onchange=e=>setPlanTheme(e.target.value);
  $('#manage-layers').onclick=()=>requireLogin(openLayers);$('#layers-close').onclick=closeLayers;$('#layers-dialog').addEventListener('cancel',e=>{e.preventDefault();closeLayers();});$('#new-layer').onclick=()=>editLayer(null);
  $('#search').addEventListener('input',e=>{state.query=e.target.value;renderResults();renderMap();});
  $('#all-layers').onclick=()=>{state.config.categories.forEach(c=>state.categories.add(c.id));renderCategories();renderResults();renderMap();};
  $('#labels-btn').onclick=()=>{state.labels=!state.labels;$('#labels-btn').classList.toggle('active',state.labels);$('#labels-btn').setAttribute('aria-pressed',state.labels);renderMap();};
  $('#edit-mode-btn').onclick=async e=>{if(state.edit){if(!await settleDraft(e.currentTarget))return;state.edit=false;state.explicitEdit=false;renderDetails();renderMap();updateToolbar();}else requireLogin(()=>{state.edit=true;state.explicitEdit=true;updateToolbar();});};
  $$('[data-tool]').forEach(b=>b.onclick=()=>chooseTool(b.dataset.tool));
  $('#finish-btn').onclick=finishDrawing;
  $('#cancel-draw-btn').onclick=()=>{state.tool=null;state.drawing=[];state.hover=null;renderMap();updateToolbar();};
  $('#zoom-in').onclick=()=>zoom(.8);$('#zoom-out').onclick=()=>zoom(1.25);$('#fit-map').onclick=fitMap;
  $('#map').addEventListener('pointerdown',mapDown);$('#map').addEventListener('pointermove',mapMove);$('#map').addEventListener('pointerup',mapUp);
  $('#map').addEventListener('pointercancel',()=>{state.drag=null;$('#map').classList.remove('dragging');});
  $('#map').addEventListener('wheel',e=>{e.preventDefault();if(state.config)zoom(e.deltaY>0?1.12:.89,mapPoint(e));},{passive:false});
  $('#map').addEventListener('keydown',e=>{if(e.key==='+'||e.key==='='){e.preventDefault();zoom(.8);}if(e.key==='-'){e.preventDefault();zoom(1.25);}if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const [x,y,w,h]=state.view;setView([x+({'ArrowLeft':-.08,'ArrowRight':.08}[e.key]||0)*w,y+({'ArrowUp':-.08,'ArrowDown':.08}[e.key]||0)*h,w,h]);}});
  document.addEventListener('keydown',e=>{if(e.target.closest('input,textarea,select,dialog'))return;if(e.key==='Escape'&&state.tool){state.tool=null;state.drawing=[];renderMap();updateToolbar();}if(e.key==='Enter'&&state.tool){e.preventDefault();finishDrawing();}});
  window.addEventListener('beforeunload',e=>{if(draftIsDirty()||state.layerDraft){e.preventDefault();e.returnValue='';}});
  $('#try-air').onclick=tryAir;$('#refresh-btn').onclick=()=>{if(state.draft){toast('Save or cancel your draft before refreshing.');return;}refresh();};
  $('#activity-btn').onclick=showActivity;$('#activity-close').onclick=()=>$('#activity-dialog').close();$('#export-btn').onclick=exportData;
  $('#identity-btn').onclick=async()=>{if(state.session?.username){if(!await discardDraft())return;try{await api('/session',{method:'DELETE'});state.session=null;state.edit=false;state.explicitEdit=false;renderIdentity();renderDetails();renderMap();updateToolbar();toast('Signed out.');}catch(e){toast(e.message);}}else{loginCallback=null;openLogin();}};
  $('#login-cancel').onclick=()=>{loginCallback=null;$('#login-dialog').close();};
  $('#login-form').onsubmit=async e=>{e.preventDefault();const form=e.target,data=new FormData(form),submit=$('button[type=submit]',form);submit.disabled=true;try{state.session=await api('/session',{method:'POST',body:{username:data.get('username'),password:data.get('password')}});$('#login-dialog').close();$('input[name=password]',form).value='';renderIdentity();const callback=loginCallback;loginCallback=null;if(callback)callback();else toast('Ready to edit as '+state.session.username+'.');}catch(err){$('#login-error').textContent=err.message;}finally{submit.disabled=false;}};
  new ResizeObserver(()=>{if(state.config)resizeMap();}).observe($('#map-viewport'));
  window.addEventListener('hashchange',async()=>{const id=new URLSearchParams(location.hash.slice(1)).get('object');if(id){try{const o=await api('/objects/'+encodeURIComponent(id));replaceObject(o);selectObject(o,true);}catch(e){toast(e.message);}}});
}
async function init(){
  bindEvents();
  try {
    state.config=await api('/config');state.categories=new Set(state.config.categories.map(c=>c.id));state.session=await api('/session');renderIdentity();
    const img=$('#plan-image');img.addEventListener('load',()=>$('#map-loading').hidden=true);img.addEventListener('error',()=>{$('#map-loading').textContent='The plan could not load. Check static/assets/plan.svg.';});
    // A separate image confirms loading even if SVG image events are inconsistent.
    const check=new Image();check.onload=()=>$('#map-loading').hidden=true;check.onerror=()=>$('#map-loading').textContent='The facility plan could not load.';check.src=state.config.plan_url;
    await refresh();
    const id=new URLSearchParams(location.hash.slice(1)).get('object');if(id){try{const o=await api('/objects/'+encodeURIComponent(id));replaceObject(o);await selectObject(o,true);}catch(e){toast(e.message);}}
    setInterval(()=>{if(!document.hidden)refresh(true);},15000);
  }catch(e){$('#map-loading').textContent='Start the Python server and open http://127.0.0.1:8000.';$('#sync-status').textContent='Disconnected';toast(e.message);}
}
// v03.js adds the upgraded workflows, then starts the application.
