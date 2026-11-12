"""Artifact preflight: text, routes, formats, monochrome output and local links."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageChops, ImageFont

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
layout = json.loads((ROOT/'architecture-layout.json').read_text(encoding='utf-8'))
nodes, edges = layout['nodes'], layout['edges']
errors = []
ids = [n['id'] for n in nodes] + [e['id'] for e in edges]
assert len(ids) == len(set(ids)), 'Duplicate graph ID'
for n in nodes:
    assert 0 <= n['x'] < n['x']+n['w'] <= layout['width']
    assert 0 <= n['y'] < n['y']+n['h'] <= layout['height']
    if n['group']:
        continue
    for i, value in enumerate([n['title'], *n['lines']]):
        size = n['size'] if i == 0 else min(n['size']-2, 22)
        font = ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if i == 0 else 'C:/Windows/Fonts/msyh.ttc', size)
        if font.getlength(value) > n['w']-16:
            errors.append(f'Text width: {n["id"]}: {value}')
    step = 32 if len(n['lines']) < 4 else 34
    if len(n['lines'])*step+n['size'] > n['h']-12:
        errors.append(f'Text height: {n["id"]}')
for e in edges:
    assert e['source'] in ids and e['target'] in ids
    for a,b in zip(e['points'],e['points'][1:]):
        assert a[0] == b[0] or a[1] == b[1], f'Nonorthogonal edge: {e["id"]}'
        for n in nodes:
            if n['group'] or n['id'] in (e['source'],e['target']):
                continue
            l,t,r,bt = n['x']+1,n['y']+1,n['x']+n['w']-1,n['y']+n['h']-1
            vertical = a[0]==b[0] and l<a[0]<r and max(min(a[1],b[1]),t)<min(max(a[1],b[1]),bt)
            horizontal = a[1]==b[1] and t<a[1]<bt and max(min(a[0],b[0]),l)<min(max(a[0],b[0]),r)
            if vertical or horizontal:
                errors.append(f'Edge crosses unrelated node: {e["id"]} / {n["id"]}')
for name in ['insightrover-system-architecture.svg','insightrover-system-architecture.drawio']:
    ET.parse(ROOT/name)
svg = (ROOT/'insightrover-system-architecture.svg').read_text(encoding='utf-8')
assert set(re.findall(r'#[0-9A-Fa-f]{3,6}',svg)) <= {'#000','#fff'}
assert '<text ' in svg and '<image ' not in svg, 'SVG must retain editable vector text'
with Image.open(ROOT/'insightrover-system-architecture.png') as image:
    assert image.size == (7680,4320)
    red,green,blue = image.convert('RGB').split()
    assert ImageChops.difference(red,green).getbbox() is None
    assert ImageChops.difference(red,blue).getbbox() is None
for doc in [REPO/'README.md',ROOT/'README.md']:
    content = doc.read_text(encoding='utf-8-sig')
    assert content.count('```') % 2 == 0
    for target in re.findall(r'\]\(([^)]+)\)',content):
        if not target.startswith(('http:','https:','#')):
            assert (doc.parent/target.split('#')[0]).exists(), f'Missing local link: {target}'
assert not any(term in svg for term in ['待补充','待验证','暂未实现','计划实现'])
assert not errors, '\n'.join(errors)
print(json.dumps({'nodes':len(nodes),'connections':len(edges),'text_fit':True,
    'edge_routes':True,'xml':True,'editable_svg':True,'monochrome':True,
    'png':[7680,4320],'local_links':True},ensure_ascii=False))
