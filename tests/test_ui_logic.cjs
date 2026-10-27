// Controller and geometry checks; this does not replace a visual browser test.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
class FakeNode {
  constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.style={setProperty(k,v){this[k]=v;}};this.classList={toggle(){},add(){},remove(){}};this.value='';this.dataset={};this.open=false;this.isConnected=true;}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k];}
  addEventListener(){}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  getScreenCTM(){return {a:1,b:0};}
  focus(){}
  showModal(){this.open=true;}
  close(){this.open=false;}
  getBoundingClientRect(){return this.rect||{top:0,bottom:180,right:300,left:0,width:300,height:180};}
}
const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new FakeNode(id));return nodes.get(id);};
const stored=new Map();
const context=vm.createContext({window:{innerWidth:1200,innerHeight:800},localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},Node:FakeNode,document:{documentElement:new FakeNode('html'),activeElement:get('#anchor'),createElement:t=>new FakeNode(t),createElementNS:(_,t)=>new FakeNode(t),createTextNode:t=>({textContent:t}),querySelector:get,querySelectorAll:()=>[]},console,setTimeout,clearTimeout,URLSearchParams,Math,JSON,Date,confirm:()=>true,history:{replaceState(){}},location:{pathname:'/'}});
const code=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8').replace(/\ninit\(\);\s*$/,'');
vm.runInContext(code,context);
const result=vm.runInContext(`
state.config={width:1440,height:720,categories:[
{id:'air',name:'Compressed air',color:'#168ca5',symbol:'A',aliases:['pressurized air','tryckluft']},
{id:'area',name:'Areas',color:'#438568',symbol:'Z',aliases:['storage']},
{id:'route',name:'Routes',color:'#b5655d',symbol:'R',aliases:['pipe']}]};
state.categories=new Set(['air','area','route']);
const air={id:'air-1',title:'AIR 01',description:'Quick coupling',category:'air',tags:[],details:[{label:'Pressure',value:'6 bar'}],links:[],geometry:{type:'point',points:[[100,200]]}};
const area={...air,id:'area-1',title:'Storage',description:'',details:[],category:'area',geometry:{type:'rectangle',points:[[300,400],[500,500]]}};
state.objects=[air,area];
const answers={};
state.query='pressurized air';answers.alias=matchedObjects().map(o=>o.id);
state.query='TRYCKLUFT';answers.swedish=matchedObjects().map(o=>o.id);
state.query='6 bar';answers.details=matchedObjects().map(o=>o.id);
state.query='missing service';answers.noMatch=matchedObjects().length;
state.query='';state.categories.delete('air');answers.layerFilter=matchedObjects().map(o=>o.id);state.categories.add('air');
const node=geometryNode({...air.geometry,category:'air'},'#168ca5');answers.pointSymbol=node.children[1].textContent;
const rect=geometryNode({type:'rectangle',points:[[500,500],[300,400]]},'#438568');answers.rectangle=[rect.attrs.x,rect.attrs.y,rect.attrs.width,rect.attrs.height];
answers.customStyle=el('span',{style:{'--color':'#168ca5'}}).style['--color'];
renderMap();answers.shapeCount=document.querySelector('#objects-layer').children.length;
answers.clamped=clamp([-100,900]);
// Keep geometry completion tests independent from rendering.
renderDetails=()=>{};renderMap=()=>{};updateToolbar=()=>{};
state.tool='polygon';state.drawing=[[1,1],[20,1],[20,30]];finishDrawing();answers.polygonDraft=state.draft.geometry;
state.draft=null;state.tool='line';state.drawing=[[1,1],[20,30]];finishDrawing();answers.lineCategory=state.draft.category;
JSON.stringify(answers);
`,context);
const r=JSON.parse(result);
assert.deepEqual(r.alias,['air-1']);assert.deepEqual(r.swedish,['air-1']);assert.deepEqual(r.details,['air-1']);assert.equal(r.noMatch,0);assert.deepEqual(r.layerFilter,['area-1']);
assert.equal(r.pointSymbol,'A');assert.deepEqual(r.rectangle,['300','400','200','100']);assert.equal(r.customStyle,'#168ca5');assert.equal(r.shapeCount,2);assert.deepEqual(r.clamped,[0,720]);assert.equal(r.polygonDraft.type,'polygon');assert.equal(r.polygonDraft.points.length,3);assert.equal(r.lineCategory,'route');
console.log('PASS: aliases, technical-field search, layer filters, point symbols, rectangle geometry, custom styles, map objects, coordinate limits, polygon and line drafts.');

