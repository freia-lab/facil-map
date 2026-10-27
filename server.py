#!/usr/bin/env python3
"""FREIA interactive facility plan. Python 3.10+. Pillow enables photo uploads."""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
from pathlib import Path
import secrets
import sqlite3
import sys
if __name__ == "__main__":
    sys.modules.setdefault("server",sys.modules[__name__])
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote, parse_qs

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1440, 720
FLOORS = json.loads((ROOT/'floors.json').read_text(encoding='utf-8'))
if not FLOORS or any(not isinstance(f,dict) or not all(k in f for k in ('id','name','width','height','plan_url')) for f in FLOORS):
    raise ValueError('Invalid floors.json')
if any(not isinstance(f['width'],(int,float)) or isinstance(f['width'],bool) or not math.isfinite(f['width']) or f['width']<=0 or not isinstance(f['height'],(int,float)) or isinstance(f['height'],bool) or not math.isfinite(f['height']) or f['height']<=0 for f in FLOORS):
    raise ValueError('Floor dimensions must be finite positive numbers.')
if len({f['id'] for f in FLOORS}) != len(FLOORS):
    raise ValueError('Floor IDs must be unique.')
# Shared coordinates keep the same camera position meaningful between floors.
if any((f['width'],f['height']) != (FLOORS[0]['width'],FLOORS[0]['height']) for f in FLOORS):
    raise ValueError('All floor drawings must use the same aligned coordinate frame.')
WIDTH, HEIGHT = FLOORS[0]['width'], FLOORS[0]['height']
CATEGORIES = [
    {'id':'air','name':'Compressed air','color':'#168ca5','symbol':'A','aliases':['pressurized air','pressurised air','tryckluft','pneumatic']},
    {'id':'power','name':'Electrical power','color':'#c38416','symbol':'E','aliases':['electricity','socket','outlet','eluttag','electric']},
    {'id':'equipment','name':'Equipment','color':'#6855be','symbol':'Q','aliases':['instrument','apparatus','machine','utrustning']},
    {'id':'area','name':'Areas','color':'#438568','symbol':'Z','aliases':['zone','storage','room','område']},
    {'id':'route','name':'Routes','color':'#b5655d','symbol':'R','aliases':['pipe','cable','line','rör','path']},
]

def norm_name(value):
    return value.strip().casefold()


