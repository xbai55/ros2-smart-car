"""Collect runtime license texts for redistribution; never reads application data."""
from importlib import metadata
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
names=['fastapi','uvicorn','sqlalchemy','pydantic','pydantic_core','starlette','anyio','httpx','httpcore',
       'h11','idna','certifi','sniffio','annotated-types','typing_extensions','typing-inspection',
       'Pillow','PyYAML','websockets','click','colorama','attrs','email-validator','importlib-metadata',
       'cryptography','cffi','pycparser','werkzeug','wheel','zipp','packaging','greenlet',
       'requests','urllib3','charset-normalizer','chardet','psutil','pyzmq','rich','pygments','PyNaCl','bcrypt','paramiko','invoke']
chunks=['InsightRover Windows 0.3.3 — third-party notices\n',
        'Python 3.12 runtime: Python Software Foundation License, https://docs.python.org/3/license.html\n',
        'Tcl/Tk: license.terms files are included in the bundled Tcl/Tk data folders.\n',
        'Runtime binaries retain their respective licenses; the application includes no project user database.\n']
for name in names:
    try:dist=metadata.distribution(name)
    except metadata.PackageNotFoundError:continue
    chunks.append('\n'+'='*72+'\n'+dist.metadata['Name']+' '+dist.version+'\n')
    for entry in dist.files or []:
        if entry.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
            path=Path(dist.locate_file(entry))
            if path.is_file() and path.stat().st_size<1000000:
                chunks.append('\n'+entry.name+'\n'+path.read_text(encoding='utf-8',errors='replace')+'\n')
for name in ['react','react-dom','scheduler','lucide-react']:
    path=ROOT/'web-console/node_modules'/name/'LICENSE'
    if path.exists():chunks.append('\n'+'='*72+'\n'+name+'\n'+path.read_text(encoding='utf-8')+'\n')
(ROOT/'desktop/THIRD_PARTY_NOTICES.txt').write_text(''.join(chunks),encoding='utf-8')
print('Third-party notices collected')
