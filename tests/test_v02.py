"""Regression checks for v0.1 upgrade, shared layers, curved geometry and timeouts."""
import contextlib
import concurrent.futures
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store,APIError,validate_object,AppServer,Handler

class Revision02Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'freia.sqlite3';self.store=Store(self.path)
        self.air=next(o for o in self.store.list_objects() if o['category']=='air')
    def tearDown(self):self.temp.cleanup()
    def test_v01_migration_preserves_accounts_objects_and_history(self):
        edited=self.store.mutate('Piotr','update',self.air['id'],{**self.air,'title':'Existing user record'},version=1)
        self.store.create_user('piotr','existing password')
        # Remove only the newly introduced v0.2 tables/marker: the remaining
        # schema is exactly the shipped v0.1 objects/revisions/users/metadata.
        with self.store.connect() as db:
            db.executescript("DROP TABLE layers; DROP TABLE layer_revisions; DELETE FROM metadata WHERE key='layers_initialized';")
        migrated=Store(self.path)
        self.assertEqual(migrated.get(self.air['id']),edited)
        self.assertEqual(len(migrated.history(self.air['id'])),2)
        self.assertTrue(migrated.authenticate('piotr','existing password'))
        self.assertEqual(len(migrated.list_objects()),7)
        self.assertEqual(len(migrated.list_layers()),5)
        backups=list(self.path.parent.glob('freia.pre-v0.2-*.sqlite3'));self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM objects').fetchone()[0],7)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='layers'").fetchone())
        Store(self.path)
        self.assertEqual(len(list(self.path.parent.glob('freia.pre-v0.2-*.sqlite3'))),1)
    def layer(self,name='Water'):
        return self.store.mutate_layer('Piotr','create',data={'name':name,'color':'#187ba0','symbol':'W','aliases':['water','vatten']})['layer']
    def test_layer_create_edit_reopen_and_stale_save(self):
        layer=self.layer()
        point=self.store.mutate('Piotr','create',data={**self.air,'external_id':'','category':layer['id'],'title':'Water point'})
        updated=self.store.mutate_layer('Piotr','update',layer['id'],{**layer,'name':'Cooling water','aliases':['kylvatten']},version=1)['layer']
        self.assertEqual(updated['version'],2)
        self.assertEqual(Store(self.path).get_layer(layer['id'])['aliases'],['kylvatten'])
        self.assertEqual(self.store.get(point['id'])['category'],layer['id'])
        with self.assertRaises(APIError) as err:self.store.mutate_layer('Other','update',layer['id'],layer,version=1)
        self.assertEqual(err.exception.status,409)
        self.assertEqual(len(self.store.export()['layer_revisions']),7)
    def test_remove_layer_moves_active_and_deleted_preserves_recovery(self):
        target=self.layer()
        deleted=self.store.mutate('Piotr','delete',self.air['id'],version=1)
        with self.assertRaises(APIError):self.store.mutate_layer('Piotr','delete','air',version=1)
        result=self.store.mutate_layer('Piotr','delete','air',version=1,replacement=target['id'])
        self.assertEqual(result['moved_objects'],3)
        current=self.store.get(deleted['id']);self.assertTrue(current['deleted']);self.assertEqual(current['category'],target['id'])
        self.assertFalse(any(l['id']=='air' for l in self.store.list_layers()))
        self.assertTrue(self.store.get_layer('air')['deleted'])
        restored=self.store.mutate('Piotr','restore',deleted['id'],version=current['version'],restore_version=1)
        self.assertFalse(restored['deleted']);self.assertEqual(restored['category'],target['id']);self.assertEqual(restored['geometry'],self.air['geometry'])
        with self.assertRaises(APIError):self.store.mutate('Piotr','create',data=self.air)
        successor=self.layer('Final services')
        self.store.mutate_layer('Piotr','delete',target['id'],version=1,replacement=successor['id'])
        current=self.store.get(deleted['id'])
        restored=self.store.mutate('Piotr','restore',deleted['id'],version=current['version'],restore_version=1)
        self.assertEqual(restored['category'],successor['id'])
    def test_removed_layer_cannot_lose_a_concurrent_object_edit(self):
        target=self.layer();self.store.mutate_layer('Piotr','delete','air',version=1,replacement=target['id'])
        with self.assertRaises(APIError) as err:self.store.mutate('Other','update',self.air['id'],data=self.air,version=1)
        self.assertEqual(err.exception.status,409)
    def test_last_layer_protected_and_invalid_definitions(self):
        for lid in ['air','power','equipment','route']:
            self.store.mutate_layer('Piotr','delete',lid,version=1,replacement='area')
        with self.assertRaises(APIError):self.store.mutate_layer('Piotr','delete','area',version=1)
        for patch in [{'color':'red'},{'name':''},{'symbol':'long'},{'aliases':['x'*101]}]:
            with self.subTest(patch=patch),self.assertRaises(APIError):self.store.mutate_layer('Piotr','create',data={'name':'New','color':'#123456','symbol':'N','aliases':[],**patch})
    def test_circle_slot_validation_and_revision_restore(self):
        for geometry in [{'type':'circle','points':[[200,200],[240,230]]},{'type':'slot','points':[[300,300],[450,400],[350,400]]}]:
            obj=self.store.mutate('Piotr','create',data={**self.air,'external_id':'','geometry':geometry})
            self.assertEqual(obj['geometry']['type'],geometry['type'])
            edited=self.store.mutate('Piotr','update',obj['id'],data={**obj,'title':'Updated curved object'},version=1)
            restored=self.store.mutate('Piotr','restore',obj['id'],version=2,restore_version=1)
            self.assertEqual(restored['geometry'],obj['geometry'])
        for geometry in [{'type':'circle','points':[[10,10],[60,10]]},{'type':'circle','points':[[100,100],[100,100]]},{'type':'slot','points':[[10,10],[200,10],[100,30]]},{'type':'slot','points':[[100,100],[200,100],[150,100]]},{'type':'slot','points':[[100,100],[100,100],[150,150]]}]:
            with self.subTest(geometry=geometry),self.assertRaises(APIError):validate_object({**self.air,'geometry':geometry})