(async()=>{
 const result=await vm.runInContext(`(async()=>{
 const extra={};
 state.query='';state.tool='circle';state.drawing=[[200,200],[240,230]];finishDrawing();extra.circleRadius=circleRadius(state.draft.geometry);extra.circleBounds=geometryBounds(state.draft.geometry);
 extra.circleNode=geometryNode(state.draft.geometry,'#168ca5').attrs;
 state.draft=null;state.tool='slot';state.drawing=[[300,300],[500,300],[400,325]];finishDrawing();extra.slotBounds=geometryBounds(state.draft.geometry);extra.slotPath=slotPath(state.draft.geometry);
 const diagonal=canonicalSlot({type:'slot',points:[[300,300],[400,400],[330,370]]});extra.diagonalRadius=slotMetrics(diagonal).r;
 const edge=circleEdge([10,10],[100,10]);extra.limitedCircleRadius=Math.hypot(edge[0]-10,edge[1]-10);
 setTheme('midnight');extra.theme=document.documentElement.dataset.theme;extra.themePressed=document.querySelector('#theme-btn').attrs['aria-pressed'];extra.themeStored=localStorage.getItem('freia-theme');
 const anchor=document.querySelector('#anchor');anchor.rect={left:1080,right:1180,top:700,bottom:730,width:100,height:30};
 state.draft=clone(air);state.exitEditAfterDraft=true;state.edit=true;
 let pending=discardDraft(anchor);extra.confirmOpen=document.querySelector('#confirm-dialog').open;extra.confirmLeft=document.querySelector('#confirm-dialog').style.left;extra.confirmTop=document.querySelector('#confirm-dialog').style.top;
 document.querySelector('#confirm-no').onclick();extra.cancelKeptDraft=!(await pending)&&!!state.draft&&state.edit;
 pending=discardDraft(anchor);document.querySelector('#confirm-yes').onclick();extra.confirmClearedDraft=await pending;extra.confirmExitedEdit=!state.edit&&!state.draft;
 state.edit=true;state.exitEditAfterDraft=false;state.draft=clone(air);pending=discardDraft(anchor);document.querySelector('#confirm-yes').onclick();await pending;extra.explicitEditRemains=state.edit;
 state.draft={...clone(air),version:1};state.exitEditAfterDraft=true;state.edit=true;
 collectDraft=()=>clone(state.draft);api=async()=>({...clone(air),version:2});renderAll=()=>{};
 await saveDraft({preventDefault(){}});extra.saveExitedEdit=!state.edit&&!state.draft;
 state.draft={...clone(air),version:1};state.exitEditAfterDraft=true;state.edit=true;
 api=async()=>{const error=new Error('Conflict');error.status=409;error.current={...clone(air),version:3,updated_by:'Other',updated_at:'2026-10-13T07:00:00Z'};throw error;};
 await saveDraft({preventDefault(){}});extra.conflictKeptDraft=!!state.draft&&state.edit;
 return JSON.stringify(extra);
 })()`,context);
 const t=JSON.parse(result);
 assert.equal(t.circleRadius,50);assert.deepEqual(t.circleBounds,[150,150,250,250]);assert.equal(t.circleNode.r,'50');assert.deepEqual(t.slotBounds,[275,275,525,325]);assert.match(t.slotPath,/A25,25/);assert.ok(t.diagonalRadius>28&&t.diagonalRadius<29);assert.equal(t.limitedCircleRadius,10);
 assert.equal(t.theme,'midnight');assert.equal(t.themeStored,'midnight');assert.equal(t.themePressed,'true');assert.equal(t.confirmOpen,true);assert.equal(t.confirmLeft,'880px');assert.equal(t.confirmTop,'510px');assert.ok(t.cancelKeptDraft);assert.ok(t.confirmClearedDraft);assert.ok(t.confirmExitedEdit);assert.ok(t.explicitEditRemains);assert.ok(t.saveExitedEdit);assert.ok(t.conflictKeptDraft);
 console.log('PASS: circle/slot rendering and bounds, midnight persistence, nearby confirmation, cancel/save edit lifecycle, and retained conflict drafts.');
 clearTimeout(vm.runInContext('toastTimer',context));
})().catch(error=>{console.error(error);process.exitCode=1;});
