#!/usr/bin/env python3
"""Install the photo dependency when needed, then launch the facility app."""
from pathlib import Path
import subprocess
import sys
try:
    import PIL
    ready=tuple(int(v) for v in PIL.__version__.split('.')[:2])>=(12,3)
except (ImportError,ValueError):ready=False
if not ready:
    print('Installing Pillow for photo processing (first run requires package access)...',flush=True)
    result=subprocess.run([sys.executable,'-m','pip','install','-r',str(Path(__file__).with_name('requirements.txt'))])
    if result.returncode:
        sys.exit('Installation failed. Ask IT to install requirements.txt, then run the launcher again.')
import server
server.main()
