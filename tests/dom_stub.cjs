// Minimal DOM for controller tests. No layout engine or browser rendering is simulated.
const vm=require('node:vm');
function environment(){
 const ids=new Map(),frames=[],stored=new Map();let created=0,doc;
 function match(node,selector){if(selector.startsWith('#'))return node.attrs.id===selector.slice(1);if(selector.startsWith('.'))return String(node.className||node.attrs.class||'').split(/\s+/).includes(selector.slice(1));const m=/^(\w+)(?:\[(\w+)=["']?([^"'\]]+)["']?\])?$/.exec(selector);return m&&node.tagName===m[1].toLowerCase()&&(!m[2]||node.attrs[m[2]]===m[3]);}
 class Node {
  constructor(tag='div'){created++;this.tagName=tag.toLowerCase();this.children=[];this.attrs={};this.style={setProperty(k,v){this[k]=v;}};this.dataset={};this.value='';this.hidden=false;this.open=false;this.disabled=false;this.isConnected=true;this.className='';this.classList={toggle:(n,on)=>{const set=new Set(this.className.split(/\s+/).filter(Boolean));if(on??!set.has(n))set.add(n);else set.delete(n);this.className=[...set].join(' ');},add:n=>this.classList.toggle(n,true),remove:n=>this.classList.toggle(n,false)};}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='id')ids.set(v,this);if(k==='value')this.value=String(v);if(k==='class')this.className=String(v);if(k==='disabled')this.disabled=true;}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(k,fn){this['on'+k]=fn;}
  append(...nodes){for(const node of nodes){const child=node instanceof Node?node:Object.assign(new Node('#text'),{textContent:String(node)});if(child.parentNode){const a=child.parentNode.children;a.splice(a.indexOf(child),1);}this.children.push(child);child.parentNode=this;}}
  prepend(...nodes){for(const child of [...nodes].reverse()){this.append(child);this.children.splice(this.children.indexOf(child),1);this.children.unshift(child);}}
  replaceChildren(...nodes){for(const child of this.children)child.remove();this.children=[];this.append(...nodes);}
  remove(){if(this.parentNode){const a=this.parentNode.children;a.splice(a.indexOf(this),1);this.parentNode=null;}if(this.attrs.id&&ids.get(this.attrs.id)===this)ids.delete(this.attrs.id);this.isConnected=false;}
  querySelectorAll(selector){const selectors=selector.split(',').map(s=>s.trim()),out=[];function walk(n){for(const c of n.children){if(selectors.some(s=>match(c,s)))out.push(c);walk(c);}}walk(this);return out;}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  focus(){doc.activeElement=this;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  getBoundingClientRect(){return this.rect||{x:0,y:0,left:0,right:300,top:0,bottom:180,width:300,height:180};}
  getScreenCTM(){return {a:1,b:0};}
 }
 function get(selector){if(selector.startsWith('#')){const key=selector.slice(1);if(!ids.has(key)){const n=new Node();n.setAttribute('id',key);}return ids.get(key);}return doc.root.querySelector(selector);}
 doc={root:new Node('body'),documentElement:new Node('html'),activeElement:null,createElement:tag=>new Node(tag),createElementNS:(_,tag)=>new Node(tag),createTextNode:text=>Object.assign(new Node('#text'),{textContent:text}),querySelector:get,querySelectorAll:s=>doc.root.querySelectorAll(s)};
 for(const key of ['objects-layer','draft-layer','handles-layer','map-viewport','map','detail-panel','results','categories','confirm-dialog','confirm-title','confirm-message','confirm-yes','confirm-no','confirm-save','floor-select','map-loading','plan-image','dirty-indicator','theme-select','plan-theme','results-heading','result-count','drawing-help','edit-toolbar','edit-mode-btn','edit-status','finish-btn','cancel-draw-btn','conflict-box','toast'])doc.root.append(get('#'+key));
 const panel=new Node();panel.className='map-panel';doc.root.append(panel);get('#map-viewport').rect={left:0,right:800,top:0,bottom:600,width:800,height:600};
 class FormData {constructor(form){this.values=new Map();for(const n of form.querySelectorAll('input,textarea,select'))if(n.attrs.name)this.values.set(n.attrs.name,n.value);}get(k){return this.values.get(k)??null;}}
 const context=vm.createContext({document:doc,Node,FormData,window:{innerWidth:1200,innerHeight:800},localStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,String(v))},requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},console,setTimeout,clearTimeout,performance,URLSearchParams,history:{replaceState(){}},location:{pathname:'/',search:'',hash:''},Math,JSON,Date,TextDecoder,confirm:()=>true});
 return {context,get,created:()=>created,flush(){while(frames.length)frames.shift()();}};
}
module.exports={environment};