class TimeoutTests(unittest.TestCase):
    def test_idle_expiry_quiet_and_partial_request_timeout_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db')
            original=Handler.idle_timeout;Handler.idle_timeout=.15
            server=AppServer(('127.0.0.1',0),store);thread=threading.Thread(target=server.serve_forever,daemon=True)
            output=io.StringIO()
            try:
                with contextlib.redirect_stderr(output):
                    thread.start()
                    sock=socket.create_connection(server.server_address,timeout=2)
                    # A browser preconnect opens a socket but sends no request.
                    self.assertEqual(sock.recv(1),b'');sock.close()
                    self.assertNotIn('timed out',output.getvalue())
                    sock=socket.create_connection(server.server_address,timeout=2)
                    sock.sendall(b'GET /api/config HTTP/1.1\r\nHost: localhost\r\n\r\n')
                    raw=b''
                    while b'\r\n\r\n' not in raw:raw+=sock.recv(8192)
                    head,body=raw.split(b'\r\n\r\n',1)
                    size=int(next(line for line in head.split(b'\r\n') if line.lower().startswith(b'content-length:')).split(b':')[1])
                    while len(body)<size:body+=sock.recv(8192)
                    self.assertEqual(sock.recv(1),b'');sock.close()
                    self.assertNotIn('timed out',output.getvalue())
                    # A received request line followed by stalled headers is a
                    # real incomplete request, and must continue to be logged.
                    sock=socket.create_connection(server.server_address,timeout=2)
                    sock.sendall(b'GET /api/config HTTP/1.1\r\nHost: localhost\r\n')
                    self.assertEqual(sock.recv(1),b'');sock.close()
                    self.assertIn('Request timed out',output.getvalue())
                    before=output.getvalue()
                    sock=socket.create_connection(server.server_address,timeout=2)
                    sock.sendall(b'POST /api/session HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{')
                    self.assertEqual(sock.recv(1),b'');sock.close()
                    self.assertIn('Active request timed out',output.getvalue()[len(before):])
            finally:
                server.shutdown();server.server_close();thread.join();Handler.idle_timeout=original

if __name__=='__main__':unittest.main()
