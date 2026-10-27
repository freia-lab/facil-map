"""Prepare the supplied CAD export without changing its geometry or viewBox."""
from pathlib import Path
import xml.etree.ElementTree as ET
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)

def prepare(source):
    source = Path(source)
    tree = ET.parse(source)
    root = tree.getroot()
    layer = root.find(f'{{{NS}}}g')
    children = list(layer)
    if any(p.tag != f'{{{NS}}}path' or set(p.attrib) - {'id', 'd', 'style'} for p in children):
        raise ValueError('Unexpected structure: manual inspection required.')
    out = ET.Element(f'{{{NS}}}svg', {
        'viewBox': root.attrib['viewBox'], 'width': root.attrib['width'],
        'height': root.attrib['height'], 'role': 'img', 'aria-label': 'FREIA facility plan'
    })
    # Each original subpath starts with a relative move from the SVG origin.
    # Reset the current point to the origin before each original path.
    # This preserves implicit relative line segments after a lowercase m.
    # Keep path order and all original commands, coordinates, and styles.
    pending, style = [], None
    def flush():
        if pending:
            ET.SubElement(out, f'{{{NS}}}path', {'style': style, 'd': ' '.join(pending)})
            pending.clear()
    for p in children:
        d = p.attrib['d'].strip()
        if not re.match(r'^[mM]\s*[-+\d.]', d):
            raise ValueError('Unexpected first path command')
        if p.get('style') != style or len(pending) == 256:
            flush()
            style = p.get('style')
        pending.append('M0,0 ' + d)
    flush()
    target = ROOT / 'static/assets/plan.svg'
    ET.ElementTree(out).write(target, encoding='utf-8', xml_declaration=True)
    original = ROOT / 'plans/original.svg'
    original.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, original)
    meta = {'source': source.name, 'viewBox': root.get('viewBox'),
            'width': float(root.get('width')), 'height': float(root.get('height')),
            'original_bytes': source.stat().st_size, 'prepared_bytes': target.stat().st_size,
            'original_paths': len(children), 'prepared_paths': len(out),
            'coordinates': 'x,y in plan units, origin at visible top-left; no physical scale assigned'}
    (ROOT / 'plans/metadata.json').write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))

if __name__ == '__main__':
    import sys
    prepare(sys.argv[1])
