"""Immutable JPEG assets; thumbnails are derived and may be regenerated."""
import hashlib
import io
from pathlib import Path
import re
import tempfile
import warnings
from server import APIError, now

MAX_UPLOAD = 12 * 1024 * 1024

def pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise APIError(503,'Photo support needs Pillow. Run: python -m pip install -r requirements.txt')
    return Image,ImageOps


def upload_photo(store, raw, actor):
    if not raw or len(raw)>MAX_UPLOAD:
        raise APIError(413,'Choose a JPEG or PNG photo up to 12 MB.')
    Image,ImageOps = pillow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG','PNG') or source.width*source.height>40_000_000:
                    raise ValueError('format or dimensions')
                image=ImageOps.exif_transpose(source)
                image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
                if image.mode in ('RGBA','LA') or 'transparency' in image.info:
                    rgba=image.convert('RGBA');background=Image.new('RGB',rgba.size,'white');background.paste(rgba,mask=rgba.getchannel('A'));image=background
                else:image=image.convert('RGB')
                output=io.BytesIO();image.save(output,'JPEG',quality=85,optimize=True)
                cooked=output.getvalue();width,height=image.size
    except Exception as exc:
        raise APIError(400,'Choose a valid JPEG or PNG photo (maximum 40 megapixels).') from exc
    pid=hashlib.sha256(cooked).hexdigest();target=store.media_dir/(pid+'.jpg')
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=store.media_dir,delete=False) as f:
            f.write(cooked);tmp=Path(f.name)
        tmp.replace(target)
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO photos VALUES (?,?,?,?,?,?)',(pid,width,height,len(cooked),now(),actor))
    return {'id':pid,'width':width,'height':height,'bytes':len(cooked),'url':'/media/'+pid+'.jpg','thumbnail_url':'/media/'+pid+'.thumb.jpg'}


def serve_photo(handler,path):
    match=re.fullmatch(r'/media/([0-9a-f]{64})(\.thumb)?\.jpg',path)
    if not match:raise APIError(404,'Photo not found.')
    pid,thumb=match.groups();store=handler.server.store
    with store.connect() as db:
        if not db.execute('SELECT 1 FROM photos WHERE id=?',(pid,)).fetchone():raise APIError(404,'Photo not found.')
    original=store.media_dir/(pid+'.jpg');target=store.media_dir/(pid+('.thumb' if thumb else '')+'.jpg')
    if not original.is_file():raise APIError(404,'Photo file is missing. Restore the corresponding image backup.')
    if thumb and not target.exists():
        Image,_=pillow()
        with Image.open(original) as im:
            im.thumbnail((320,320),Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(dir=store.media_dir,delete=False) as f:tmp=Path(f.name)
            im.save(tmp,'JPEG',quality=80,optimize=True);tmp.replace(target)
    raw=target.read_bytes();handler.send_response(200);handler.send_header('Content-Type','image/jpeg');handler.send_header('Content-Length',str(len(raw)));handler.send_header('Cache-Control','private, max-age=31536000, immutable');handler.security_headers();handler.end_headers();handler.wfile.write(raw)
