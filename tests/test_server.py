"""Workflow tests: revision persistence, stale saves, restore, identity, HTTP contract."""
import concurrent.futures
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store, APIError, AppServer, validate_object

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'map.db')
        self.sample=self.store.list_objects()[0]
    def tearDown(self):self.temp.cleanup()
    def test_searchable_samples_and_persistence(self):
        self.assertEqual(len(self.store.list_objects()),7)
        item=self.store.mutate('Piotr','create',data={**self.sample,'external_id':'','title':'Real point','status':'unverified'})
        self.assertEqual(item['version'],1)
        self.assertEqual(Store(self.store.path).get(item['id'])['title'],'Real point')
        self.assertEqual(len(Store(self.store.path).list_objects()),8)
    def test_full_revision_delete_restore_workflow(self):
        item=self.store.mutate('Piotr','update',self.sample['id'],data={**self.sample,'title':'Updated name','geometry':{'type':'point','points':[[10,20]]}},version=1)
        deleted=self.store.mutate('Second editor','delete',item['id'],version=2)
        self.assertTrue(deleted['deleted'])
        self.assertFalse(any(x['id']==item['id'] for x in self.store.list_objects()))
        restored=self.store.mutate('Piotr','restore',item['id'],version=3,restore_version=1)
        self.assertEqual(restored['geometry'],self.sample['geometry'])
        self.assertEqual(restored['title'],self.sample['title'])
        self.assertEqual(restored['version'],4);self.assertFalse(restored['deleted'])
        self.assertEqual([r['action'] for r in self.store.history(item['id'])],['restore:1','delete','update','create'])
    def test_two_simultaneous_editors_only_one_succeeds(self):
        def save(actor):
            try:return self.store.mutate(actor,'update',self.sample['id'],data={**self.sample,'title':actor},version=1)
            except APIError as exc:return exc.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(save,['First','Second']))
        self.assertEqual(sum(isinstance(x,dict) for x in results),1)
        self.assertIn(409,results)
        self.assertEqual(len(self.store.history(self.sample['id'])),2)
    def test_validation_and_passwords(self):
        invalid=[{'geometry':{'type':'point','points':[[float('nan'),1]]}}, {'links':[{'label':'Bad','url':'javascript:alert(1)'}]}, {'links':[{'label':'Bad','url':'//evil.example/path'}]}, {'geometry':{'type':'point','points':[[-1,4]]}}, {'geometry':{'type':'rectangle','points':[[1,1],[1,10]]}}, {'geometry':{'type':'polygon','points':[[0,0],[1,1],[2,2]]}}, {'geometry':{'type':'line','points':[[1,1],[1,1]]}}]
        for patch in invalid:
            with self.subTest(patch=patch),self.assertRaises(APIError):validate_object({**self.sample,**patch})
        self.store.create_user('piotr','a valid password ')
        self.assertTrue(self.store.authenticate('piotr','a valid password '))
        self.assertFalse(self.store.authenticate('piotr','a valid password'))
        self.assertFalse(self.store.authenticate('other','a valid password '))
    def test_export_and_backup(self):
        self.store.mutate('Test','delete',self.sample['id'],version=1)
        data=self.store.export()
        self.assertEqual(len(data['objects']),7);self.assertEqual(len(data['revisions']),8)
        self.assertNotIn('users',data)
        self.assertEqual(data['revisions'][-1]['action'],'delete')
        backup=Path(self.temp.name)/'backup.db'
        with self.store.connect() as src,sqlite3.connect(backup) as dst:src.backup(dst)
        self.assertTrue(Store(backup).get(self.sample['id'])['deleted'])

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'map.db')
        self.server=AppServer(('127.0.0.1',0),self.store)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_address[1];self.cookie=None
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,method,path,body=None,extra=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        headers={'Content-Type':'application/json'}
        if self.cookie:headers['Cookie']=self.cookie
        headers.update(extra or {})
        c.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers)
        response=c.getresponse();raw=response.read();status=response.status;headers=dict(response.getheaders())
        c.close()
        if headers.get('Set-Cookie'):self.cookie=headers['Set-Cookie'].split(';')[0]
        return status,json.loads(raw) if headers.get('Content-Type','').startswith('application/json') else raw,headers
    def test_contract_login_create_conflict_logout(self):
        status,data,_=self.request('GET','/api/config');self.assertEqual(status,200);self.assertEqual(data['width'],1440)
        sample=self.store.list_objects()[0]
        self.assertEqual(self.request('POST','/api/objects',sample)[0],401)
        status,_,headers=self.request('POST','/api/session',{'username':'Piotr'});self.assertEqual(status,200);self.assertIn('HttpOnly',headers['Set-Cookie'])
        status,saved,_=self.request('POST','/api/objects',{**sample,'external_id':'','title':'HTTP test'});self.assertEqual(status,201)
        status,saved,_=self.request('PUT','/api/objects/'+saved['id'],{**saved,'title':'Edited'});self.assertEqual(status,200)
        stale={**saved,'version':1}
        status,err,_=self.request('PUT','/api/objects/'+saved['id'],stale);self.assertEqual(status,409);self.assertEqual(err['current']['version'],2)
        self.assertEqual(self.request('GET','/api/objects/'+saved['id']+'/history')[0],200)
        self.assertEqual(self.request('DELETE','/api/session')[0],200)
        self.assertEqual(self.request('DELETE','/api/objects/'+saved['id'],{'version':2})[0],401)
    def test_files_write_origin_and_bad_json(self):
        status,html,_=self.request('GET','/');self.assertEqual(status,200);self.assertIn(b'Facility map',html)
        self.assertEqual(self.request('GET','/../server.py')[0],404)
        self.assertEqual(self.request('POST','/api/session',{'username':'x'},{'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/session',{'username':'x'},{'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.request('POST','/api/session',{'username':'x'},{'Content-Type':'text/plain'})[0],415)
        status,svg,headers=self.request('GET','/assets/plan.svg',extra={'Accept-Encoding':'gzip'})
        self.assertEqual(status,200);self.assertEqual(headers['Content-Encoding'],'gzip')
        import gzip
        self.assertIn(b'viewBox="80 220 1440 720"',gzip.decompress(svg))
    def test_layer_http_create_edit_remove_and_config(self):
        definition={'name':'Cooling water','color':'#217da1','symbol':'W','aliases':['kylvatten']}
        self.assertEqual(self.request('POST','/api/layers',definition)[0],401)
        self.request('POST','/api/session',{'username':'Piotr'})
        status,data,_=self.request('POST','/api/layers',definition)
        self.assertEqual(status,201);layer=data['layer']
        status,data,_=self.request('PUT','/api/layers/'+layer['id'],{**layer,'name':'Water services'})
        self.assertEqual(status,200);self.assertEqual(data['layer']['version'],2)
        status,config,_=self.request('GET','/api/config')
        self.assertTrue(any(c['name']=='Water services' for c in config['categories']))
        status,data,_=self.request('GET','/api/layers')
        self.assertEqual(next(c for c in data['layers'] if c['id']==layer['id'])['object_count'],0)
        self.assertEqual(self.request('DELETE','/api/layers/'+layer['id'],{'version':2})[0],200)
        status,config,_=self.request('GET','/api/config')
        self.assertFalse(any(c['id']==layer['id'] for c in config['categories']))
        self.assertTrue(any(c['id']==layer['id'] for c in config['archived_categories']))

    def test_account_mode(self):
        self.store.create_user('piotr','test password 123')
        self.server.auth='accounts'
        self.assertEqual(self.request('POST','/api/session',{'username':'piotr','password':'wrong'})[0],401)
        self.assertEqual(self.request('POST','/api/session',{'username':'piotr','password':'test password 123'})[0],200)
        status,data,_=self.request('GET','/api/session');self.assertEqual(status,200);self.assertEqual(data['username'],'piotr')

if __name__=='__main__':unittest.main()
