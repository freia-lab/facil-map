"""v0.3 floors, reviewed imports, photo history, backup restore, and HTTP endpoints."""
import base64
import http.client
import importlib.util
import io
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store,APIError,AppServer
from csv_io import export_csv,preview_csv,apply_preview,parse_coordinates
from photos import upload_photo
from backup_support import make_backup,restore_backup
from PIL import Image

class FeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'app/data/freia.sqlite3';self.store=Store(self.path)
        self.air=next(o for o in self.store.list_objects() if o['category']=='air')
    def tearDown(self):self.temp.cleanup()
    def test_floor_separation_and_stable_external_ids(self):
        upper=self.store.mutate('Test','create',data={**self.air,'external_id':'UPPER-1','floor_id':'upper'})
        self.assertEqual(upper['floor_id'],'upper');self.assertEqual(Store(self.path).get(upper['id'])['external_id'],'UPPER-1')
        self.assertEqual(sum(o['floor_id']=='upper' for o in self.store.list_objects()),1)
        with self.assertRaises(APIError):self.store.mutate('Test','create',data={**self.air,'external_id':'UPPER-1'})
        with self.assertRaises(APIError):self.store.mutate('Test','create',data={**self.air,'external_id':'','floor_id':'unknown'})
    def csv(self,rows):return 'external_id,name,floor,layer,shape,coordinates,radius,description\n'+rows
    def test_csv_all_shape_roundtrips_and_idempotence(self):
        rows='POINT,A,upper,Compressed air,point,"(100,200)",,Point\nRECT,B,ground,Areas,rectangle,"(200,300),(400,500)",,Rectangle\nPOLY,C,ground,Areas,polygon,"(200,200),(300,200),(250,300)",,Polygon\nLINE,D,upper,Routes,line,"(100,100),(200,200),(300,200)",,Line\nCIRCLE,E,ground,Areas,circle,"(600,300)",40,Circle\nSLOT,F,upper,Areas,slot,"(600,300),(750,400)",20,Slot\n'
        before=len(self.store.list_objects());preview=preview_csv(self.store,self.csv(rows))
        self.assertEqual(preview['summary']['create'],6);self.assertFalse(preview['errors']);self.assertEqual(len(self.store.list_objects()),before)
        result=apply_preview(self.store,preview,'Piotr','shapes.csv');self.assertEqual(result['created'],6)
        again=preview_csv(self.store,export_csv(self.store));self.assertEqual(again['summary']['update'],0);self.assertEqual(again['summary']['unchanged'],13)
        all_rows={o['external_id']:o for o in self.store.list_objects()}
        self.assertEqual(all_rows['CIRCLE']['geometry']['type'],'circle');self.assertEqual(all_rows['SLOT']['floor_id'],'upper')
        self.assertEqual(self.store.history(all_rows['SLOT']['id'])[0]['batch_id'],result['batch_id'])
    def test_import_preserves_omitted_fields_and_detects_stale_preview_atomically(self):
        first=apply_preview(self.store,preview_csv(self.store,self.csv('EXT-1,Test,ground,Areas,point,"(200,200)",,Existing description\n')),'Piotr','a.csv')
        o=next(x for x in self.store.list_objects() if x['external_id']=='EXT-1')
        text='external_id,name,floor,layer,shape,coordinates\nEXT-1,Changed,ground,Areas,point,"(200,200)"\nEXT-2,New,upper,Areas,point,"(300,300)"\n'
        preview=preview_csv(self.store,text);self.assertEqual(preview['changes'][0]['payload']['description'],'Existing description')
        current=self.store.mutate('Other','update',o['id'],data={**o,'description':'Other editor'},version=o['version'])
        with self.assertRaises(APIError) as e:apply_preview(self.store,preview,'Piotr','stale.csv')
        self.assertEqual(e.exception.status,409);self.assertFalse(any(x['external_id']=='EXT-2' for x in self.store.list_objects()))
        fresh=preview_csv(self.store,text);apply_preview(self.store,fresh,'Piotr','fresh.csv')
        self.assertEqual(self.store.get(o['id'])['description'],'Other editor')
    def test_csv_validation_and_safe_parser(self):
        for text in ['__import__("os").system("echo x")','(1,2),bad','(1,2)(3,4)','(nan,2)','(1e999,2)']:
            with self.subTest(text=text),self.assertRaises(ValueError):parse_coordinates(text)
        self.assertEqual(parse_coordinates('( 1.5, 2 ), (3,4)'),[[1.5,2.0],[3.0,4.0]])
        preview=preview_csv(self.store,self.csv('DUP,A,ground,Areas,point,"(100,100)",,\nDUP,B,ground,Areas,point,"(200,200)",,\nBAD,C,no-floor,Areas,point,"(100,100)",,\n'))
        self.assertEqual(preview['summary']['errors'],2)
        with self.assertRaises(APIError):apply_preview(self.store,preview,'Piotr','bad.csv')
        self.assertFalse(any(x['external_id']=='DUP' for x in self.store.list_objects()))
    def picture(self):
        buf=io.BytesIO();Image.new('RGB',(2200,1200),(35,80,120)).save(buf,'PNG');return buf.getvalue()
    def test_photo_resize_dedup_history_and_incremental_backup_restore(self):
        photo=upload_photo(self.store,self.picture(),'Piotr');self.assertEqual(max(photo['width'],photo['height']),1600)
        self.assertEqual(upload_photo(self.store,self.picture(),'Other')['id'],photo['id'])
        with self.assertRaises(APIError):upload_photo(self.store,b'not an image','Piotr')
        o=self.store.mutate('Piotr','update',self.air['id'],data={**self.air,'photos':[{'id':photo['id'],'caption':'Connector close-up'}],'main_photo':photo['id']},version=self.air['version'])
        self.store.mutate('Piotr','update',o['id'],data={**o,'photos':[],'main_photo':None},version=o['version'])
        root=Path(self.temp.name)/'backups';first=make_backup(self.path,root/'one.sqlite3');second=make_backup(self.path,root/'two.sqlite3')
        self.assertEqual(first['new_images_copied'],1);self.assertEqual(second['new_images_copied'],0);self.assertEqual(second['referenced_images'],1)
        restored_path=Path(self.temp.name)/'restored/data/map.sqlite3';restore_backup(root/'one.sqlite3',restored_path)
        restored=Store(restored_path);current=restored.get(o['id']);recovered=restored.mutate('Piotr','restore',o['id'],version=current['version'],restore_version=2)
        self.assertEqual(recovered['photos'][0]['id'],photo['id']);self.assertTrue((restored.media_dir/(photo['id']+'.jpg')).is_file())
    def test_restore_rejects_missing_image_before_replacing_database(self):
        photo=upload_photo(self.store,self.picture(),'Piotr');self.store.mutate('Piotr','update',self.air['id'],data={**self.air,'photos':[{'id':photo['id'],'caption':''}]},version=1)
        root=Path(self.temp.name)/'backup';make_backup(self.path,root/'snapshot.sqlite3');(root/'images'/(photo['id']+'.jpg')).unlink()
        target=Path(self.temp.name)/'target/data/map.sqlite3';target.parent.mkdir(parents=True);target.write_bytes(b'preserve this')
        with self.assertRaises(ValueError):restore_backup(root/'snapshot.sqlite3',target)
        self.assertEqual(target.read_bytes(),b'preserve this')
    def test_v02_upgrade_changes_only_schema_not_revision_numbers(self):
        # Recreate the shipped v0.2 schema directly, with one real saved record.
        old=Path(self.temp.name)/'old/data/map.sqlite3';old.parent.mkdir(parents=True)
        payload={k:v for k,v in self.air.items() if k not in ('floor_id','external_id','photos','main_photo','id','version','deleted','updated_at','updated_by')}
        with sqlite3.connect(old) as db:
            db.executescript('CREATE TABLE objects(id TEXT PRIMARY KEY,version INTEGER,deleted INTEGER,payload TEXT,updated_at TEXT,updated_by TEXT);CREATE TABLE revisions(seq INTEGER PRIMARY KEY AUTOINCREMENT,object_id TEXT,version INTEGER,action TEXT,payload TEXT,deleted INTEGER,changed_at TEXT,changed_by TEXT,UNIQUE(object_id,version));CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);')
            db.execute('INSERT INTO metadata VALUES (?,?)',('initialized','1'));raw=json.dumps(payload)
            db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?)',('legacy',8,0,raw,'2026-10-13','Piotr'))
            db.execute('INSERT INTO revisions(object_id,version,action,payload,deleted,changed_at,changed_by) VALUES (?,?,?,?,?,?,?)',('legacy',8,'update',raw,0,'2026-10-13','Piotr'))
        upgraded=Store(old);obj=upgraded.get('legacy');self.assertEqual(obj['version'],8);self.assertEqual(obj['floor_id'],'ground');self.assertEqual(obj['external_id'],'legacy');self.assertEqual(len(upgraded.history('legacy')),1)
        self.assertEqual(len(list(old.parent.glob('map.pre-v0.3-*.sqlite3'))),1)

class HttpFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'map.db');self.server=AppServer(('127.0.0.1',0),self.store);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.cookie=None
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def req(self,method,path,data=None,mime='application/json'):
        c=http.client.HTTPConnection(*self.server.server_address,timeout=10);headers={'Content-Type':mime}
        if self.cookie:headers['Cookie']=self.cookie
        raw=data if isinstance(data,bytes) else json.dumps(data).encode() if data is not None else None
        c.request(method,path,body=raw,headers=headers);r=c.getresponse();body=r.read();heads=dict(r.getheaders());status=r.status;c.close()
        if heads.get('Set-Cookie'):self.cookie=heads['Set-Cookie'].split(';')[0]
        return status,json.loads(body) if heads.get('Content-Type','').startswith('application/json') else body,heads
    def test_http_preview_upload_and_efficient_refresh(self):
        status,data,_=self.req('GET','/api/config');self.assertEqual([f['id'] for f in data['floors']],['ground','upper'])
        status,data,_=self.req('GET','/api/objects');token=data['token'];self.assertEqual(self.req('GET','/api/objects?since='+token)[1]['unchanged'],True)
        self.assertEqual(self.req('POST','/api/import/preview',{'csv':'x'})[0],401)
        self.req('POST','/api/session',{'username':'Piotr'})
        csv='external_id,name,floor,layer,shape,coordinates\nHTTP-1,Test,upper,Areas,point,"(100,100)"\n'
        status,preview,_=self.req('POST','/api/import/preview',{'csv':csv,'filename':'a.csv'});self.assertEqual(status,200)
        self.assertEqual(self.req('POST','/api/import/apply',{'token':preview['token']})[0],200)
        self.assertEqual(self.req('POST','/api/import/apply',{'token':preview['token']})[0],409)
        self.assertNotIn('unchanged',self.req('GET','/api/objects?since='+token)[1])
        buf=io.BytesIO();Image.new('RGB',(100,100),'red').save(buf,'JPEG')
        status,p,_=self.req('POST','/api/photos',buf.getvalue(),'image/jpeg');self.assertEqual(status,201)
        status,raw,heads=self.req('GET',p['thumbnail_url']);self.assertEqual(status,200);self.assertEqual(heads['Content-Type'],'image/jpeg')
        self.assertEqual(self.req('GET','/api/export.csv')[0],200)
        self.assertEqual(self.req('GET','/api/import/template')[0],200)

if __name__=='__main__':unittest.main()
