"""Bounded ROS trinary PGM/YAML import. Never follows YAML image references."""
import base64
import hashlib
import json
import math
import re
import struct

import yaml

MAX_BYTES = 40 * 1024 * 1024


def pgm_pixels(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('PGM 文件超过 40 MB')
    offset = 0
    def token():
        nonlocal offset
        while offset < len(raw):
            if raw[offset:offset+1] == b'#':
                end = raw.find(b'\n',offset)
                offset = len(raw) if end < 0 else end+1
            elif raw[offset] in b' \t\r\n':
                offset += 1
            else:
                break
        start = offset
        while offset < len(raw) and raw[offset] not in b' \t\r\n#': offset += 1
        if offset == start: raise ValueError('PGM 头或像素不完整')
        return raw[start:offset]
    try:
        magic, width, height, maximum = token(), int(token()), int(token()), int(token())
        if magic not in (b'P2',b'P5') or not 1 <= width <= 16384 or not 1 <= height <= 16384 or width*height > 16_000_000 or not 1 <= maximum <= 65535:
            raise ValueError('仅支持尺寸有效的 P2/P5 PGM')
        if magic == b'P2':
            pixels = [int(token()) for _ in range(width*height)]
            # Trailing comments/whitespace are permitted, additional pixels are not.
            try: token()
            except ValueError: pass
            else: raise ValueError('PGM 像素数量过多')
        else:
            if offset >= len(raw) or raw[offset] not in b' \t\r\n': raise ValueError('PGM 缺少像素分隔符')
            offset += 2 if raw[offset:offset+2] == b'\r\n' else 1
            raster = raw[offset:]
            size = 1 if maximum < 256 else 2
            if len(raster) != width*height*size: raise ValueError('PGM 像素长度错误')
            pixels = list(raster) if size == 1 else [p[0] for p in struct.iter_unpack('>H',raster)]
        if any(p < 0 or p > maximum for p in pixels): raise ValueError('PGM 像素越界')
        return width,height,maximum,pixels
    except (OverflowError,TypeError) as exc:
        raise ValueError('PGM 格式无效') from exc


def parse_map(pair):
    if not isinstance(pair,dict): raise ValueError('需要 PGM 和 YAML 文件')
    text = pair.get('yaml','')
    if not isinstance(text,str) or len(text.encode())>65536: raise ValueError('YAML 文件无效或过大')
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError('YAML 格式无效') from exc
    if not isinstance(spec,dict) or spec.get('mode','trinary') != 'trinary': raise ValueError('首版仅支持 trinary 地图')
    name = spec.get('image')
    if not isinstance(name,str) or not re.fullmatch(r'[^/\\:]+\.pgm',name,re.I) or name.startswith('.') or name != pair.get('filename'):
        raise ValueError('YAML image 必须仅引用本次上传的 PGM 文件名')
    try:
        resolution = float(spec['resolution']); origin = spec['origin']
        if not isinstance(origin,list) or len(origin)!=3: raise ValueError('原点需要三个数值')
        origin = list(map(float,origin))
        free, occupied = float(spec.get('free_thresh',.196)),float(spec.get('occupied_thresh',.65))
        negate = spec.get('negate',0)
        if negate not in (0,1) or not 0 <= free < occupied <= 1 or resolution<=0 or not all(math.isfinite(v) for v in [resolution,free,occupied,*origin]): raise ValueError('地图比例或阈值无效')
        encoded = pair.get('pgm_base64','')
        if not isinstance(encoded,str) or len(encoded)>MAX_BYTES*4//3+4: raise ValueError('PGM 文件过大')
        raw = base64.b64decode(encoded,validate=True)
        width,height,maximum,pixels = pgm_pixels(raw)
    except (KeyError,TypeError,OverflowError) as exc:
        raise ValueError('地图参数不完整') from exc
    data = []
    for y in range(height-1,-1,-1):
        for pixel in pixels[y*width:(y+1)*width]:
            probability = pixel/maximum if negate else 1-pixel/maximum
            data.append(100 if probability>occupied else 0 if probability<free else -1)
    return {'width':width,'height':height,'resolution':resolution,'origin':dict(zip(('x','y','yaw'),origin))},data


def import_snapshot(payload):
    info,data = parse_map(payload['map'])
    result = {'info':info,'data':data,'header':{'frame_id':'map'},'session_id':'import-'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:32],'revision':1}
    if payload.get('keepout'):
        mask_info,mask = parse_map(payload['keepout'])
        if mask_info != info: raise ValueError('禁行遮罩的尺寸、分辨率和原点必须与地图相同')
        if any(v<0 for v in mask): raise ValueError('禁行遮罩仅支持明确的禁行和允许区域')
        result.update(keepout=mask,map_features=['keepout-v1'])
    return result
