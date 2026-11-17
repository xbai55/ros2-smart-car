"""One synthetic image request; opt in only after image content is verified."""
import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.services.assistant_provider import configured_fall_review_provider
from app.services.windows_credentials import read_credentials, write_credentials, PROFILE_ENV


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('LOCALAPPDATA', Path.home()))/'InsightRover')
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    profile = hashlib.sha256(os.path.normcase(str(args.data_dir.resolve())).encode()).hexdigest()
    os.environ[PROFILE_ENV] = profile
    provider = configured_fall_review_provider()
    from PIL import Image, ImageDraw
    colors = ['red', 'green', 'blue']
    shapes = ['circle', 'square', 'triangle']
    random.SystemRandom().shuffle(colors)
    random.SystemRandom().shuffle(shapes)
    image = Image.new('RGB', (720, 260), 'white')
    draw = ImageDraw.Draw(image)
    expected = []
    for index, (shape, color) in enumerate(zip(shapes, colors)):
        x = index*240+45
        if shape == 'circle': draw.ellipse((x, 50, x+150, 200), fill=color)
        elif shape == 'square': draw.rectangle((x, 50, x+150, 200), fill=color)
        else: draw.polygon([(x+75, 50), (x, 200), (x+150, 200)], fill=color)
        expected.append({'shape': shape, 'color': color})
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG')
    data = buffer.getvalue()
    result = {'passed': False, 'model': provider.model, 'images_sent': 1,
              'test': 'synthetic-image-connectivity-only', 'accuracy_evaluated': False}
    try:
        answer = await asyncio.wait_for(provider.complete([
            {'role': 'system', 'content': 'Describe only what is visible. Return JSON only.'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': 'Identify the three large colored shapes from left to right. Return a JSON object with one key "objects", an array of objects with exactly "shape" and "color". Shape must be circle, square, or triangle. Color must be red, green, or blue.'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,'+base64.b64encode(data).decode('ascii')}}
            ]}
        ], []), timeout=12.)
        content = json.loads(answer.get('content', ''))
        result['passed'] = content.get('objects') == expected
        result['response_model'] = provider.last_response.get('model', provider.model)
        result['expected'], result['observed'] = expected, content.get('objects')
        if result['passed'] and args.enable:
            values = read_credentials(profile)
            values.update(fall_review_enabled='1', fall_review_model=provider.model)
            write_credentials(profile, values)
            result['enabled'] = True
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
