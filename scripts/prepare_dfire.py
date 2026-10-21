"""Audit D-Fire; keep AoF video frames out of training and group near duplicates.

This produces a public-data baseline, not a vehicle-scene acceptance certificate.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

from PIL import Image


class HashTree:
    def __init__(self):
        self.root = None

    def match_and_add(self, value, index, radius=4):
        matches, stack = [], [self.root] if self.root else []
        while stack:
            node = stack.pop()
            distance = (value ^ node[0]).bit_count()
            if distance <= radius:
                matches.append(node[1])
            stack.extend(child for edge, child in node[2].items() if distance - radius <= edge <= distance + radius)
        if self.root is None:
            self.root = [value, index, {}]
        else:
            node = self.root
            while True:
                distance = (value ^ node[0]).bit_count()
                if distance == 0:
                    break
                if distance not in node[2]:
                    node[2][distance] = [value, index, {}]
                    break
                node = node[2][distance]
        return matches


def label_lines(path):
    result, clipped = [], 0
    for line in path.read_text(encoding='utf-8').splitlines():
        values = line.split()
        if len(values) != 5:
            raise ValueError('label requires class and four coordinates')
        cls = int(values[0])
        x, y, w, h = map(float, values[1:])
        if cls not in (0, 1) or not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
            raise ValueError('invalid label class or size')
        bounds = (x-w/2, y-h/2, x+w/2, y+h/2)
        left, top, right, bottom = (max(0., min(1., v)) for v in bounds)
        if right <= left or bottom <= top:
            raise ValueError('label box outside image')
        clipped += any(a != b for a, b in zip(bounds, (left, top, right, bottom)))
        result.append(f'{cls} {(left+right)/2:.8f} {(top+bottom)/2:.8f} {right-left:.8f} {bottom-top:.8f}')
    return result, clipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'data.yaml').exists():
        raise RuntimeError('Prepared dataset already exists; use its manifest or a new output directory')
    parents, rows, tree, errors = [], [], HashTree(), []
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for image in sorted(args.raw.resolve().rglob('*.jpg')):
        if image.name.startswith('.'):
            continue
        try:
            labels, clipped = label_lines(image.parent.parent / 'labels' / (image.stem + '.txt'))
            with Image.open(image) as frame:
                frame.load()
                gray = frame.convert('L').resize((9, 8))
                pixels = list(gray.getdata())
                dhash = sum(int(pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
            sha = hashlib.sha256(image.read_bytes()).hexdigest()
            index = len(rows)
            parents.append(index)
            for match in tree.match_and_add(dhash, index):
                parents[find(index)] = find(match)
            rows.append({'image': str(image), 'sha256': sha, 'labels': labels, 'clipped_boxes': clipped,
                         'external': image.parent.parent.name == 'test' or not image.stem.startswith('WEB')})
            if index % 1000 == 0:
                print('audited', index, flush=True)
        except Exception as exc:
            errors.append({'image': str(image), 'reason': str(exc)})
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[find(index)].append(row)
    manifest, counts, duplicate_count = [], Counter(), 0
    for group in groups.values():
        ident = min(row['sha256'] for row in group)
        split = 'test' if any(row['external'] for row in group) else 'val' if int(ident[:8], 16) % 100 < 15 else 'train'
        seen = set()
        for row in group:
            if row['sha256'] in seen:
                duplicate_count += 1
                continue
            seen.add(row['sha256'])
            source = Path(row['image'])
            target = root / 'images' / split / (row['sha256'] + '.jpg')
            target.parent.mkdir(parents=True, exist_ok=True)
            label = root / 'labels' / split / (row['sha256'] + '.txt')
            label.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
            label.write_text('\n'.join(row['labels']), encoding='utf-8')
            counts[split] += 1
            manifest.append({**row, 'group': ident, 'split': split})
    if any(counts[s] < 100 for s in ('train', 'val', 'test')):
        raise ValueError('Insufficient independent sample groups')
    (root / 'data.yaml').write_text('path: '+json.dumps(str(root).replace('\\','/'))+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: smoke\n  1: fire\n', encoding='utf-8')
    (root / 'samples.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in manifest), encoding='utf-8')
    report = {'counts': counts, 'excluded': errors, 'duplicate_images_removed': duplicate_count,
              'clipped_boxes': sum(row['clipped_boxes'] for row in rows),
              'class_map': {'0': 'smoke', '1': 'fire'},
              'split_policy': 'All AoF and PublicDataset images plus original test are external test; WEB train near-duplicate dHash groups split 85/15 train/val. Hamming<=4; whole groups cannot cross splits.',
              'limitation': 'Source scene IDs unavailable for WEB; perceptual grouping cannot prove scene independence. Vehicle scenes still require separate acceptance.'}
    (root / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
