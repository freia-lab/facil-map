#!/usr/bin/env python3
"""Back up the database and copy only new referenced images to a shared pool."""
import argparse,json,sys
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from backup_support import make_backup
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--data',type=Path,default=root/'data/freia.sqlite3')
p.add_argument('--output',type=Path)
p.add_argument('--image-store',type=Path,help='Shared backup image pool; defaults to images beside the snapshot.')
a=p.parse_args();output=a.output or root/'backups'/('freia-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
try:result=make_backup(a.data,output,a.image_store)
except (ValueError,OSError) as e:p.error(str(e))
print(json.dumps(result,indent=2))
