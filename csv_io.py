"""Spreadsheet-friendly CSV preview/apply. Coordinates are parsed, never evaluated."""
import csv
import io
import json
import math
import re
import uuid
from server import APIError, FLOORS, now, validate_object

COLUMNS=['external_id','name','floor','layer','shape','coordinates','radius','description','status','tags','details','links']
NUMBER=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
PAIR=re.compile(r'\(\s*('+NUMBER+r')\s*,\s*('+NUMBER+r')\s*\)')


def escape_cell(value):
    if isinstance(value,str) and (value.startswith("'") or value.lstrip().startswith(('=','+','-','@'))):
        return "'"+value
    return value


def unescape_cell(value):
    if isinstance(value,str) and (value.startswith("''") or (value.startswith("'") and value[1:].lstrip().startswith(('=','+','-','@')))):
        return value[1:]
    return value


def parse_coordinates(text):
    if not isinstance(text,str) or len(text)>40000:raise ValueError('Coordinates are too long.')
    points=[];end=0
    for match in PAIR.finditer(text):
        separator=text[end:match.start()].strip()
        if separator not in ('',',') or (points and separator!=','):raise ValueError('Use coordinates such as (100,200),(300,400).')
        point=[float(match[1]),float(match[2])]
        if not all(math.isfinite(v) for v in point):raise ValueError('Coordinates must be finite numbers.')
        points.append(point);end=match.end()
        if len(points)>500:raise ValueError('Use up to 500 vertices.')
    if text[end:].strip() or not points:raise ValueError('Use coordinates such as (100,200),(300,400).')
    return points


def geometry_from_row(row):
    typ=row['shape'].strip().casefold();points=parse_coordinates(row['coordinates'])
    if typ in ('circle','slot'):
        try:radius=float(row.get('radius',''))
        except ValueError:raise ValueError('Circle and slot need a numeric radius.')
        if not math.isfinite(radius) or radius<.1:raise ValueError('Radius must be at least 0.1 plan units.')
        if typ=='circle':
            if len(points)!=1:raise ValueError('A circle uses one centre coordinate plus radius.')
            points=[points[0],[points[0][0]+radius,points[0][1]]]
        else:
            if len(points)!=2:raise ValueError('A slot uses two end centres plus radius (half-width).')
            a,b=points;dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
            if length<.1:raise ValueError('Slot end centres must be distinct.')
            points=[a,b,[(a[0]+b[0])/2-dy/length*radius,(a[1]+b[1])/2+dx/length*radius]]
    return {'type':typ,'points':points}


def equivalent_geometry(a,b):
    if a['type']!=b['type']:return False
    if a['type']=='circle':
        pairs=zip(a['points'][0],b['points'][0]);ra=math.dist(*a['points']);rb=math.dist(*b['points'])
        return all(abs(x-y)<.001 for x,y in pairs) and abs(ra-rb)<.001
    if a['type']=='slot':
        def radius(g):
            x,y,w=g['points'];length=math.dist(x,y)
            return abs((w[0]-x[0])*(-(y[1]-x[1]))+(w[1]-x[1])*(y[0]-x[0]))/length
        return all(abs(x-y)<.001 for p,q in zip(a['points'][:2],b['points'][:2]) for x,y in zip(p,q)) and abs(radius(a)-radius(b))<.001
    return a==b


def parse_pairs(text,key):
    result=[]
    for line in text.splitlines():
        if not line.strip():continue
        label,sep,value=line.partition('|')
        if not sep or not label.strip() or not value.strip():raise ValueError('Use one label | value per line for details and links.')
        result.append({'label':label.strip(),key:value.strip()})
    return result


