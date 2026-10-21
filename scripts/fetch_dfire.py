"""Fetch an explicit public D-Fire mirror and retain its exact revision and hashes."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import tarfile
import time
import urllib.request

REPO = 'hanvithSai/gavin-dfire-raw'


def fetch(url, path, expected_size):
    if path.is_file() and path.stat().st_size == expected_size:
        return
    partial = path.with_suffix(path.suffix + '.part')
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request, timeout=60) as response:
        append = response.status == 206 and offset > 0
        if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise ValueError('服务器返回的续传范围不匹配')
        if not append:
            offset = 0
        last = time.monotonic()
        with partial.open('ab' if append else 'wb') as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                offset += len(block)
                if time.monotonic() - last > 15:
                    print(path.name, round(offset / 1e6), '/', round(expected_size / 1e6), 'MB', flush=True)
                    last = time.monotonic()
    if partial.stat().st_size != expected_size:
        raise ValueError('下载长度与公开清单不一致：' + path.name)
    partial.replace(path)


def download_with_retry(url, path, expected_size):
    for attempt in range(6):
        try:
            return fetch(url, path, expected_size)
        except Exception as exc:
            print(path.name, 'download interrupted, resuming:', str(exc), flush=True)
            if attempt == 5:
                raise
            time.sleep(min(10, 2 ** attempt))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    previous = root / 'download-manifest.json'
    if previous.exists():
        revision = json.loads(previous.read_text(encoding='utf-8'))['revision']
    else:
        with urllib.request.urlopen(f'https://huggingface.co/api/datasets/{REPO}', timeout=30) as response:
            revision = json.load(response)['sha']
    with urllib.request.urlopen(f'https://huggingface.co/api/datasets/{REPO}/tree/{revision}', timeout=30) as response:
        entries = {item['path']: item for item in json.load(response)}
    files = ['train.tar', 'test.tar']
    source = {'original_source': 'https://github.com/gaia-solutions-on-demand/DFireDataset',
              'mirror': f'https://huggingface.co/datasets/{REPO}', 'revision': revision,
              'license_note': 'Mirror CC-BY assertion conflicts with original CC0 notice; retain original image-rights caveat. Do not redistribute based on mirror metadata.',
              'status': 'downloading', 'files': {}}
    manifest = root / 'download-manifest.json'
    manifest.write_text(json.dumps(source, indent=2), encoding='utf-8')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(download_with_retry, f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/{name}?download=true', root / name, entries[name]['size']) for name in files]
        for future in futures:
            future.result()
    for name in files:
        digest = hashlib.sha256()
        with (root / name).open('rb') as file:
            while block := file.read(1024 * 1024):
                digest.update(block)
        expected = entries[name].get('lfs', {}).get('oid')
        if expected and expected != digest.hexdigest():
            raise ValueError('下载文件摘要不匹配：' + name)
        source['files'][name] = {'sha256': digest.hexdigest(), 'size': entries[name]['size']}
        with tarfile.open(root / name) as archive:
            members = archive.getmembers()
            for member in members:
                target = (root / 'raw' / member.name).resolve()
                if not target.is_relative_to(root / 'raw') or not (member.isdir() or member.isfile()):
                    raise ValueError('数据压缩包包含不安全路径')
            archive.extractall(root / 'raw', members=members, filter='data')
        print('verified and extracted', name, flush=True)
    source['status'] = 'downloaded_not_audited'
    manifest.write_text(json.dumps(source, indent=2), encoding='utf-8')
    print('Dataset downloaded; inspect labels and split leakage before training.', flush=True)


if __name__ == '__main__':
    main()
