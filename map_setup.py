"""Versioned map registration and calibration. Drawing coordinates never migrate."""
import gzip
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from server import APIError, FLOORS, WIDTH, HEIGHT, now


def initialize(store):
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='map_settings'").fetchone():
            import sqlite3
            target=store.path.with_name(store.path.stem+'.pre-v0.4.sqlite3')
            if not target.exists():
                with sqlite3.connect(target) as backup: db.backup(backup)
        db.executescript('''CREATE TABLE IF NOT EXISTS admin_users(username TEXT PRIMARY KEY);
          CREATE TABLE IF NOT EXISTS map_assets(id TEXT PRIMARY KEY,svg BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS map_settings(version INTEGER PRIMARY KEY,payload TEXT NOT NULL,actor TEXT NOT NULL,changed_at TEXT NOT NULL);''')
        if not db.execute('SELECT 1 FROM map_settings').fetchone():
            data={'metres_per_pixel':None,'calibration':None,'grid_origin':[0,0],'landmarks':[],
              'floors':[{**f,'transform':[1,0,0,1,0,0],'image_width':WIDTH,'image_height':HEIGHT} for f in FLOORS]}
            db.execute('INSERT INTO map_settings VALUES (1,?,?,?)',(json.dumps(data),'System',now()))


def current(store,version=None):
    with store.connect() as db:
        row=db.execute('SELECT * FROM map_settings '+('WHERE version=?' if version else 'ORDER BY version DESC LIMIT 1'),(version,) if version else ()).fetchone()
    if not row:raise APIError(404,'Map revision not found.')
    return {**json.loads(row['payload']),'version':row['version'],'actor':row['actor'],'changed_at':row['changed_at']}


def is_admin(handler):
    session=handler.session()
    if not session:return False
    if handler.server.auth=='demo':return True
    with handler.server.store.connect() as db:return bool(db.execute('SELECT 1 FROM admin_users WHERE username=?',(session['username'],)).fetchone())


def number(v,positive=False):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>1e8 or (positive and v<=0):raise APIError(400,'Invalid numeric value.')
    return v


def point(v):
    if not isinstance(v,list) or len(v)!=2:raise APIError(400,'A reference needs X and Y.')
    return [number(x) for x in v]


def clean_svg(raw):
    if not isinstance(raw,str) or len(raw.encode())>24_000_000:raise APIError(413,'SVG must be at most 24 MB.')
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():raise APIError(400,'SVG document declarations are not supported.')
    try:root=ET.fromstring(raw)
    except ET.ParseError:raise APIError(400,'Invalid SVG XML.')
    if root.tag!='{http://www.w3.org/2000/svg}svg':raise APIError(400,'Choose an SVG drawing.')
    allowed={'svg','g','path','rect','circle','ellipse','line','polyline','polygon','title','desc'}
    attrs={'viewBox','width','height','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','d','points','transform','fill','fill-rule','fill-opacity','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','opacity','preserveAspectRatio','vector-effect','id'}
    for node in root.iter():
        if node.tag.split('}')[-1] not in allowed:raise APIError(400,'Unsupported SVG element. Export plain paths/shapes without text, images, links, stylesheets or reusable symbols.')
        cleaned={}
        for key,value in node.attrib.items():
            if key=='style':
                for rule in value.split(';'):
                    if ':' in rule:
                        k,v=rule.split(':',1)
                        if k.strip() in attrs:cleaned[k.strip()]=v.strip()
            elif key in attrs:cleaned[key]=value
        if any(re.search(r'url\s*\(|javascript:|@import',v,re.I) for v in cleaned.values()):raise APIError(400,'SVG references and external resources are not supported.')
        node.attrib.clear();node.attrib.update(cleaned)
    try:
        box=[float(x) for x in re.split(r'[\s,]+',root.get('viewBox','').strip())]
        if len(box)!=4 or not all(math.isfinite(x) for x in box) or min(box[2:])<=0:raise ValueError()
    except ValueError:raise APIError(400,'SVG needs a valid viewBox. Export a plain SVG with a page size.')
    root.set('width',str(box[2]));root.set('height',str(box[3]))
    return ET.tostring(root,encoding='utf-8'),box[2],box[3]


def save(store,actor,expected,data):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        version=db.execute('SELECT MAX(version) FROM map_settings').fetchone()[0]
        if expected!=version:raise APIError(409,'Map setup changed. Reopen setup and review the latest revision.')
        db.execute('INSERT INTO map_settings VALUES (?,?,?,?)',(version+1,json.dumps(data),actor,now()))
    return current(store)


