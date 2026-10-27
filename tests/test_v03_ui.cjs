const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {environment}=require('./dom_stub.cjs');const env=environment(),ctx=env.context;
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8'),ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/v03.js'),'utf8').replace(/\ninit\(\);\s*$/,''),ctx);
function run(code){return vm.runInContext(code,ctx);}
run(`state.config={width:1440,height:720,plan_url:'/assets/plan.svg',floors:[{id:'ground',name:'Ground floor',plan_url:'/assets/plan.svg'},{id:'upper',name:'Upper floor',plan_url:'/assets/plan.svg'}],categories:[{id:'air',name:'Compressed air',color:'#168ca5',symbol:'A',version:1,aliases:['pressurized air']},{id:'area',name:'Areas',color:'#438568',symbol:'Z',version:1,aliases:[]}]};state.categories=new Set(['air','area']);state.session={username:'Piotr'};
const base={id:'one',version:1,title:'Outlet',category:'air',description:'Original',status:'unverified',tags:[],details:[],links:[],floor_id:'ground',external_id:'AIR-1',photos:[],main_photo:null,geometry:{type:'point',points:[[100,200]]}};
const upper={...clone(base),id:'two',external_id:'AIR-2',floor_id:'upper',title:'Upper outlet'};
state.objects=[base,upper];`);
(async()=>{
 run('renderMap();');assert.equal(env.get('#objects-layer').children.length,1);const group=env.get('#objects-layer').children[0],before=env.created();
 run('setView([30,30,600,450]);');env.flush();assert.equal(env.get('#objects-layer').children[0],group);assert.equal(env.created(),before,'panning reuses object nodes');
 const camera=run('JSON.stringify(state.view)');await run("switchFloor('upper');");assert.equal(run('JSON.stringify(state.view)'),camera);assert.equal(env.get('#objects-layer').children.length,1);assert.equal(run('visibleObjects()[0].id'),'two');
 run("state.searchAll=true;state.query='pressurized air';");assert.equal(run('matchedObjects().length'),2);run('state.searchAll=false;');assert.equal(run('matchedObjects().length'),1);
 run('setView([-9999,-9999,300,225]);');env.flush();assert.deepEqual(JSON.parse(run('JSON.stringify(state.view.slice(0,2))')),[-40,-40]);
 run('setView([9999,9999,300,225]);');env.flush();assert.deepEqual(JSON.parse(run('JSON.stringify(state.view.slice(0,2))')),[1180,535]);
 run("state.floor='ground';state.explicitEdit=true;state.edit=true;");await run('selectObject(base);');assert.equal(run('state.draft.id'),'one');assert.equal(run('draftIsDirty()'),false);
 env.get('#editor-form').querySelector('input[name=title]').value='Changed';assert.equal(run('draftIsDirty()'),true);env.get('#editor-form').querySelector('input[name=title]').value='Outlet';assert.equal(run('draftIsDirty()'),false);
 run('state.draft.geometry.points[0][0]=101;');assert.equal(run('draftIsDirty()'),true);run('state.draft.geometry.points[0][0]=100;');assert.equal(run('draftIsDirty()'),false);
 await run('selectObject(upper);');assert.equal(run('state.draft.id'),'two');assert.equal(env.get('#confirm-dialog').open,false,'unchanged drafts switch without prompting');
 env.get('#editor-form').querySelector('input[name=title]').value='Unsaved upper';const switching=run('selectObject(base);');assert.equal(env.get('#confirm-dialog').open,true);env.get('#confirm-no').onclick();await switching;assert.equal(run('state.draft.id'),'two');
 const discardSwitch=run('selectObject(base);');env.get('#confirm-yes').onclick();await discardSwitch;assert.equal(run('state.draft.id'),'one');assert.equal(run('state.explicitEdit'),true);
 const merge=JSON.parse(run(`JSON.stringify(mergeVersions(base,{...clone(base),description:'My note'},{...clone(base),version:2,title:'Other name'}))`));assert.deepEqual(merge.conflicts,[]);assert.equal(merge.merged.description,'My note');assert.equal(merge.merged.title,'Other name');
 const conflict=JSON.parse(run(`JSON.stringify(mergeVersions(base,{...clone(base),geometry:{type:'point',points:[[110,200]]}},{...clone(base),version:2,floor_id:'upper'}))`));assert.ok(conflict.conflicts.includes('location'),'floor and geometry changes are reviewed together');
 const caption=JSON.parse(run(`JSON.stringify(mergeVersions(base,{...clone(base),title:'Mine'},{...clone(base),title:'Other'}))`));assert.ok(caption.conflicts.includes('title'));
 run("setTheme('solarized');setPlanTheme('light');");assert.equal(run("localStorage.getItem('freia-theme')"),'solarized');assert.equal(run("document.documentElement.dataset.plan"),'light');
 console.log('PASS: retained map nodes, bounded camera, same view across floors, cross-floor search, immediate edit selection, reverted changes, selective switch prompts, conflict merging, and theme/plan preferences.');
 clearTimeout(run('toastTimer'));
})().catch(error=>{console.error(error);process.exitCode=1;clearTimeout(run('toastTimer'));});
