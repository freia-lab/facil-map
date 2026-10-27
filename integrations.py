"""HTTP endpoints for binary photos, reviewed CSV imports and efficient refresh."""
import json
import secrets
import time
from urllib.parse import parse_qs,urlsplit
from server import APIError,text_field
from csv_io import preview_csv,apply_preview,export_csv,COLUMNS
from photos import MAX_UPLOAD,upload_photo
import csv,io


def text_response(handler,text,mime,filename):
    raw=text.encode('utf-8');handler.send_response(200);handler.send_header('Content-Type',mime+'; charset=utf-8');handler.send_header('Content-Length',str(len(raw)));handler.send_header('Content-Disposition','attachment; filename="'+filename+'"');handler.send_header('Cache-Control','no-store');handler.security_headers();handler.end_headers();handler.wfile.write(raw)


def feature_api(handler,method,path):
    store=handler.server.store
    if method=='GET' and path=='/api/objects':
        since=parse_qs(urlsplit(handler.path).query).get('since',[None])[0];token=store.sync_token()
        handler.respond(200,{'unchanged':True,'token':token} if since==token else {'objects':store.list_objects(),'token':token});return True
    if method=='POST' and path=='/api/photos':
        actor=handler.actor()
        try:size=int(handler.headers.get('Content-Length','0'))
        except ValueError:raise APIError(400,'Invalid photo size.')
        if not 0<size<=MAX_UPLOAD:raise APIError(413,'Choose a photo up to 12 MB.')
        if handler.headers.get('Content-Type','').split(';')[0] not in ('image/jpeg','image/png'):raise APIError(415,'Choose a JPEG or PNG photo.')
        raw=handler.rfile.read(size)
        with handler.server.photo_slots:
            result=upload_photo(store,raw,actor)
        handler.respond(201,result);return True
    if method=='GET' and path=='/api/export.csv':
        text_response(handler,export_csv(store),'text/csv','freia-objects.csv');return True
    if method=='GET' and path=='/api/import/template':
        output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=COLUMNS);writer.writeheader();writer.writerow({'external_id':'EXAMPLE-NEW','name':'Example object','floor':'ground','layer':store.list_layers()[0]['name'],'shape':'point','coordinates':'(295,445)','description':'Replace this illustrative row before importing.','status':'sample'});text='\ufeff'+output.getvalue()
        text_response(handler,text,'text/csv','freia-import-template.csv');return True
    if method=='POST' and path=='/api/import/preview':
        actor=handler.actor();body=handler.body(5_000_000);filename=text_field(body.get('filename','objects.csv'),'filename',200,True)
        preview=preview_csv(store,body.get('csv'))
        token=secrets.token_urlsafe(32)
        with handler.server.import_lock:
            saved={k:v for k,v in handler.server.import_previews.items() if v['expires']>time.time()}
            if len(saved)>30:raise APIError(429,'Too many active previews. Try again after old previews expire.')
            saved[token]={'preview':preview,'actor':actor,'filename':filename,'expires':time.time()+1200};handler.server.import_previews=saved
        handler.respond(200,{'token':token,'summary':preview['summary'],'rows':preview['rows'],'errors':preview['errors']});return True
    if method=='POST' and path=='/api/import/apply':
        actor=handler.actor();body=handler.body();token=body.get('token')
        if not isinstance(token,str):raise APIError(400,'Preview token is required.')
        with handler.server.import_lock:
            item=handler.server.import_previews.get(token)
            if not item or item['actor']!=actor or item['expires']<time.time():raise APIError(409,'Preview expired or belongs to another user. Preview the file again.')
            result=apply_preview(store,item['preview'],actor,item['filename'])
            handler.server.import_previews.pop(token,None)
        handler.respond(200,result);return True
    return False