def setup_api(h,method,path):
    store=h.server.store
    if path=='/api/map-settings' and method=='GET':h.respond(200,current(store));return True
    if path=='/api/map-history' and method=='GET':
        if not is_admin(h):raise APIError(403,'Administrator access required.')
        with store.connect() as db:rows=[dict(r) for r in db.execute('SELECT version,actor,changed_at FROM map_settings ORDER BY version DESC')]
        h.respond(200,{'revisions':rows});return True
    if path.startswith('/api/plan-assets/') and method=='GET':
        pid=path.rsplit('/',1)[-1]
        with store.connect() as db:row=db.execute('SELECT svg FROM map_assets WHERE id=?',(pid,)).fetchone()
        if not row:raise APIError(404,'Plan not found.')
        raw=gzip.decompress(row[0]);h.send_response(200);h.send_header('Content-Type','image/svg+xml');h.send_header('Content-Length',str(len(raw)));h.send_header('Cache-Control','private, max-age=31536000, immutable');h.security_headers();h.end_headers();h.wfile.write(raw);return True
    if path not in ('/api/map-settings','/api/map-restore','/api/plan-upload') or method!='POST':return False
    actor=h.actor()
    if not is_admin(h):raise APIError(403,'Administrator access required.')
    body=h.body(25_000_000 if path=='/api/plan-upload' else 256000)
    if path=='/api/plan-upload':
        raw,w,ht=clean_svg(body.get('svg'));pid=hashlib.sha256(raw).hexdigest()
        with store.connect() as db:db.execute('INSERT OR IGNORE INTO map_assets VALUES (?,?)',(pid,gzip.compress(raw)))
        h.respond(201,{'plan_url':'/api/plan-assets/'+pid,'image_width':w,'image_height':ht});return True
    if not isinstance(body.get('version'),int) or isinstance(body.get('version'),bool):raise APIError(400,'Current map revision is required.')
    if path=='/api/map-restore':
        if not isinstance(body.get('restore_version'),int) or isinstance(body.get('restore_version'),bool) or body['restore_version']<1:raise APIError(400,'Choose a valid map revision.')
        data=current(store,body.get('restore_version'))
    else:
        old=current(store);data={k:old[k] for k in ('metres_per_pixel','calibration','grid_origin','landmarks','floors')}
        calibration=body.get('calibration')
        if calibration is not None:
            if not isinstance(calibration,dict):raise APIError(400,'Invalid calibration.')
            a,b=point(calibration.get('a')),point(calibration.get('b'));metres=number(calibration.get('metres'),True);pixels=math.dist(a,b)
            if pixels<1:raise APIError(400,'Choose calibration points at least one plan pixel apart.')
            data['calibration']={'a':a,'b':b,'metres':metres};data['metres_per_pixel']=metres/pixels
            if not 1e-9<=data['metres_per_pixel']<=1e6:raise APIError(400,'Calibration scale is outside the supported range.')
        data['grid_origin']=point(body.get('grid_origin',data['grid_origin']))
        markers=body.get('landmarks',data['landmarks'])
        if not isinstance(markers,list) or len(markers)>40:raise APIError(400,'Use at most 40 landmarks.')
        data['landmarks']=[]
        for marker in markers:
            if not isinstance(marker,dict):raise APIError(400,'Invalid landmark.')
            name=marker.get('name')
            if not isinstance(name,str) or not name.strip() or len(name)>100:raise APIError(400,'Landmark names must contain 1–100 characters.')
            data['landmarks'].append({'name':name.strip(),'point':point(marker.get('point'))})
        replacement=body.get('replacement')
        if replacement:
            if not isinstance(replacement,dict):raise APIError(400,'Invalid replacement plan.')
            floor=next((f for f in data['floors'] if f['id']==replacement.get('floor_id')),None)
            if not floor:raise APIError(400,'Unknown floor.')
            url=replacement.get('plan_url','');pid=url.rsplit('/',1)[-1]
            with store.connect() as db:asset=db.execute('SELECT svg FROM map_assets WHERE id=?',(pid,)).fetchone()
            if url!='/api/plan-assets/'+pid or not asset:raise APIError(400,'Upload the replacement SVG first.')
            matrix=replacement.get('transform')
            if not isinstance(matrix,list) or len(matrix)!=6:raise APIError(400,'Alignment matrix is required.')
            a,b,c,d,e,f=[number(x) for x in matrix]
            if a*a+b*b<1e-12 or abs(c+b)>1e-7 or abs(d-a)>1e-7:raise APIError(400,'Alignment must preserve shape proportions.')
            _,w,ht=clean_svg(gzip.decompress(asset[0]).decode())
            floor.update(plan_url=url,transform=matrix,image_width=w,image_height=ht)
    data={k:v for k,v in data.items() if k not in ('version','actor','changed_at')}
    h.respond(200,save(store,actor,body.get('version'),data));return True
