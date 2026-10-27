#!/usr/bin/env python3
"""Generate an isolated benchmark database; never overwrite an existing file."""
import argparse,json,math,random,sys,time,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from server import Store,validate_object
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--count',type=int,choices=[100,300,1000],default=300)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.output.exists():p.error('Output already exists. Choose a new file, never your live database.')
rng=random.Random(314159);store=Store(a.output);started=time.perf_counter()
with store.connect() as db:
 db.execute('BEGIN IMMEDIATE');db.execute('DELETE FROM objects');db.execute('DELETE FROM revisions');layers=store.list_layers(db=db)
 for i in range(a.count):
  # One third is clustered, the rest spread across the hall. Both floors are used.
  x=rng.uniform(590,740) if i%3==0 else rng.uniform(90,1330);y=rng.uniform(340,450) if i%3==0 else rng.uniform(90,620)
  typ=['point','point','point','rectangle','polygon','line','circle','slot'][i%8]
  if typ=='point':geometry={'type':typ,'points':[[x,y]]}
  elif typ=='rectangle':geometry={'type':typ,'points':[[x,y],[x+25,y+18]]}
  elif typ=='polygon':geometry={'type':typ,'points':[[x+18*math.cos(t*math.tau/24),y+18*math.sin(t*math.tau/24)] for t in range(24)]}
  elif typ=='line':geometry={'type':typ,'points':[[x,y],[x+20,y+15],[x+45,y+15]]}
  elif typ=='circle':geometry={'type':typ,'points':[[x,y],[x+15,y]]}
  else:geometry={'type':typ,'points':[[x,y],[x+30,y+15],[x+11,y+15.5]]}
  item={'title':f'Benchmark {i+1:04d} · {typ}','external_id':f'BENCH-{i+1:04d}','floor_id':'upper' if i%4==0 else 'ground','category':layers[i%len(layers)]['id'],'status':'sample','description':'Synthetic benchmark record. Not facility data.','tags':['benchmark'],'details':[{'label':'Asset','value':f'TEST-{i+1}'}],'links':[],'geometry':geometry}
  store.write(db,str(uuid.uuid4()),validate_object(item,layers),'Benchmark generator','create',1,False)
print(json.dumps({'objects':a.count,'database':str(a.output.resolve()),'generation_seconds':round(time.perf_counter()-started,3)},indent=2))
print('Start with: python server.py --data "'+str(a.output.resolve())+'"')
print('Open http://127.0.0.1:8000/?benchmark=1, then Export data -> Measure map performance.')
