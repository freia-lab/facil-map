#!/usr/bin/env python3
"""Restore a database snapshot and its referenced photos. Stop the server first."""
import argparse,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from backup_support import restore_backup
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('snapshot',type=Path)
p.add_argument('--data',type=Path,default=root/'data/freia.sqlite3')
a=p.parse_args()
try:result=restore_backup(a.snapshot,a.data)
except (ValueError,OSError) as e:p.error(str(e))
print(json.dumps(result,indent=2))
