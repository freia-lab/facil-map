"""Actual HTTP authorization, calibration, registration, rollback and backup checks."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store,AppServer,APIError
from map_setup import current,clean_svg
from backup_support import make_backup,restore_backup

SVG='<svg xmlns="http://www.w3.org/2000/svg" viewBox="80 220 1440 720"><path d="M80 220 L1500 900" style="stroke:black;fill:none"/></svg>'
class MapSetupTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'data/map.sqlite3';self.store=Store(self.path)
  self.store.create_user('admin','password12345');self.store.create_user('editor','password12345')
  with self.store.connect() as db:db.execute('INSERT INTO admin_users VALUES (?)',('admin',))
  self.server=AppServer(('127.0.0.1',0),self.store,'accounts');self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
 def request(self,method,path,body=None,cookie=None):
  conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);headers={}
  if body is not None:headers['Content-Type']='application/json'
  if cookie:headers['Cookie']=cookie
  conn.request(method,'/api/'+path,json.dumps(body) if body is not None else None,headers);response=conn.getresponse();raw=response.read();status=response.status;cookie=response.getheader('Set-Cookie');content=response.getheader('Content-Type');conn.close()
  return status,json.loads(raw) if 'json' in content else raw,cookie
 def login(self,name):
  status,data,cookie=self.request('POST','session',{'username':name,'password':'password12345'});self.assertEqual(status,200);self.assertEqual(data['is_admin'],name=='admin');return cookie
 def test_permissions_live_role_and_existing_accounts(self):
  editor=self.login('editor');admin=self.login('admin')
  self.assertEqual(self.request('POST','map-settings',{'version':1},editor)[0],403)
  self.assertEqual(self.request('POST','plan-upload',{'svg':SVG},editor)[0],403)
  self.assertEqual(self.request('GET','map-history',cookie=editor)[0],403)
  self.assertEqual(self.request('GET','map-settings')[0],200)
  with self.store.connect() as db:db.execute("DELETE FROM admin_users WHERE username='admin'")
  self.assertEqual(self.request('POST','map-settings',{'version':1},admin)[0],403)
  self.store.create_user('editor','newpassword123')
  self.assertTrue(self.store.authenticate('editor','newpassword123'))
 def test_scale_upload_registration_conflict_and_rollback(self):
  admin=self.login('admin');objects=self.store.list_objects()
  status,asset,_=self.request('POST','plan-upload',{'svg':SVG},admin);self.assertEqual(status,201)
  body={'version':1,'calibration':{'a':[10,10],'b':[260,10],'metres':10},'grid_origin':[0,0],'landmarks':[{'name':'Column 1','point':[100,100]},{'name':'Column 2','point':[500,100]}], 'replacement':{**asset,'floor_id':'upper','transform':[.8,.1,-.1,.8,30,40]}}
  status,data,_=self.request('POST','map-settings',body,admin);self.assertEqual(status,200);self.assertEqual(data['metres_per_pixel'],.04)
  self.assertEqual(self.store.list_objects(),objects,'alignment never changes object coordinates or revisions')
  status,config,_=self.request('GET','config');self.assertEqual(config['floors'][1]['plan_url'],asset['plan_url'])
  self.assertEqual(self.request('GET',asset['plan_url'][5:])[0],200)
  self.assertEqual(self.request('POST','map-settings',body,admin)[0],409)
  status,data,_=self.request('POST','map-restore',{'version':2,'restore_version':1},admin);self.assertEqual(status,200);self.assertEqual(data['version'],3);self.assertIsNone(data['metres_per_pixel']);self.assertEqual(data['floors'][1]['plan_url'],'/assets/plan.svg')
  self.assertEqual(len(self.request('GET','map-history',cookie=admin)[1]['revisions']),3)
  backup=Path(self.temp.name)/'backup/snapshot.sqlite3';make_backup(self.path,backup)
  restored=Path(self.temp.name)/'restored/map.sqlite3';restore_backup(backup,restored);store=Store(restored)
  with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM map_assets').fetchone()[0],1)
  self.assertEqual(current(store,2)['metres_per_pixel'],.04)
 def test_invalid_calibration_and_unsafe_svg(self):
  admin=self.login('admin')
  for calibration in ({'a':[1,1],'b':[1,1],'metres':10},{'a':[0,0],'b':[20,0],'metres':0},{'a':[0,0],'b':[20,0],'metres':float('inf')}):
   self.assertEqual(self.request('POST','map-settings',{'version':1,'calibration':calibration},admin)[0],400)
  for svg in (SVG.replace('<path','<script'),SVG.replace('stroke:black','stroke:url(https://bad)'),SVG.replace('<path','<foreignObject'), '<!DOCTYPE svg>'+SVG):
   self.assertEqual(self.request('POST','plan-upload',{'svg':svg},admin)[0],400)
  self.assertEqual(current(self.store)['version'],1)
 def test_restart_preserves_setup_and_migration_backup(self):
  self.assertTrue(self.path.with_name('map.pre-v0.4.sqlite3').exists())
  self.assertEqual(current(Store(self.path))['version'],1)

if __name__=='__main__':unittest.main()
