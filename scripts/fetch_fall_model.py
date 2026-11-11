"""Download the pinned YOLO11 fall checkpoint and verify its exact bytes."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import tempfile
import urllib.request


REVISION = '97261b03632a9715a27481b2cfdac6a78e26d2d9'
URL = f'https://huggingface.co/melihuzunoglu/human-fall-detection/resolve/{REVISION}/best.pt?download=true'
SHA256 = '3f56ad30358d5c63bf8dbc0c1299cf68818c3d291dfb10c94107b94110aadd4c'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and digest(output) == SHA256:
        print(f'Already verified: {output}')
        return
    with tempfile.NamedTemporaryFile(prefix=output.name + '.', suffix='.partial', dir=output.parent, delete=False) as handle:
        partial = Path(handle.name)
    try:
        request = urllib.request.Request(URL, headers={'User-Agent': 'InsightRover-fall-model-fetch/1'})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as stream:
            while block := response.read(1 << 20):
                stream.write(block)
        actual = digest(partial)
        if actual != SHA256:
            raise ValueError(f'SHA256 mismatch: expected {SHA256}, got {actual}')
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    print(f'Verified {output} ({output.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