class APIError(Exception):
    def __init__(self, status, message, **extra):
        self.status, self.message, self.extra = status, message, extra


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def text_field(value, field, limit=1000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise APIError(400, f'{field} must be text, {"nonempty, " if required else ""}up to {limit} characters.')
    return value.strip()


def validate_object(data, categories=None):
    if not isinstance(data, dict):
        raise APIError(400, 'Object must be a JSON object.')
    obj = {k: text_field(data.get(k, ''), k, limit, required) for k, limit, required in [
        ('title', 180, True), ('description', 10000, False), ('category', 50, True)]}
    if obj['category'] not in {c['id'] for c in (CATEGORIES if categories is None else categories)}:
        raise APIError(400, 'Choose a valid category.')
    obj['floor_id'] = data.get('floor_id','ground')
    if obj['floor_id'] not in {f['id'] for f in FLOORS}:
        raise APIError(400,'Choose a valid floor.')
    obj['external_id'] = text_field(data.get('external_id',''),'external ID',160)
    obj['photos'] = []
    photos = data.get('photos',[])
    if not isinstance(photos,list) or len(photos)>20:
        raise APIError(400,'Use up to 20 photos per object.')
    for photo in photos:
        if not isinstance(photo,dict) or not isinstance(photo.get('id'),str) or not re.fullmatch(r'[0-9a-f]{64}',photo['id']):
            raise APIError(400,'Invalid photo reference.')
        if any(p['id']==photo['id'] for p in obj['photos']):
            raise APIError(400,'Duplicate photo reference.')
        obj['photos'].append({'id':photo['id'],'caption':text_field(photo.get('caption',''),'photo caption',300)})
    obj['main_photo'] = data.get('main_photo') or (obj['photos'][0]['id'] if obj['photos'] else None)
    if obj['main_photo'] is not None and obj['main_photo'] not in {p['id'] for p in obj['photos']}:
        raise APIError(400,'The main photo must belong to this object.')
    obj['status'] = data.get('status', 'unverified')
    if obj['status'] not in ['sample', 'unverified', 'verified', 'out-of-service']:
        raise APIError(400, 'Invalid status.')
    tags = data.get('tags', [])
    if not isinstance(tags, list) or len(tags) > 30:
        raise APIError(400, 'Use up to 30 keywords.')
    obj['tags'] = [text_field(x, 'keyword', 100) for x in tags if x]
    for key in ['links', 'details']:
        rows = data.get(key, [])
        if not isinstance(rows, list) or len(rows) > 30:
            raise APIError(400, f'Use up to 30 {key}.')
        obj[key] = []
        for row in rows:
            if not isinstance(row, dict):
                raise APIError(400, f'Invalid {key} row.')
            label = text_field(row.get('label', ''), 'label', 160, True)
            valkey = 'url' if key == 'links' else 'value'
            value = text_field(row.get(valkey, ''), valkey, 2000, True)
            if key == 'links':
                parsed = urlsplit(value)
                if not ((parsed.scheme in ('http', 'https') and parsed.netloc) or
                        (value.startswith('/') and not value.startswith('//') and not parsed.scheme)):
                    raise APIError(400, 'Links must use http://, https://, or a root-relative web address.')
                if any(ord(ch) < 32 for ch in value) or '\\' in value:
                    raise APIError(400, 'Invalid link address.')
            obj[key].append({'label': label, valkey: value})
    g = data.get('geometry')
    if not isinstance(g, dict) or g.get('type') not in ('point', 'rectangle', 'polygon', 'line', 'circle', 'slot'):
        raise APIError(400, 'Invalid geometry type.')
    points = g.get('points')
    typ = g['type']
    minimum = {'point': 1, 'rectangle': 2, 'polygon': 3, 'line': 2, 'circle': 2, 'slot': 3}[typ]
    if not isinstance(points, list) or not minimum <= len(points) <= 500 or (typ in ('point', 'rectangle', 'circle', 'slot') and len(points) != minimum):
        raise APIError(400, 'Invalid number of geometry vertices.')
    checked = []
    for p in points:
        if not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in p):
            raise APIError(400, 'Coordinates must be finite x,y pairs.')
        if not (0 <= p[0] <= WIDTH and 0 <= p[1] <= HEIGHT):
            raise APIError(400, 'Geometry must be within the plan.')
        checked.append([round(p[0], 4), round(p[1], 4)])
    if typ == 'rectangle' and (abs(checked[0][0]-checked[1][0]) < .1 or abs(checked[0][1]-checked[1][1]) < .1):
        raise APIError(400, 'Rectangle must have a nonzero width and height.')
    if typ == 'line' and len({tuple(p) for p in checked}) < 2:
        raise APIError(400, 'A line needs two distinct points.')
    if typ == 'polygon':
        area = abs(sum(p[0]*checked[(i+1)%len(checked)][1] - checked[(i+1)%len(checked)][0]*p[1] for i,p in enumerate(checked))) / 2
        if area < .01:
            raise APIError(400, 'Polygon must enclose an area.')
    if typ in ('circle', 'slot'):
        a, b = checked[:2]
        length = math.hypot(b[0]-a[0], b[1]-a[1])
        if length < .1:
            raise APIError(400, 'Circle radius or slot centreline must be at least 0.1 plan units.')
        if typ == 'circle':
            radius, ends = length, [a]
        else:
            normal = [-(b[1]-a[1])/length, (b[0]-a[0])/length]
            radius = abs((checked[2][0]-a[0])*normal[0] + (checked[2][1]-a[1])*normal[1])
            ends = [a, b]
            if radius < .1:
                raise APIError(400, 'Slot half-width must be at least 0.1 plan units.')
        if any(x-radius < -.0001 or x+radius > WIDTH+.0001 or y-radius < -.0001 or y+radius > HEIGHT+.0001 for x,y in ends):
            raise APIError(400, 'The whole circle or slot must fit within the plan.')
    obj['geometry'] = {'type': typ, 'points': checked}
    return obj


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # Additive v0.2 migration: snapshot an existing v0.1 database first.
            has_old_data = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='objects'").fetchone()
            has_layers = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='layers'").fetchone()
            if has_old_data and not has_layers:
                backup = self.path.with_name(self.path.stem + '.pre-v0.2-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
                with sqlite3.connect(backup) as target:
                    db.backup(target)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, object_id TEXT NOT NULL,
                    version INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
                    deleted INTEGER NOT NULL, changed_at TEXT NOT NULL, changed_by TEXT NOT NULL,
                    UNIQUE(object_id, version));
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS layers (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
                    replacement_id TEXT);
                CREATE TABLE IF NOT EXISTS layer_revisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, layer_id TEXT NOT NULL,
                    version INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
                    deleted INTEGER NOT NULL, changed_at TEXT NOT NULL, changed_by TEXT NOT NULL,
                    replacement_id TEXT, UNIQUE(layer_id, version));
            ''')
            if db.execute("SELECT value FROM metadata WHERE key='layers_initialized'").fetchone() is None:
                for layer in CATEGORIES:
                    self.write_layer(db, layer['id'], {k:v for k,v in layer.items() if k!='id'}, 'System', 'create', 1)
                db.execute("INSERT INTO metadata VALUES ('layers_initialized','1')")
            if db.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone() is None:
                for obj in self.samples():
                    self.write(db, obj['id'], validate_object(obj), 'Sample data', 'create', 1, False)
                db.execute("INSERT INTO metadata VALUES ('initialized','1')")

        self.media_dir = self.path.parent/'images'
        self.media_dir.mkdir(exist_ok=True)
        with self.connect() as db:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(objects)')}
            if 'floor_id' not in columns:
                backup = self.path.with_name(self.path.stem + '.pre-v0.3-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
                with sqlite3.connect(backup) as target:
                    db.backup(target)
                db.execute("ALTER TABLE objects ADD COLUMN floor_id TEXT NOT NULL DEFAULT 'ground'")
                db.execute('ALTER TABLE objects ADD COLUMN external_id TEXT')
                for row in db.execute('SELECT id,payload FROM objects').fetchall():
                    payload = json.loads(row['payload'])
                    payload.update(floor_id=payload.get('floor_id','ground'),external_id=payload.get('external_id') or row['id'],photos=payload.get('photos',[]),main_photo=payload.get('main_photo'))
                    db.execute('UPDATE objects SET payload=?,floor_id=?,external_id=? WHERE id=?',
                               (json.dumps(payload,ensure_ascii=False),payload['floor_id'],payload['external_id'],row['id']))
            revision_columns = {r['name'] for r in db.execute('PRAGMA table_info(revisions)')}
            if 'batch_id' not in revision_columns:
                db.execute('ALTER TABLE revisions ADD COLUMN batch_id TEXT')
            db.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS objects_external_id ON objects(external_id);
                CREATE INDEX IF NOT EXISTS objects_floor ON objects(floor_id,deleted);
                CREATE TABLE IF NOT EXISTS photos (
                    id TEXT PRIMARY KEY, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    bytes INTEGER NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS import_batches (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, actor TEXT NOT NULL,
                    applied_at TEXT NOT NULL, created_count INTEGER NOT NULL, updated_count INTEGER NOT NULL);
            """)

        from map_setup import initialize
        initialize(self)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @staticmethod
    def samples():
        def item(name, cat, typ, points, details=(), tags=()):
            return {'id':str(uuid.uuid5(uuid.NAMESPACE_URL, 'freia-prototype:'+name)), 'title':name, 'category':cat,
                'status':'sample','description':'Illustrative record only. Its position and technical values are invented; replace after checking the facility.',
                'tags':list(tags), 'details':[{'label':k,'value':v} for k,v in details],
                'links':[{'label':'Example documentation — placeholder','url':'/sample-document.html'}],
                'geometry':{'type':typ,'points':points}}
        return [
            item('AIR-01 · West hall', 'air', 'point', [[295,445]], [('Connector','Example quick coupling'),('Pressure','Example: 6 bar — unverified')], ['pressurized air','tryckluft']),
            item('AIR-02 · Central hall', 'air', 'point', [[660,545]], [('Connector','Example quick coupling')]),
            item('AIR-03 · East hall', 'air', 'point', [[1100,450]], [('Owner','Example technical contact')]),
            item('POWER-01 · Service outlet', 'power', 'point', [[830,338]], [('Supply','Example: 230 V — unverified')]),
            item('Example equipment footprint', 'equipment', 'rectangle', [[710,390],[957,550]], [('Asset ID','DEMO-EQ-001')]),
            item('Example storage area', 'area', 'polygon', [[465,595],[630,595],[650,645],[465,645]]),
            item('Example pipe route', 'route', 'line', [[295,445],[295,370],[1100,370],[1100,450]]),
        ]

    @staticmethod
    def unpack(row):
        return {**json.loads(row['payload']), 'id':row['id'], 'version':row['version'],
                'deleted':bool(row['deleted']), 'updated_at':row['updated_at'], 'updated_by':row['updated_by']}

    def list_objects(self, include_deleted=False):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM objects' + ('' if include_deleted else ' WHERE deleted=0') + ' ORDER BY updated_at DESC, id').fetchall()
        return [self.unpack(r) for r in rows]

    def get(self, oid, db=None):
        if db is None:
            with self.connect() as connection:
                return self.get(oid, connection)
        row = db.execute('SELECT * FROM objects WHERE id=?', (oid,)).fetchone()
        if not row:
            raise APIError(404, 'Object not found.')
        return self.unpack(row)

    def write(self, db, oid, payload, actor, action, version, deleted):
        payload = dict(payload)
        payload['floor_id'] = payload.get('floor_id','ground')
        payload['external_id'] = payload.get('external_id') or oid
        # Initial v0.1/v0.2 seeding runs before the v0.3 columns exist.
        cols = {r['name'] for r in db.execute('PRAGMA table_info(objects)')}
        if 'external_id' in cols:
            other = db.execute('SELECT id FROM objects WHERE external_id=? AND id!=?',(payload['external_id'],oid)).fetchone()
            if other:
                raise APIError(409,'That external ID already belongs to another object.')
            for photo in payload.get('photos',[]):
                if not db.execute('SELECT 1 FROM photos WHERE id=?',(photo['id'],)).fetchone():
                    raise APIError(400,'A referenced photo does not exist.')
        stamp, raw = now(), json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if 'external_id' in cols:
            db.execute('INSERT OR REPLACE INTO objects(id,version,deleted,payload,updated_at,updated_by,floor_id,external_id) VALUES (?,?,?,?,?,?,?,?)',
                       (oid,version,int(deleted),raw,stamp,actor,payload['floor_id'],payload['external_id']))
        else:
            db.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?)', (oid,version,int(deleted),raw,stamp,actor))
        db.execute('INSERT INTO revisions(object_id,version,action,payload,deleted,changed_at,changed_by) VALUES (?,?,?,?,?,?,?)',
                   (oid,version,action,raw,int(deleted),stamp,actor))
        return self.get(oid, db)

    def mutate(self, actor, action, oid=None, data=None, version=None, restore_version=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            layers = self.list_layers(db=db)
            if action == 'create':
                return self.write(db, str(uuid.uuid4()), validate_object(data, layers), actor, action, 1, False)
            current = self.get(oid, db)
            if isinstance(version, bool) or not isinstance(version, int) or current['version'] != version:
                raise APIError(409, 'This object changed since you opened it. Your draft is retained; review the latest version before saving.', current=current)
            deleted = False
            if action == 'update':
                if current['deleted']:
                    raise APIError(409, 'This object was deleted. Restore it before editing.', current=current)
                payload = validate_object(data, layers)
            elif action == 'delete':
                if current['deleted']:
                    raise APIError(409, 'Object is already deleted.', current=current)
                payload, deleted = validate_object(current, self.list_layers(True, db)), True
            elif action == 'restore':
                if isinstance(restore_version,bool) or not isinstance(restore_version,int):
                    raise APIError(400, 'Choose a revision to restore.')
                row = db.execute('SELECT * FROM revisions WHERE object_id=? AND version=?', (oid,restore_version)).fetchone()
                if not row:
                    raise APIError(404, 'Revision not found.')
                if row['deleted']:
                    raise APIError(400, 'Choose a revision from before deletion.')
                payload = json.loads(row['payload'])
                active_ids = {layer['id'] for layer in layers}
                if payload['category'] not in active_ids:
                    # Restore content/geometry, using the successor of a removed
                    # layer (or the object's current layer when no successor exists).
                    seen, candidate = set(), payload['category']
                    while candidate and candidate not in active_ids and candidate not in seen:
                        seen.add(candidate)
                        archived = self.get_layer(candidate, db)
                        candidate = archived.get('replacement_id')
                    payload['category'] = candidate if candidate in active_ids else current['category']
                payload = validate_object(payload, layers)
                action = 'restore:'+str(restore_version)
            else:
                raise APIError(400, 'Invalid operation.')
            return self.write(db, oid, payload, actor, action, current['version']+1, deleted)

    def history(self, oid):
        self.get(oid)
        with self.connect() as db:
            return [dict(r) | {'payload':json.loads(r['payload']), 'deleted':bool(r['deleted'])}
                    for r in db.execute('SELECT * FROM revisions WHERE object_id=? ORDER BY version DESC', (oid,))]

    def activity(self):
        with self.connect() as db:
            rows = db.execute('SELECT r.*,o.payload AS current_payload FROM revisions r JOIN objects o ON o.id=r.object_id ORDER BY seq DESC LIMIT 200').fetchall()
        return [{'object_id':r['object_id'],'version':r['version'],'action':r['action'],
                 'title':json.loads(r['current_payload'])['title'],'changed_at':r['changed_at'],'changed_by':r['changed_by']} for r in rows]

    def export(self):
        # A read transaction ensures a single consistent database snapshot.
        with self.connect() as db:
            db.execute('BEGIN')
            objects = [self.unpack(r) for r in db.execute('SELECT * FROM objects ORDER BY id')]
            revisions = [dict(r) | {'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM revisions ORDER BY seq')]
            categories = self.list_layers(True, db)
            layer_revisions = [dict(r) | {'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM layer_revisions ORDER BY seq')]
        from map_setup import current
        return {'schema_version':4,'map_settings':current(self),'exported_at':now(),'plan':{'width':WIDTH,'height':HEIGHT,'coordinate_system':'x,y from visible top-left'},
                'categories':categories,'objects':objects,'revisions':revisions,'layer_revisions':layer_revisions,'floors':current(self)['floors'],'photos':self.photo_metadata(),'import_batches':self.import_batches()}

    def photo_metadata(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM photos ORDER BY created_at,id')]

    def import_batches(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM import_batches ORDER BY applied_at DESC')]

    def sync_token(self):
        with self.connect() as db:
            objects = db.execute('SELECT COALESCE(MAX(seq),0) FROM revisions').fetchone()[0]
            layers = db.execute('SELECT COALESCE(MAX(seq),0) FROM layer_revisions').fetchone()[0]
        return f'{objects}:{layers}'

    def list_layers(self, include_deleted=False, db=None):
        if db is None:
            with self.connect() as connection:
                return self.list_layers(include_deleted, connection)
        rows = db.execute('SELECT * FROM layers' + ('' if include_deleted else ' WHERE deleted=0') + ' ORDER BY rowid').fetchall()
        return [{**self.unpack(r), 'replacement_id':r['replacement_id']} for r in rows]

    def get_layer(self, lid, db=None):
        if db is None:
            with self.connect() as connection:
                return self.get_layer(lid, connection)
        row = db.execute('SELECT * FROM layers WHERE id=?', (lid,)).fetchone()
        if not row:
            raise APIError(404, 'Layer not found.')
        return {**self.unpack(row), 'replacement_id':row['replacement_id']}

    @staticmethod
    def validate_layer(data):
        if not isinstance(data,dict):
            raise APIError(400,'Layer must be an object.')
        name = text_field(data.get('name',''),'layer name',100,True)
        color = text_field(data.get('color',''),'layer colour',7,True)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
            raise APIError(400,'Choose a six-digit hexadecimal colour.')
        symbol = text_field(data.get('symbol',''),'marker symbol',3,True)
        aliases = data.get('aliases',[])
        if not isinstance(aliases,list) or len(aliases)>30:
            raise APIError(400,'Use up to 30 search aliases.')
        return {'name':name,'color':color,'symbol':symbol,'aliases':[text_field(a,'alias',100,True) for a in aliases]}

    def write_layer(self, db, lid, payload, actor, action, version, deleted=False, replacement=None):
        stamp, raw = now(), json.dumps(payload,ensure_ascii=False,allow_nan=False)
        db.execute('INSERT INTO layers VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,deleted=excluded.deleted,payload=excluded.payload,updated_at=excluded.updated_at,updated_by=excluded.updated_by,replacement_id=excluded.replacement_id',(lid,version,int(deleted),raw,stamp,actor,replacement))
        db.execute('INSERT INTO layer_revisions(layer_id,version,action,payload,deleted,changed_at,changed_by,replacement_id) VALUES (?,?,?,?,?,?,?,?)',
                   (lid,version,action,raw,int(deleted),stamp,actor,replacement))
        return self.get_layer(lid,db)

    def mutate_layer(self, actor, action, lid=None, data=None, version=None, replacement=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            layers = self.list_layers(db=db)
            if action == 'create':
                payload = self.validate_layer(data)
                if any(norm_name(l['name']) == norm_name(payload['name']) for l in layers):
                    raise APIError(400,'An active layer already has that name.')
                return {'layer':self.write_layer(db,str(uuid.uuid4()),payload,actor,'create',1),'moved_objects':0}
            current = self.get_layer(lid,db)
            if isinstance(version,bool) or not isinstance(version,int) or version != current['version'] or current['deleted']:
                raise APIError(409,'This layer changed. Reload layers before saving.',current=current)
            moved = 0
            if action == 'update':
                payload = self.validate_layer(data)
                if any(l['id']!=lid and norm_name(l['name']) == norm_name(payload['name']) for l in layers):
                    raise APIError(400,'An active layer already has that name.')
                result = self.write_layer(db,lid,payload,actor,'update',version+1)
            elif action == 'delete':
                if len(layers)<=1:
                    raise APIError(400,'Keep at least one active layer.')
                if replacement is not None and (not isinstance(replacement,str) or replacement not in {l['id'] for l in layers if l['id']!=lid}):
                    raise APIError(400,'Choose another active layer for reassignment.')
                records = [self.unpack(row) for row in db.execute('SELECT * FROM objects')]
                affected = [o for o in records if o['category']==lid]
                if affected and not replacement:
                    raise APIError(400,'This layer contains objects, including recoverable deleted records. Choose a destination layer.')
                for obj in affected:
                    payload = validate_object({**obj,'category':replacement},layers)
                    self.write(db,obj['id'],payload,actor,'move-layer',obj['version']+1,obj['deleted'])
                    moved += 1
                result = self.write_layer(db,lid,{k:current[k] for k in ('name','color','symbol','aliases')},actor,'delete',version+1,True,replacement)
            else:
                raise APIError(400,'Invalid layer operation.')
            return {'layer':result,'moved_objects':moved}

    def create_user(self, username, password):
        username = text_field(username,'username',100,True)
        if len(password) < 10:
            raise ValueError('Use a password of at least 10 characters.')
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO users VALUES (?,?,?)', (username,salt,hashed))

    def authenticate(self, username, password):
        with self.connect() as db:
            row = db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        salt = row['salt'] if row else '0'*32
        actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex()
        return bool(row and hmac.compare_digest(actual,row['password_hash']))


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store, auth='demo', secure_cookie=False):
        self.store, self.auth, self.secure_cookie = store, auth, secure_cookie
        self.sessions, self.failed_logins = {}, {}
        self.import_previews = {}
        self.import_lock = __import__('threading').Lock()
        self.photo_slots = __import__('threading').BoundedSemaphore(2)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'FREIA-Map/0.4'
    idle_timeout = 30
    protocol_version = 'HTTP/1.1'
    def setup(self):
        super().setup()
        self.connection.settimeout(self.idle_timeout)

    def handle_one_request(self):
        self._dispatch_started = False
        self._request_started = False
        super().handle_one_request()

    def parse_request(self):
        self._request_started = True
        return super().parse_request()

    def log_error(self, fmt, *args):
        # BaseHTTPRequestHandler labels idle keep-alive/preconnect expiry as a
        # request error. It already closes the socket; only that noise is quiet.
        if fmt == "Request timed out: %r" and not self._request_started:
            return
        super().log_error(fmt, *args)

    def log_message(self, fmt, *args):
        # Do not log request bodies, passwords, or cookie headers.
        sys.stderr.write('%s %s\n' % (self.log_date_time_string(), fmt % args))

    def do_GET(self): self.dispatch('GET')
    def do_POST(self): self.dispatch('POST')
    def do_PUT(self): self.dispatch('PUT')
    def do_DELETE(self): self.dispatch('DELETE')

    def dispatch(self, method):
        self._dispatch_started = True
        try:
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/'):
                self.api(method, path)
            elif method == 'GET':
                self.static(path)
            else:
                raise APIError(405, 'Method not allowed.')
        except APIError as exc:
            self.respond(exc.status, {'error':exc.message, **exc.extra})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.respond(400, {'error':'Invalid JSON.'})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except TimeoutError:
            self.log_error('Active request timed out: %s %s',method,self.path)
            self.close_connection = True
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500, {'error':'Server error. Check the server log.'})

    def security_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'")

    def respond(self, status, body, cookie=None):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        if status >= 400:
            # Failed authorization can leave a request body unread. Close the
            # connection so it is never parsed or logged as another request.
            self.close_connection = True
            self.send_header('Connection','close')
        self.security_headers()
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(raw)

    def body(self, max_size=256000):
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            raise APIError(415,'Send application/json.')
        try:
            size = int(self.headers.get('Content-Length','0'))
        except ValueError:
            raise APIError(400,'Invalid request size.')
        if not 0 < size <= max_size:
            raise APIError(413,f'Request exceeds {max_size} bytes or has no body.')
        body = json.loads(self.rfile.read(size))
        if not isinstance(body,dict):
            raise APIError(400,'Request must be an object.')
        return body

    def same_origin(self):
        origin = self.headers.get('Origin')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise APIError(403,'Cross-site writes are blocked.')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            raise APIError(403,'Cross-site writes are blocked.')

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
        except Exception:
            return None
        token = cookie.get('freia_session')
        session = self.server.sessions.get(token.value) if token else None
        return session if session and session['expires'] > time.time() else None

    def user_is_admin(self,username):
        with self.server.store.connect() as db:return bool(db.execute("SELECT 1 FROM admin_users WHERE username=?",(username,)).fetchone())

    def actor(self):
        session = self.session()
        if not session:
            raise APIError(401,'Sign in before editing.')
        return session['username']

    def api(self, method, path):
        store = self.server.store
        if method != 'GET':
            self.same_origin()
        from map_setup import setup_api, current, is_admin
        if setup_api(self,method,path):return
        from integrations import feature_api
        if feature_api(self,method,path):
            return
        if method == 'GET' and path == '/api/config':
            return self.respond(200, {'width':WIDTH,'height':HEIGHT,'categories':store.list_layers(),'archived_categories':[l for l in store.list_layers(True) if l['deleted']],'auth_mode':self.server.auth,'plan_url':FLOORS[0]['plan_url'],'floors':current(store)['floors'],'map_settings':current(store)})
        if method == 'GET' and path == '/api/session':
            s = self.session()
            return self.respond(200, {'username':s['username'] if s else None,'auth_mode':self.server.auth,'is_admin':is_admin(self)})
        if method == 'POST' and path == '/api/session':
            data = self.body()
            username = text_field(data.get('username',''),'name',100,True)
            if self.server.auth == 'accounts':
                password = data.get('password','')
                if not isinstance(password,str) or len(password)>2000:
                    raise APIError(400,'Invalid password.')
                key = self.client_address[0]
                attempts = [t for t in self.server.failed_logins.get(key,[]) if t > time.time()-60]
                if len(attempts) >= 10:
                    raise APIError(429,'Too many login attempts. Try again in a minute.')
                if not store.authenticate(username,password):
                    self.server.failed_logins[key] = attempts + [time.time()]
                    raise APIError(401,'Incorrect username or password.')
                self.server.failed_logins.pop(key,None)
            session_id = secrets.token_urlsafe(32)
            # Remove expired sessions while preserving active sessions.
            self.server.sessions = {k:v for k,v in self.server.sessions.items() if v['expires'] > time.time()}
            self.server.sessions[session_id] = {'username':username,'expires':time.time()+12*3600}
            cookie = f'freia_session={session_id}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200' + ('; Secure' if self.server.secure_cookie else '')
            return self.respond(200, {'username':username,'auth_mode':self.server.auth,'is_admin':self.server.auth=='demo' or self.user_is_admin(username)},cookie)
        if method == 'DELETE' and path == '/api/session':
            cookie = SimpleCookie(); cookie.load(self.headers.get('Cookie',''))
            if cookie.get('freia_session'):
                self.server.sessions.pop(cookie['freia_session'].value,None)
            return self.respond(200, {'ok':True},'freia_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
        if method == 'GET' and path == '/api/objects':
            return self.respond(200, {'objects':store.list_objects()})
        if method == 'GET' and path == '/api/activity':
            return self.respond(200, {'activity':store.activity()})
        if method == 'GET' and path == '/api/export':
            return self.respond(200, store.export())
        if method == 'GET' and path == '/api/layers':
            records = store.list_objects(True)
            layers = [{**l,'object_count':sum(o['category']==l['id'] and not o['deleted'] for o in records),
                       'deleted_object_count':sum(o['category']==l['id'] and o['deleted'] for o in records)} for l in store.list_layers(True)]
            return self.respond(200, {'layers':layers})
        if method == 'POST' and path == '/api/layers':
            return self.respond(201,store.mutate_layer(self.actor(),'create',data=self.body()))
        layer_parts = path.strip('/').split('/')
        if len(layer_parts)==3 and layer_parts[:2]==['api','layers'] and method in ('PUT','DELETE'):
            actor, data = self.actor(), self.body()
            return self.respond(200,store.mutate_layer(actor,'update' if method=='PUT' else 'delete',layer_parts[2],
                                data=data,version=data.get('version'),replacement=data.get('replacement_id')))
        if method == 'POST' and path == '/api/objects':
            return self.respond(201, store.mutate(self.actor(),'create',data=self.body()))
        parts = path.strip('/').split('/')
        if len(parts) >= 3 and parts[:2] == ['api','objects']:
            oid = parts[2]
            if len(parts) == 3:
                if method == 'GET': return self.respond(200,store.get(oid))
                if method in ['PUT','DELETE']:
                    actor, data = self.actor(), self.body()
                    return self.respond(200,store.mutate(actor,'update' if method == 'PUT' else 'delete',oid,data=data,version=data.get('version')))
            if len(parts) == 4 and parts[3] == 'history' and method == 'GET':
                return self.respond(200, {'revisions':store.history(oid)})
            if len(parts) == 4 and parts[3] == 'restore' and method == 'POST':
                actor, data = self.actor(), self.body()
                return self.respond(200,store.mutate(actor,'restore',oid,version=data.get('version'),restore_version=data.get('restore_version')))
        raise APIError(404,'Endpoint not found.')

    def static(self, path):
        if path.startswith('/media/'):
            from photos import serve_photo
            return serve_photo(self,path)
        public = (ROOT/'static').resolve()
        target = (public / (path.lstrip('/') or 'index.html')).resolve()
        if not target.is_relative_to(public) or not target.is_file():
            raise APIError(404,'File not found.')
        mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if mime.startswith('text/') or target.suffix == '.js':
            mime += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type',mime)
        self.send_header('Cache-Control','no-cache')
        self.security_headers()
        import gzip
        if target.suffix == '.svg' and 'gzip' in self.headers.get('Accept-Encoding',''):
            # Precomputed on packaging; plan remains available uncompressed too.
            compressed = target.with_suffix('.svg.gz')
            if compressed.is_file():
                raw = compressed.read_bytes()
            else:
                raw = gzip.compress(target.read_bytes(),mtime=0)
            self.send_header('Content-Encoding','gzip')
            self.send_header('Vary','Accept-Encoding')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        else:
            self.send_header('Content-Length',str(target.stat().st_size))
            self.end_headers()
            import shutil
            with target.open('rb') as f:
                shutil.copyfileobj(f,self.wfile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--data',type=Path,default=ROOT/'data/freia.sqlite3')
    parser.add_argument('--auth',choices=['demo','accounts'],default='demo')
    parser.add_argument('--secure-cookie',action='store_true',help='Enable when serving through an HTTPS reverse proxy.')
    parser.add_argument('--create-user',metavar='USERNAME',help='Create or update a local account, then exit.')
    parser.add_argument('--set-role',metavar='USERNAME',help='Set an existing account role, then exit.')
    parser.add_argument('--role',choices=['admin','editor'],default='editor')
    args = parser.parse_args()
    store = Store(args.data)
    if args.set_role:
        with store.connect() as db:
            if not db.execute('SELECT 1 FROM users WHERE username=?',(args.set_role,)).fetchone():parser.error('Account does not exist.')
            if args.role=='admin':db.execute('INSERT OR IGNORE INTO admin_users VALUES (?)',(args.set_role,))
            else:db.execute('DELETE FROM admin_users WHERE username=?',(args.set_role,))
        print('Account role updated.');return
    if args.create_user:
        import getpass
        password = getpass.getpass('Password (at least 10 characters): ')
        if password != getpass.getpass('Repeat password: '):
            parser.error('Passwords do not match.')
        try: store.create_user(args.create_user,password)
        except ValueError as exc: parser.error(str(exc))
        print(f'Account {args.create_user!r} created or updated.'); return
    if args.host not in ('127.0.0.1','localhost','::1') and args.auth != 'accounts':
        parser.error('Shared network hosting requires --auth accounts. Create accounts with --create-user first.')
    if args.auth == 'accounts':
        with store.connect() as db:
            if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                parser.error('Create an account with --create-user USERNAME first.')
    server = AppServer((args.host,args.port),store,args.auth,args.secure_cookie)
    print(f'FREIA map: http://{args.host}:{args.port}  |  mode: {args.auth}', flush=True)
    print(f'Database: {args.data.resolve()}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__':
    main()