def preview_csv(store,text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>2_000_000:raise APIError(413,'CSV must be UTF-8 text up to 2 MB.')
    text=text.lstrip('\ufeff')
    try:
        dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
    except csv.Error:dialect=csv.excel
    reader=csv.DictReader(io.StringIO(text,newline=''),dialect=dialect)
    required={'external_id','name','floor','layer','shape','coordinates'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):raise APIError(400,'CSV needs columns: '+', '.join(sorted(required))+'. Download the template.')
    if len(reader.fieldnames)!=len(set(reader.fieldnames)) or any(c not in COLUMNS for c in reader.fieldnames):raise APIError(400,'CSV has duplicate or unsupported columns. Use the template headers.')
    with store.connect() as db:
        db.execute('BEGIN')
        existing={o['external_id']:o for o in [store.unpack(r) for r in db.execute('SELECT * FROM objects')]}
        layers=store.list_layers(db=db)
    layer_names={l['name'].casefold():l['id'] for l in layers};layer_names.update({l['id']:l['id'] for l in layers})
    floors={f['name'].casefold():f['id'] for f in FLOORS};floors.update({f['id']:f['id'] for f in FLOORS})
    changes=[];rows=[];errors=[];seen=set()
    try:
        for index,row in enumerate(reader,2):
            if index>5001:raise APIError(413,'Use up to 5,000 records per import.')
            try:
                if None in row or any(v is None for v in row.values()):raise ValueError('Row has the wrong number of columns.')
                row={k:unescape_cell(v) for k,v in row.items()}
                ext=row['external_id'].strip()
                if not ext:raise ValueError('A stable external_id is required.')
                if ext in seen:raise ValueError('Duplicate external_id in this file.')
                seen.add(ext);current=existing.get(ext)
                if current and current['deleted']:raise ValueError('This external ID belongs to a deleted object. Restore it first or use a different ID.')
                floor=floors.get(row['floor'].strip().casefold()) or floors.get(row['floor'].strip())
                layer=layer_names.get(row['layer'].strip().casefold()) or layer_names.get(row['layer'].strip())
                if not floor:raise ValueError('Unknown floor. Use its name or ID.')
                if not layer:raise ValueError('Unknown layer. Create it in Manage layers first.')
                payload=dict(current or {});payload.update(external_id=ext,title=row['name'].strip(),floor_id=floor,category=layer,geometry=geometry_from_row(row))
                if current and equivalent_geometry(payload['geometry'],current['geometry']):payload['geometry']=current['geometry']
                for field in ('description','status'):
                    if field in row:payload[field]=row[field].strip()
                if not payload.get('status'):payload['status']='unverified'
                if 'tags' in row:payload['tags']=[v.strip() for v in row['tags'].split('|') if v.strip()]
                if 'details' in row:payload['details']=parse_pairs(row['details'],'value')
                if 'links' in row:payload['links']=parse_pairs(row['links'],'url')
                payload=validate_object(payload,layers)
                old=validate_object(current,layers) if current else None
                action='unchanged' if old==payload else 'update' if current else 'create'
                changed_fields=[key for key in payload if old is not None and payload[key]!=old[key]]
                rows.append({'row':index,'external_id':ext,'name':payload['title'],'floor':floor,'action':action,'changed_fields':changed_fields})
                if action!='unchanged':changes.append({'row':index,'external_id':ext,'id':current['id'] if current else None,'version':current['version'] if current else None,'payload':payload,'action':action})
            except (ValueError,APIError) as exc:
                errors.append({'row':index,'external_id':row.get('external_id',''),'error':exc.message if isinstance(exc,APIError) else str(exc)})
    except csv.Error as exc:raise APIError(400,'Malformed CSV: '+str(exc))
    if not rows and not errors:raise APIError(400,'CSV has no object rows.')
    return {'rows':rows,'errors':errors,'changes':changes,'layer_versions':{l['id']:l['version'] for l in layers},'summary':{k:sum(r['action']==k for r in rows) for k in ('create','update','unchanged')}|{'errors':len(errors)}}


def apply_preview(store,preview,actor,filename):
    if preview['errors']:raise APIError(400,'Fix the preview errors before applying.')
    batch=str(uuid.uuid4());created=updated=0
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');layers=store.list_layers(db=db)
        versions={l['id']:l['version'] for l in layers}
        used={c['payload']['category'] for c in preview['changes']}
        if any(versions.get(lid)!=preview['layer_versions'].get(lid) for lid in used):raise APIError(409,'A destination layer changed after preview. Preview the file again.')
        for change in preview['changes']:
            if change['id']:
                current=store.get(change['id'],db)
                if current['version']!=change['version'] or current['deleted']:raise APIError(409,'An object changed after preview: '+change['external_id']+'. Preview the file again.')
            elif db.execute('SELECT 1 FROM objects WHERE external_id=?',(change['external_id'],)).fetchone():raise APIError(409,'An external ID was added after preview: '+change['external_id']+'. Preview again.')
        for change in preview['changes']:
            oid=change['id'] or str(uuid.uuid4());version=(change['version'] or 0)+1
            payload=validate_object(change['payload'],layers)
            store.write(db,oid,payload,actor,'import',version,False)
            db.execute('UPDATE revisions SET batch_id=? WHERE object_id=? AND version=?',(batch,oid,version))
            if change['id']:updated+=1
            else:created+=1
        db.execute('INSERT INTO import_batches VALUES (?,?,?,?,?,?)',(batch,filename,actor,now(),created,updated))
    return {'batch_id':batch,'created':created,'updated':updated}


def export_csv(store,objects=None):
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=COLUMNS);writer.writeheader()
    layers={l['id']:l['name'] for l in store.list_layers(True)}
    for obj in objects if objects is not None else store.list_objects():
        g=obj['geometry'];points=g['points'];radius=''
        if g['type']=='circle':radius=format(math.dist(*points),'.9g');points=points[:1]
        elif g['type']=='slot':
            a,b,w=points;length=math.dist(a,b);radius=format(abs((w[0]-a[0])*(-(b[1]-a[1]))+(w[1]-a[1])*(b[0]-a[0]))/length,'.9g');points=points[:2]
        coords=','.join('('+','.join(format(v,'.9g') for v in p)+')' for p in points)
        record={'external_id':obj['external_id'],'name':obj['title'],'floor':obj['floor_id'],'layer':layers.get(obj['category'],obj['category']),'shape':g['type'],'coordinates':coords,'radius':radius,'description':obj['description'],'status':obj['status'],'tags':' | '.join(obj['tags']),'details':'\n'.join(r['label']+' | '+r['value'] for r in obj['details']),'links':'\n'.join(r['label']+' | '+r['url'] for r in obj['links'])}
        writer.writerow({k:escape_cell(v) for k,v in record.items()})
    return '\ufeff'+out.getvalue()
