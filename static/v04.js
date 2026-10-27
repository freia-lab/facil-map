'use strict';
Object.assign(state,{grid:false,measure:false,measurePoints:[],pointer:null,setup:null,placingCopy:false,activeVertex:null});
const settings=()=>state.config?.map_settings;
const metric=()=>settings()?.metres_per_pixel;
const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
function rowLetter(n){let s='';for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function zone(p){const m=metric();if(!m)return '';const o=settings().grid_origin,s=2/m,c=Math.floor((p[0]-o[0])/s),r=Math.floor((p[1]-o[1])/s);return c>=0&&r>=0?rowLetter(r)+(c+1):'Outside grid';}
function similarity(source,target){
 if(source.length<2||target.length<2||dist(source[0],source[1])<1||dist(target[0],target[1])<1)throw new Error('Choose two distinct, well-separated reference points.');
 const u=[source[1][0]-source[0][0],source[1][1]-source[0][1]],v=[target[1][0]-target[0][0],target[1][1]-target[0][1]],den=u[0]**2+u[1]**2;
 const a=(u[0]*v[0]+u[1]*v[1])/den,b=(u[0]*v[1]-u[1]*v[0])/den;
 return [a,b,-b,a,target[0][0]-a*source[0][0]+b*source[0][1],target[0][1]-b*source[0][0]-a*source[0][1]];
}
function transformPoint(p,t){return [t[0]*p[0]+t[2]*p[1]+t[4],t[1]*p[0]+t[3]*p[1]+t[5]];}
function inversePoint(p,t){const d=t[0]*t[3]-t[1]*t[2];return [(t[3]*(p[0]-t[4])-t[2]*(p[1]-t[5]))/d,(-t[1]*(p[0]-t[4])+t[0]*(p[1]-t[5]))/d];}
function planAppearance(){
 const f=floorList().find(f=>f.id===state.floor);if(!f)return;
 const image=$('#plan-image'),replacement=state.setup?.replacement,active=replacement||f;
 image.setAttribute('href',active.plan_url);image.setAttribute('width',active.image_width||state.config.width);image.setAttribute('height',active.image_height||state.config.height);image.setAttribute('preserveAspectRatio','none');image.setAttribute('transform','matrix('+(active.transform||[1,0,0,1,0,0]).join(' ')+')');
}
const floor04=setFloorDirect;setFloorDirect=function(id){floor04(id);planAppearance();state.measurePoints=[];};
function overlayText(g,text,x,y,u,anchor='middle'){const n=svgEl('text',{x,y,'font-size':12*u,'text-anchor':anchor,class:'grid-label'});n.textContent=text;n.style.strokeWidth=3*u+'px';g.append(n);}
function updateSurveyCursor(){const map=$('#map');if(map)map.classList.toggle('survey-targeting',Boolean(state.measure||state.setup?.capture));}
function renderOverlay(){
 updateSurveyCursor();
 if(!state.config||!$('#survey-layer'))return;
 const layer=$('#survey-layer');layer.replaceChildren();const u=screenUnit(),[x,y,w,h]=state.view,m=metric();
 const left=Math.max(0,x),right=Math.min(state.config.width,x+w),top=Math.max(0,y),bottom=Math.min(state.config.height,y+h);
 if(state.grid&&m){const gridLabels=svgEl('g',{class:'grid-axis-labels'}),defs=svgEl('defs');
  for(const [id,x2,y2] of [['grid-fade-left','100%','0%'],['grid-fade-top','0%','100%']]){const gradient=svgEl('linearGradient',{id,x1:'0%',y1:'0%',x2,y2});for(const [offset,opacity] of [['0%',.97],['30%',.87],['100%',0]])gradient.append(svgEl('stop',{offset,'stop-color':'var(--map-bg, #eef2f3)','stop-opacity':opacity}));defs.append(gradient);}
  gridLabels.append(defs,svgEl('rect',{x,y,width:w,height:58*u,fill:'url(#grid-fade-top)'}),svgEl('rect',{x,y,width:66*u,height:h,fill:'url(#grid-fade-left)'}));
  const step=2/m,[ox,oy]=settings().grid_origin;const firstC=Math.max(0,Math.floor((left-ox)/step)),lastC=Math.ceil((right-ox)/step),firstR=Math.max(0,Math.floor((top-oy)/step)),lastR=Math.ceil((bottom-oy)/step);
  // Do not allocate thousands of subpixel lines for an erroneous calibration.
  if(lastC-firstC+lastR-firstR<1500){
   for(let c=firstC;c<=lastC;c++){const xx=ox+c*step;if(xx>=left&&xx<=right)layer.append(svgEl('line',{x1:xx,y1:top,x2:xx,y2:bottom,class:'grid-line','vector-effect':'non-scaling-stroke'}));const mid=xx+step/2;if(mid>=left&&mid<=right&&c%Math.max(1,Math.ceil(40*u/step))===0)overlayText(gridLabels,String(c+1),mid,y+18*u,u);}
   for(let r=firstR;r<=lastR;r++){const yy=oy+r*step;if(yy>=top&&yy<=bottom)layer.append(svgEl('line',{x1:left,y1:yy,x2:right,y2:yy,class:'grid-line','vector-effect':'non-scaling-stroke'}));const mid=yy+step/2;if(mid>=top&&mid<=bottom&&r%Math.max(1,Math.ceil(22*u/step))===0)overlayText(gridLabels,rowLetter(r),x+12*u,mid,u);}
  }
  layer.append(gridLabels);
 }
 const refs=state.setup?.landmarks||[];
 refs.forEach((r,i)=>{layer.append(svgEl('circle',{cx:r.point[0],cy:r.point[1],r:5*u,fill:'#d74747',stroke:'white','stroke-width':u}));overlayText(layer,(i+1)+': '+r.name,r.point[0]+8*u,r.point[1]-9*u,u,'start');});
 let points=state.measurePoints.slice();if(state.measure&&points.length===1&&state.pointer)points.push(state.pointer);
 if(points.length===2){layer.append(svgEl('line',{x1:points[0][0],y1:points[0][1],x2:points[1][0],y2:points[1][1],stroke:'#e4514c','stroke-width':2,'vector-effect':'non-scaling-stroke'}));points.forEach(p=>layer.append(svgEl('circle',{cx:p[0],cy:p[1],r:4*u,fill:'#e4514c'})));overlayText(layer,(dist(...points)*m).toFixed(2)+' m',(points[0][0]+points[1][0])/2,(points[0][1]+points[1][1])/2-10*u,u);}
 const scale=$('#scale-indicator');if(m){const max=120*u*m,pow=10**Math.floor(Math.log10(max)),nice=[5,2,1].map(n=>n*pow).find(n=>n<=max)||pow/2;scale.hidden=false;scale.style.width=(nice/m/u)+'px';scale.textContent=Number(nice.toPrecision(4))+' m';}else scale.hidden=true;
 $('#grid-btn').disabled=!m;$('#measure-btn').disabled=!m;
 $('#map-status').textContent=state.pointer&&inPlan(state.pointer)?'X: '+state.pointer[0].toFixed(1)+' px · Y: '+state.pointer[1].toFixed(1)+' px'+(m?' · '+zone(state.pointer):''):(m?'Calibrated · '+(state.measure?'Measure: click two points · Escape clears':'Plan pixels'): 'Plan pixels · Set scale in Map setup');
 if(state.activeVertex!==null&&state.draft){const p=state.draft.geometry.points[state.activeVertex];if(p)layer.append(svgEl('circle',{cx:p[0],cy:p[1],r:9*u,fill:'none',stroke:'#e4514c','stroke-width':2,'vector-effect':'non-scaling-stroke'}));}
}
const map04=renderMap;renderMap=function(full=true){map04(full);renderOverlay();syncGeometryFields();};
const identity04=renderIdentity;renderIdentity=function(){identity04();const b=$('#setup-btn');if(b)b.hidden=!state.session?.is_admin;};
const layers04=refreshLayers;refreshLayers=async function(){const result=await layers04();if(!state.setup)planAppearance();return result;};
function makeDuplicate(o){const d=editable(o);d.title=(o.title+' — copy').slice(0,180);d.external_id='';d.status='unverified';d.floor_id=state.floor;return d;}
async function duplicateObject(o){if(!await settleDraft())return;state.draft=makeDuplicate(o);state.base=null;state.selected=null;state.edit=true;state.explicitEdit=false;state.placingCopy=true;renderDetails();renderMap();updateToolbar();toast('Click the map to place the copy, then review and save. Escape cancels placement.');}
const details04=renderDetails;renderDetails=function(){details04();const o=selectedObject();if(o&&!o.deleted&&!state.draft){$('.detail-body')?.prepend(el('button',{type:'button',class:'secondary',onclick:()=>requireLogin(()=>duplicateObject(o))},'Duplicate object'));}};
function geometryValid(g){if(g.points.some(p=>p.some(v=>!Number.isFinite(v))))return false;const b=geometryBounds(g);return b.every(Number.isFinite)&&b[0]>=0&&b[1]>=0&&b[2]<=state.config.width&&b[3]<=state.config.height;}
function syncGeometryFields(){if(!state.draft)return;$$('[data-coordinate]').forEach(input=>{if(document.activeElement===input)return;const [i,j]=input.dataset.coordinate.split(',').map(Number);input.value=state.draft.geometry.points[i][j].toFixed(3);});}
const editor04=renderEditor;renderEditor=function(){editor04();state.activeVertex=null;const form=$('#editor-form'),box=el('details',{class:'geometry-editor'},el('summary',{},'Advanced · Position and geometry'));
 box.append(el('p',{class:'form-hint'},'Plan pixels from top-left. X increases right; Y increases down. Circle: centre + edge. Slot: end centres + width handle.'));
 const dx=el('input',{type:'number',step:'any',value:0,'aria-label':'Move all vertices by X'}),dy=el('input',{type:'number',step:'any',value:0,'aria-label':'Move all vertices by Y'});
 box.append(el('div',{class:'geometry-move'},labelField('Move ΔX',dx),labelField('Move ΔY',dy),el('button',{type:'button',class:'secondary',onclick:()=>{const g=clone(state.draft.geometry),x=Number(dx.value),y=Number(dy.value);g.points=g.points.map(p=>[p[0]+x,p[1]+y]);if(!geometryValid(g)){toast('The translated shape must fit inside the plan.');return;}state.draft.geometry=g;dx.value=dy.value=0;renderMap();updateDirty();}},'Move whole shape')));
 const table=el('table',{},el('thead',{},el('tr',{},el('th',{},'Vertex'),el('th',{},'X (px)'),el('th',{},'Y (px)')))),body=el('tbody');
 state.draft.geometry.points.forEach((p,i)=>{const row=el('tr',{},el('td',{},String(i+1)));p.forEach((v,j)=>{const input=el('input',{type:'number',step:'any',value:v,'data-coordinate':i+','+j,'aria-label':'Vertex '+(i+1)+' '+(j?'Y':'X'),onfocus:()=>{state.activeVertex=i;renderOverlay();},onchange:()=>{const g=clone(state.draft.geometry);g.points[i][j]=Number(input.value);if(!input.value.trim()||!geometryValid(g)){toast('Enter coordinates that keep the shape inside the plan.');input.value=state.draft.geometry.points[i][j];return;}state.draft.geometry=g;renderMap();updateDirty();}});row.append(el('td',{},input));});body.append(row);});table.append(body);box.append(el('div',{class:'vertices-scroll'},table));form.insertBefore(box,$('#draft-photos'));
};
const clear04=clearDraft;clearDraft=function(){clear04();state.placingCopy=false;state.activeVertex=null;};
function setupMessage(text){$('#setup-message').textContent=text;}
function captureMode(mode){state.setup.capture=mode;updateSurveyCursor();state.setup.picked=[];$('#setup-dialog').close();$('#survey-help').hidden=false;$('#survey-help-text').textContent=(mode==='calibrate'||mode==='verify')?'Select two points for a known distance.':mode==='landmark'?'Click a permanent structural landmark.':mode==='origin'?'Click the top-left grid anchor (letters/numbers increase down/right).':'On the NEW drawing, click in this order: '+(state.setup.targets||[]).map((r,i)=>(i+1)+'. '+r.name).join(' → ');}
async function openSetup(){if(!await settleDraft())return;state.tool=null;state.drawing=[];state.measure=false;state.measurePoints=[];renderAll();try{const latest=await api('/map-settings');state.setup={...clone(latest),replacement:null,capture:null,picked:[]};state.config.map_settings=latest;renderSetup();$('#setup-dialog').showModal();renderOverlay();}catch(e){toast(e.message);}}
function abandonSetup(){state.setup=null;$('#setup-dialog').close();$('#survey-help').hidden=true;planAppearance();renderOverlay();}
function renderSetup(){updateSurveyCursor();const s=state.setup,container=$('#setup-content');container.replaceChildren();
 container.append(el('p',{class:'muted'},'Administrator setup · Shared by both floors. Changes apply only when saved. Demo mode grants setup access to local signed-in names.'),el('p',{},'Revision '+s.version+' · '+(s.metres_per_pixel?Number(s.metres_per_pixel.toPrecision(6))+' m / plan pixel':'Scale not calibrated')));
 const metres=el('input',{type:'number',min:0,step:'any',value:s.calibration?.metres||'',id:'known-metres'});
 const pixelDistance=el('input',{type:'number',min:1,step:'any',placeholder:'Optional: enter pixel length directly',id:'known-pixels'});
 container.append(el('h3',{},'Scale calibration'),labelField('Known distance (m)',metres),labelField('Equivalent length (plan px)',pixelDistance),el('button',{type:'button',class:'secondary',onclick:()=>{const mm=Number(metres.value),px=Number(pixelDistance.value);if(!(mm>0)){setupMessage('Enter the known distance in metres first.');return;}s.knownMetres=mm;if(px>=1){s.calibration={a:[0,0],b:[px,0],metres:mm};s.metres_per_pixel=mm/px;setupMessage('Draft calibration: '+s.metres_per_pixel+' m / pixel. Save to apply.');}else captureMode('calibrate');}},'Set scale / select two points'),el('button',{type:'button',class:'text-button',onclick:()=>{s.knownMetres=Number(metres.value);if(!(s.knownMetres>0)){setupMessage('Enter the known check distance first.');return;}captureMode('verify');}},'Check another known distance'));
 container.append(el('h3',{},'Grid anchor'),el('p',{},'X '+s.grid_origin[0].toFixed(2)+' · Y '+s.grid_origin[1].toFixed(2)+' plan px'),el('button',{type:'button',class:'secondary',onclick:()=>captureMode('origin')},'Choose grid anchor'));
 container.append(el('h3',{},'Named reference landmarks'),el('p',{class:'form-hint'},'Choose permanent features. Coordinates are shared across floors. Use two for alignment; three or more also provide a fit check.'));
 s.landmarks.forEach((r,i)=>container.append(el('div',{class:'reference-row'},el('input',{type:'checkbox',checked:true,'data-reference':i,'aria-label':'Use '+r.name+' for alignment'}),el('span',{},r.name+' · '+r.point.map(v=>v.toFixed(1)).join(', ')),el('button',{type:'button',class:'text-button',onclick:()=>{s.landmarks.splice(i,1);renderSetup();renderOverlay();}},'Remove'))));
 const name=el('input',{id:'landmark-name',maxlength:100,placeholder:'e.g. Column B3 centre'});container.append(labelField('New landmark name',name),el('button',{type:'button',class:'secondary',onclick:()=>{if(!name.value.trim()){setupMessage('Name the landmark first.');return;}s.nextName=name.value.trim();captureMode('landmark');}},'Place landmark'));
 container.append(el('h3',{},'Replace '+floorName(state.floor)+' background'),el('p',{class:'form-hint'},'Plain SVG paths and shapes only, up to 24 MB. Text must be converted to paths. Upload stays private to this draft until Apply; existing objects do not move.'));
 const upload=el('input',{type:'file',accept:'.svg,image/svg+xml',onchange:async()=>{if(!upload.files[0])return;try{if(upload.files[0].size>24_000_000)throw new Error('Choose an SVG up to 24 MB.');s.targets=$$('[data-reference]:checked',container).map(n=>s.landmarks[Number(n.dataset.reference)]);if(s.targets.length<2)throw new Error('Select at least two landmarks first.');const svg=await upload.files[0].text(),asset=await api('/plan-upload',{method:'POST',body:{svg}}),scale=Math.min(state.config.width/asset.image_width,state.config.height/asset.image_height);s.replacement={...asset,floor_id:state.floor,transform:[scale,0,0,scale,0,0]};s.previewTransform=s.replacement.transform.slice();s.aligned=false;planAppearance();captureMode('align');}catch(e){setupMessage(e.message);}}});container.append(upload);
 if(s.replacement){container.append(el('p',{},s.aligned?'Replacement preview is aligned. Inspect it beneath the existing objects.':'Replacement is not aligned yet.'),el('button',{type:'button',class:'secondary',onclick:()=>{s.replacement.transform=s.previewTransform.slice();planAppearance();s.aligned=false;captureMode('align');}},'Repeat alignment'),el('button',{type:'button',class:'text-button',onclick:()=>{$('#setup-dialog').close();$('#survey-help').hidden=false;$('#survey-help-text').textContent='Inspect the aligned background beneath existing objects; pan and zoom normally. Return to setup to apply or cancel.';}},'Inspect preview'));
 }
}
async function saveSetup(){const s=state.setup;if(s.replacement&&!s.aligned){setupMessage('Complete the alignment before applying the replacement.');return;}const btn=$('#setup-save');btn.disabled=true;try{const result=await api('/map-settings',{method:'POST',body:{version:s.version,calibration:s.calibration,landmarks:s.landmarks,grid_origin:s.grid_origin,replacement:s.replacement}});state.config.map_settings=result;state.config.floors=result.floors;abandonSetup();toast('Map setup saved · revision '+result.version);}catch(e){setupMessage(e.message);}finally{btn.disabled=false;}}
async function setupHistory(){try{const data=await api('/map-history'),box=$('#setup-history');box.replaceChildren(...data.revisions.map(r=>el('button',{type:'button',class:'secondary',onclick:async()=>{if(!await confirmNear($('#setup-history'),'Restore calibration, landmarks and BOTH floor backgrounds from revision '+r.version+'?',{title:'Restore map setup',accept:'Restore',cancel:'Cancel'}))return;try{const result=await api('/map-restore',{method:'POST',body:{version:state.setup.version,restore_version:r.version}});state.config.map_settings=result;state.config.floors=result.floors;abandonSetup();toast('Map setup restored as revision '+result.version);}catch(e){setupMessage(e.message);}}},'Restore revision '+r.version+' · '+r.actor+' · '+date(r.changed_at))));}catch(e){setupMessage(e.message);}}
function capturedPoint(p){const s=state.setup,mode=s.capture;s.picked.push(p);
 if(mode==='landmark'){s.landmarks.push({name:s.nextName,point:p});s.capture=null;}
 else if(mode==='origin'){s.grid_origin=p;s.capture=null;}
 else if((mode==='calibrate'||mode==='verify')&&s.picked.length===2){const pixels=dist(...s.picked);if(pixels<1){toast('Choose points farther apart.');s.picked=[];return;}if(mode==='calibrate'){s.calibration={a:s.picked[0],b:s.picked[1],metres:s.knownMetres};s.metres_per_pixel=s.knownMetres/pixels;}else{s.checkMessage=s.metres_per_pixel?'Check: '+(pixels*s.metres_per_pixel).toFixed(3)+' m measured; '+s.knownMetres+' m expected ('+(100*(pixels*s.metres_per_pixel/s.knownMetres-1)).toFixed(2)+'% difference).':'Set a scale first.';}s.capture=null;}
 else if(mode==='align'){
  toast('Selected reference '+s.picked.length+' of '+s.targets.length+(s.targets[s.picked.length]?' · next: '+s.targets[s.picked.length].name:''));
  if(s.picked.length===s.targets.length){try{const source=s.picked.map(q=>inversePoint(q,s.previewTransform)),target=s.targets.map(r=>r.point),t=similarity(source,target);s.replacement.transform=t;s.aligned=true;s.checkMessage=source.length>2?'Extra-reference errors: '+source.slice(2).map((q,i)=>dist(transformPoint(q,t),target[i+2]).toFixed(2)+' px').join(', ')+'. Inspect before applying.':'Two-reference alignment calculated. A third reference is recommended to check the fit.';s.capture=null;planAppearance();}catch(e){toast(e.message);s.picked=[];}}
 }
 if(!s.capture){$('#survey-help').hidden=true;renderSetup();setupMessage(s.checkMessage||'Draft updated. Apply setup to save.');$('#setup-dialog').showModal();}renderOverlay();
}
const select04=selectObject;selectObject=async function(o,centre=false){if(state.setup){toast('Finish or cancel Map setup first.');return false;}state.measure=false;state.measurePoints=[];$('#measure-btn').setAttribute('aria-pressed','false');return select04(o,centre);};
const choose04=chooseTool;chooseTool=function(tool){state.measure=false;state.measurePoints=[];$('#measure-btn').setAttribute('aria-pressed','false');choose04(tool);};
const down04=mapDown,move04=mapMove,up04=mapUp;
mapDown=function(e){down04(e);if(state.drag&&(state.measure||state.setup||state.placingCopy)){state.drag.kind='pan';state.drag.id=null;}};
mapMove=function(e){move04(e);state.pointer=mapPoint(e);renderOverlay();if(state.drag?.moved&&state.draft){syncGeometryFields();updateDirty();}};
mapUp=function(e){const d=state.drag,p=mapPoint(e),special=state.measure||state.setup||state.placingCopy;
 if(special&&d&&!d.moved){state.drag=null;if($('#map').hasPointerCapture(e.pointerId))$('#map').releasePointerCapture(e.pointerId);if(!inPlan(p)){toast('Select a point inside the plan.');return;}
  if(state.setup){if(state.setup.capture)capturedPoint(p);}
  else if(state.placingCopy){const g=clone(state.draft.geometry),b=geometryBounds(g),dx=p[0]-(b[0]+b[2])/2,dy=p[1]-(b[1]+b[3])/2;g.points=g.points.map(q=>[q[0]+dx,q[1]+dy]);if(!geometryValid(g)){toast('The copy must fit inside the plan. Choose a location farther from the edge.');return;}state.draft.geometry=g;state.placingCopy=false;renderMap();updateDirty();}
  else{if(state.measurePoints.length===2)state.measurePoints=[];state.measurePoints.push(p);renderOverlay();}return;
 }up04(e);};
const bind04=bindEvents;bindEvents=function(){
 $('#map').append(svgEl('g',{id:'survey-layer','pointer-events':'none'}));
 $('#map-viewport').append(el('div',{id:'scale-indicator',hidden:true}),el('div',{id:'survey-help',hidden:true},el('span',{id:'survey-help-text'}),el('button',{type:'button',class:'secondary',onclick:()=>{if(!state.setup)return;state.setup.capture=null;state.setup.picked=[];$('#survey-help').hidden=true;renderSetup();$('#setup-dialog').showModal();}},'Return to setup')));
 $('.toolbar-actions').prepend(el('button',{id:'grid-btn',class:'small-button','aria-pressed':'false',onclick:()=>{state.grid=!state.grid;$('#grid-btn').setAttribute('aria-pressed',String(state.grid));renderOverlay();}},'2 m grid'),el('button',{id:'measure-btn',class:'small-button','aria-pressed':'false',onclick:async()=>{if(state.setup)return;if(!state.measure&&!await settleDraft())return;state.tool=null;state.drawing=[];state.measure=!state.measure;state.measurePoints=[];$('#measure-btn').setAttribute('aria-pressed',String(state.measure));renderAll();}},'Measure'),el('button',{id:'setup-btn',class:'small-button',hidden:true,onclick:()=>{state.measure=false;state.measurePoints=[];openSetup();}},'Map setup'));
 const dialog=el('dialog',{id:'setup-dialog',class:'wide-dialog'},el('div',{class:'dialog-heading'},el('h2',{},'Map setup'),el('button',{type:'button',class:'icon-button','aria-label':'Cancel map setup',onclick:abandonSetup},'×')),el('div',{id:'setup-content'}),el('p',{id:'setup-message',role:'status'}),el('div',{class:'dialog-actions'},el('button',{id:'setup-save',type:'button',class:'primary',onclick:saveSetup},'Apply setup'),el('button',{type:'button',class:'secondary',onclick:abandonSetup},'Cancel')),el('hr'),el('button',{type:'button',class:'text-button',onclick:setupHistory},'Show setup revisions / rollback'),el('div',{id:'setup-history'}));document.body.append(dialog);dialog.addEventListener('cancel',e=>{e.preventDefault();abandonSetup();});
 bind04();$('#map').addEventListener('pointerleave',()=>{state.pointer=null;renderOverlay();});
 window.addEventListener('beforeunload',e=>{if(state.setup){e.preventDefault();e.returnValue='';}});
 document.addEventListener('keydown',e=>{if(e.key!=='Escape'||e.target.closest('input,textarea,select,dialog'))return;if(state.setup?.capture){state.setup.capture=null;$('#survey-help').hidden=true;renderSetup();$('#setup-dialog').showModal();}state.measure=false;state.measurePoints=[];$('#measure-btn').setAttribute('aria-pressed','false');state.placingCopy=false;renderOverlay();});
 // Avoid switching floors or starting an object tool in the middle of reference selection.
 document.addEventListener('click',e=>{if(state.setup&&e.target.closest('#floor-select,[data-tool],#edit-mode-btn,#measure-btn')){e.preventDefault();e.stopImmediatePropagation();toast('Finish or cancel Map setup first.');}},true);
};
init();
