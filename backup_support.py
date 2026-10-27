"""Consistent database snapshots with a shared immutable image pool."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def referenced_photos(db):
    ids=set()
    for table in ('objects','revisions'):
        for (raw,) in db.execute('SELECT payload FROM '+table):
            for p in json.loads(raw).get('photos',[]):ids.add(p['id'])
    return sorted(ids)


def make_backup(source_path,output,image_store=None):
    source_path,output=Path(source_path).resolve(),Path(output).resolve()
    if not source_path.is_file():raise ValueError('Database does not exist.')
    if output.exists():raise ValueError('Backup output already exists.')
    pool=Path(image_store).resolve() if image_store else output.parent/'images'
    output.parent.mkdir(parents=True,exist_ok=True);pool.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(output) as target:
        source.backup(target)
        ids=referenced_photos(target)
    copied=0;files=[]
    try:
        for pid in ids:
            filename=pid+'.jpg';source=source_path.parent/'images'/filename;dest=pool/filename
            if not source.is_file():raise ValueError('Referenced photo is missing: '+pid)
            if dest.exists():
                if hashlib.sha256(dest.read_bytes()).hexdigest()!=pid:raise ValueError('Backup image is corrupt: '+pid)
            else:
                if hashlib.sha256(source.read_bytes()).hexdigest()!=pid:raise ValueError('Source photo is corrupt: '+pid)
                with tempfile.NamedTemporaryFile(dir=pool,delete=False) as temp:
                    with source.open('rb') as inp:shutil.copyfileobj(inp,temp)
                    temporary=Path(temp.name)
                temporary.replace(dest);copied+=1
            files.append(filename)
        manifest={'schema_version':1,'database':output.name,'database_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                  'image_store':os.path.relpath(pool,output.parent),'images':files,
                  'retention':'Keep every listed image while retaining this snapshot. Thumbnails are regenerated.'}
        output.with_suffix(output.suffix+'.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    except Exception:
        output.unlink(missing_ok=True);raise
    return {'database':str(output),'manifest':str(output.with_suffix(output.suffix+'.manifest.json')),'referenced_images':len(files),'new_images_copied':copied}


def restore_backup(snapshot,target_path):
    snapshot,target=Path(snapshot).resolve(),Path(target_path).resolve()
    if not snapshot.is_file():raise ValueError('Snapshot does not exist.')
    with sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Snapshot failed SQLite integrity check.')
        ids=referenced_photos(db)
    manifest_path=snapshot.with_suffix(snapshot.suffix+'.manifest.json')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else None
    if ids and not manifest:raise ValueError('This snapshot needs its image manifest and image pool.')
    if manifest and hashlib.sha256(snapshot.read_bytes()).hexdigest()!=manifest['database_sha256']:raise ValueError('Snapshot does not match its manifest.')
    sources=[]
    for pid in ids:
        filename=pid+'.jpg'
        if filename not in manifest['images']:raise ValueError('Manifest is missing a photo reference.')
        path=(snapshot.parent/manifest['image_store']/filename).resolve()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=pid:raise ValueError('Backup photo missing or corrupt: '+pid)
        sources.append((path,filename))
    target.parent.mkdir(parents=True,exist_ok=True);media=target.parent/'images';media.mkdir(exist_ok=True)
    for source,filename in sources:
        dest=media/filename
        if not dest.exists():shutil.copy2(source,dest)
        elif hashlib.sha256(dest.read_bytes()).hexdigest()!=filename[:-4]:shutil.copy2(source,dest)
    # Caller stops the app first. Preserve the existing database before replacement.
    previous=None
    if target.exists():
        from datetime import datetime
        previous=target.with_name(target.stem+'.before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
        make_backup(target,previous)
    with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as temp:
        with snapshot.open('rb') as source:shutil.copyfileobj(source,temp)
        temporary=Path(temp.name)
    temporary.replace(target)
    return {'database':str(target),'images_restored':len(sources),'previous_database_backup':str(previous) if previous else None}
