import json
import base64
import hashlib
import io
import zipfile
import logging
import math
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5
import httpx

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from PIL import Image, ImageOps, ImageFilter, UnidentifiedImageError
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ...core.pagination import run_list
from ...models import AppSetting, MapModel, MapPlace, MissionTask, PatrolTask, Robot, Route, User
from ...schemas.ops import MapIn, MapPlaceIn, MapUpdate, SlamMapIn, MapOptimizationIn
from ...gateway import get_robot_gateway
from ...services.slam_maps import snapshot_assets
from ...services.map_optimization import optimize_snapshot, isolated_candidates
from ...services.ros_map_io import import_snapshot
from ...services.ops import json_loads, record_audit
from ...services.storage import get_storage
from ..deps import get_db, require_permission

router = APIRouter(prefix="/maps", tags=["maps"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
SELECTION_KEY = "navigation_map_id"


def _error(status: int, message: str, code: str = "BAD_REQUEST"):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _map(db: Session, map_id: str) -> MapModel:
    item = db.get(MapModel, map_id)
    if item is None:
        raise _error(404, "地图不存在", "NOT_FOUND")
    return item


def _delete_image(key: str | None):
    if key and key.startswith("maps/"):
        try:
            get_storage().delete(key)
        except Exception:
            logging.getLogger(__name__).exception("Unable to remove map image %s", key)


def serialize_map(item: MapModel) -> dict:
    def timestamp(value):
        if value is None:
            return None
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()

    return {
        "id": item.id,
        "name": item.name,
        "floor": item.floor,
        "description": item.description,
        "resolution": item.resolution,
        "width": item.width,
        "height": item.height,
        "origin": json_loads(item.origin, []),
        "image_key": item.image_key,
        "file_url": item.file_url,
        "metadata": json_loads(item.meta, {}),
        "active": item.active,
        "created_at": timestamp(item.created_at),
        "updated_at": timestamp(item.updated_at),
        "image_url": f"/api/v1/maps/{item.id}/image" if item.image_key else None,
    }


def _apply_payload(item: MapModel, payload: MapIn) -> None:
    data = payload.model_dump()
    item.name = data["name"]
    item.floor = data["floor"]
    item.description = data["description"]
    item.resolution = data["resolution"]
    item.width = data["width"]
    item.height = data["height"]
    item.origin = json.dumps(data["origin"] or [], ensure_ascii=False)
    item.image_key = data["image_key"]
    item.file_url = data["file_url"]
    item.meta = json.dumps(data["metadata"] or {}, ensure_ascii=False)
    item.active = data["active"]


@router.get("")
def list_maps(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("maps.read")),
    keyword: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(MapModel).order_by(MapModel.name)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(MapModel.name.like(like), MapModel.floor.like(like)))
    if active is not None:
        stmt = stmt.where(MapModel.active.is_(active))
    return run_list(db, stmt, serialize_map, page, page_size)


@router.post("", status_code=201)
def create_map(
    payload: MapIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("maps.manage")),
) -> dict:
    item = MapModel(id=str(uuid4()))
    _apply_payload(item, payload)
    db.add(item)
    db.flush()
    record_audit(db, user, "maps.create", "map", item.id, after=serialize_map(item))
    db.commit()
    return serialize_map(item)


@router.post("/slam", status_code=201)
async def save_slam_map(payload: SlamMapIn, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    if db.get(Robot, payload.robot_id) is None:
        raise _error(404, "机器人不存在", "NOT_FOUND")
    map_id = str(uuid5(NAMESPACE_URL, f"slam:{payload.robot_id}:{payload.request_id}"))
    existing = db.get(MapModel, map_id)
    if existing is not None:
        return serialize_map(existing)
    setting = db.scalar(select(AppSetting).where(AppSetting.key == "robot_web_url"))
    gateway = get_robot_gateway(setting.value if setting else None)
    try:
        exported = await gateway.save_slam_map()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise _error(409, "小车尚无可保存的 SLAM 地图", "MAP_NOT_READY") from exc
        raise _error(502, "小车保存地图失败，请检查车端连接与地图状态", "VEHICLE_UNAVAILABLE") from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise _error(502, str(exc) or "无法连接小车保存地图", "VEHICLE_UNAVAILABLE") from exc
    try:
        packed = snapshot_assets(exported["snapshot"])
    except (KeyError, ValueError, TypeError) as exc:
        raise _error(502, f"车端地图无法登记：{exc}", "INVALID_SLAM_MAP") from exc
    prefix = f"maps/{map_id}/{packed['digest']}"
    assets = {name: f"{prefix}/{name}" for name in packed["assets"]}
    item = MapModel(id=map_id, name=payload.name, floor=payload.floor, description=payload.description,
                    width=packed["width"], height=packed["height"], resolution=packed["resolution"],
                    origin=json.dumps(packed["origin"]), active=True, image_key=assets["preview.png"],
                    file_url=f"/api/v1/maps/{map_id}/image")
    item.meta = json.dumps({"source": "slam", "coordinate_space": "map_meters", "navigation_ready": False,
                           "robot_id": payload.robot_id, "session_id": packed["session_id"],
                           "frame_id": packed["frame_id"], "revision": exported["snapshot"].get("revision"),
                           "digest": packed["digest"], "assets": assets,
                           "vehicle_yaml_path": exported.get("yaml_path"), "vehicle_pgm_path": exported.get("pgm_path"),
                           "request_id": str(payload.request_id)}, ensure_ascii=False)
    written = []
    try:
        for name, (content, mime) in packed["assets"].items():
            written.append(assets[name])
            get_storage().put(assets[name], content, content_type=mime)
        db.add(item)
        db.flush()
        record_audit(db, user, "maps.slam.save", "map", map_id, after=serialize_map(item))
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.get(MapModel, map_id)
        if winner is None or json_loads(winner.meta, {}).get("digest") != packed["digest"]:
            for key in written: _delete_image(key)
        if winner is not None:
            return serialize_map(winner)
        raise _error(500, "车端文件已保存，地图登记失败，请重试", "MAP_IMPORT_FAILED")
    except Exception as exc:
        db.rollback()
        for key in written: _delete_image(key)
        logging.getLogger(__name__).exception("SLAM import failed")
        raise _error(500, "车端文件已保存，地图登记失败，请重试", "MAP_IMPORT_FAILED") from exc
    return serialize_map(item)


@router.get("/selection")
def map_selection(db: Session = Depends(get_db), _: User = Depends(require_permission("maps.read"))):
    selected = db.scalar(select(AppSetting).where(AppSetting.key == SELECTION_KEY))
    item = db.get(MapModel, selected.value) if selected and selected.value else None
    return {"map_id": item.id if item and item.active else None, "initialized": selected is not None}


def _grid(item):
    metadata = json_loads(item.meta,{})
    key = metadata.get('assets',{}).get('snapshot.json','')
    if metadata.get('source') != 'slam' or not key.startswith(f'maps/{item.id}/'):
        raise _error(409,'请选择带栅格数据的 SLAM 地图')
    raw = get_storage().get(key)
    if raw is None: raise _error(404,'地图文件缺失')
    return json.loads(raw)


@router.post('/import-ros',status_code=201)
async def import_ros(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission('maps.manage'))):
    # Stream with a hard cap instead of allocating an unbounded JSON request.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>112*1024*1024: raise _error(413,'导入文件过大')
    try:
        payload = json.loads(body)
        if not isinstance(payload,dict): raise ValueError('导入请求格式无效')
        name = payload.get('name','').strip()
        if not name or len(name)>128: raise ValueError('地图名称无效')
        def prepare():
            return snapshot_assets(import_snapshot(payload))
        packed = await run_in_threadpool(prepare)
    except (ValueError,TypeError,KeyError) as exc:
        raise _error(422,str(exc)) from exc
    item = MapModel(id=str(uuid4()), name=name, floor=str(payload.get('floor','1F'))[:64], description='导入的 ROS 栅格地图',
                    width=packed['width'],height=packed['height'],resolution=packed['resolution'],origin=json.dumps(packed['origin']),active=True)
    prefix=f"maps/{item.id}/{packed['digest']}"
    assets={n:f'{prefix}/{n}' for n in packed['assets']}
    item.image_key=assets['preview.png']; item.file_url=f'/api/v1/maps/{item.id}/image'
    item.meta=json.dumps({'source':'slam','coordinate_space':'map_meters','navigation_ready':False,'digest':packed['digest'],
                          'frame_id':packed['frame_id'],'session_id':packed['session_id'],'assets':assets,'imported':True,
                          'terrain_digest':packed['terrain_digest'],'keepout_digest':packed['keepout_digest']})
    written=[]
    try:
        for n,(content,mime) in packed['assets'].items():
            written.append(assets[n]); get_storage().put(assets[n],content,content_type=mime)
        db.add(item); db.flush(); record_audit(db,user,'maps.import_ros','map',item.id,after=serialize_map(item)); db.commit()
    except Exception as exc:
        db.rollback()
        for key in written: _delete_image(key)
        raise _error(500,'导入失败，已有地图未修改') from exc
    return serialize_map(item)


@router.post('/{map_id}/cleanup-candidates')
def cleanup_candidates(map_id: str, payload: dict = Body(default={}), max_cells: int = Query(default=2,ge=1,le=8), db: Session = Depends(get_db),
                       _: User = Depends(require_permission('maps.manage'))):
    snapshot = _grid(_map(db,map_id))
    operations=payload.get('operations',[])
    if operations:
        try: snapshot,_=optimize_snapshot(snapshot,operations)
        except (ValueError,TypeError,KeyError) as exc: raise _error(422,str(exc)) from exc
    values = isolated_candidates(snapshot,max_cells)
    if len(values)>20000: raise _error(422,'候选超过两万个，请先分区手工清理')
    return {'candidates':values,'max_cells':max_cells,'resolution':snapshot['info']['resolution']}


@router.get('/{map_id}/export-ros')
def export_ros(map_id: str, db: Session = Depends(get_db), _: User = Depends(require_permission('maps.read'))):
    item=_map(db,map_id); snapshot=_grid(item); packed=snapshot_assets(snapshot)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,(content,_) in packed['assets'].items(): archive.writestr(name,content)
        archive.writestr('version.json',json.dumps({'name':item.name,'metadata':json_loads(item.meta,{})},ensure_ascii=False,indent=2))
    return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="ros-map.zip"'})


def _optimized(db, map_id, payload):
    parent = _map(db, map_id)
    metadata = json_loads(parent.meta, {})
    key = metadata.get("assets", {}).get("snapshot.json", "")
    if metadata.get("source") != "slam" or not key.startswith(f"maps/{map_id}/"):
        raise _error(409, "仅支持有原始栅格数据的 SLAM 地图", "GRID_REQUIRED")
    raw = get_storage().get(key)
    if raw is None:
        raise _error(404, "原始地图文件缺失", "NOT_FOUND")
    try:
        edited, changed = optimize_snapshot(json.loads(raw), payload.operations) if payload.operations else (json.loads(raw),0)
        packed = snapshot_assets(edited)
    except (ValueError, TypeError, KeyError) as exc:
        raise _error(422, str(exc)) from exc
    return parent, metadata, packed, changed


@router.post("/{map_id}/optimization-preview")
def preview_optimization(map_id: str, payload: MapOptimizationIn, db: Session = Depends(get_db),
                         _: User = Depends(require_permission("maps.manage")), radius_m: float = Query(default=.25,ge=.01,le=2)):
    _, _, packed, changed = _optimized(db, map_id, payload)
    original = _grid(_map(db,map_id))
    edited = json.loads(packed['assets']['snapshot.json'][0])
    width,height = packed['width'],packed['height']
    old_mask,new_mask = original.get('keepout',[0]*len(original['data'])),edited.get('keepout',[0]*len(original['data']))
    pixels=bytearray(width*height*4)
    for i,(a,b,m,n) in enumerate(zip(original['data'],edited['data'],old_mask,new_mask)):
        if a != b or m != n:
            p=((height-1-i//width)*width+i%width)*4; pixels[p:p+4]=b'\x00\xb4\xd8\x96'
    diff=io.BytesIO(); Image.frombytes('RGBA',(width,height),bytes(pixels)).save(diff,format='PNG')
    effective=None
    if any(new_mask):
        mask=Image.frombytes('L',(width,height),bytes(255 if v else 0 for y in range(height-1,-1,-1) for v in new_mask[y*width:(y+1)*width]))
        # Conservative footprint envelope, identical to the vehicle's square dilation.
        span=math.ceil(radius_m/packed['resolution'])
        if span>100: raise _error(422,'该分辨率下禁行边界过大')
        alpha=mask.filter(ImageFilter.MaxFilter(span*2+1)).point(lambda v: 75 if v else 0)
        layer=Image.new('RGBA',(width,height),(231,62,67)); layer.putalpha(alpha)
        out=io.BytesIO(); layer.save(out,format='PNG'); effective='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
    return {"changed_cells": changed, "digest": packed["digest"],
            'changed_area_m2':changed*packed['resolution']**2, 'radius_m':radius_m,
            'diff_url':'data:image/png;base64,'+base64.b64encode(diff.getvalue()).decode(),
            'keepout_url':'data:image/png;base64,'+base64.b64encode(packed['assets']['keepout.png'][0]).decode() if 'keepout.png' in packed['assets'] else None,
            'effective_keepout_url':effective,
            "preview_url": "data:image/png;base64," + base64.b64encode(packed["assets"]["preview.png"][0]).decode()}


@router.post("/{map_id}/derive", status_code=201)
def derive_map(map_id: str, payload: MapOptimizationIn, db: Session = Depends(get_db),
               user: User = Depends(require_permission("maps.manage"))):
    if not payload.operations: raise _error(422,'请至少完成一步编辑再另存版本')
    child_id = str(uuid5(NAMESPACE_URL, f"derive:{map_id}:{payload.request_id}"))
    fingerprint = hashlib.sha256(json.dumps({"name": payload.name, "operations": payload.operations}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if db.get(MapModel, child_id):
        existing = db.get(MapModel, child_id)
        if json_loads(existing.meta, {}).get("request_fingerprint") != fingerprint:
            raise _error(409, "请求标识已用于另一份编辑，请刷新后另存版本")
        return serialize_map(existing)
    parent, metadata, packed, changed = _optimized(db, map_id, payload)
    prefix = f"maps/{child_id}/{packed['digest']}"
    assets = {name: f"{prefix}/{name}" for name in packed["assets"]}
    item = MapModel(id=child_id, name=payload.name, floor=parent.floor, description="优化版本；原图保留",
                    width=packed["width"], height=packed["height"], resolution=packed["resolution"],
                    origin=json.dumps(packed["origin"]), active=True, image_key=assets["preview.png"],
                    file_url=f"/api/v1/maps/{child_id}/image")
    item.meta = json.dumps({"source": "slam", "coordinate_space": "map_meters", "navigation_ready": False,
                           "session_id": packed["session_id"], "frame_id": packed["frame_id"], "digest": packed["digest"],
                           "assets": assets, "parent_map_id": map_id, "parent_digest": metadata.get("digest"),
                           'terrain_digest':packed['terrain_digest'],'keepout_digest':packed['keepout_digest'],
                           "operations": payload.operations, "changed_cells": changed, "robot_id": metadata.get("robot_id"), "request_fingerprint": fingerprint}, ensure_ascii=False)
    written = []
    try:
        for name, (content, mime) in packed["assets"].items():
            written.append(assets[name])
            get_storage().put(assets[name], content, content_type=mime)
        db.add(item)
        db.flush()
        record_audit(db, user, "maps.derive", "map", child_id, after=serialize_map(item))
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.get(MapModel, child_id)
        if winner and json_loads(winner.meta, {}).get("digest") == packed["digest"]:
            return serialize_map(winner)
        for key in written:
            _delete_image(key)
        raise _error(409, "该优化请求已存在，请刷新后重试")
    except Exception as exc:
        db.rollback()
        for key in written:
            _delete_image(key)
        raise _error(500, "优化版本保存失败，原图未修改") from exc
    return serialize_map(item)


@router.delete("/selection", status_code=204)
def clear_selection(db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    selected = db.scalar(select(AppSetting).where(AppSetting.key == SELECTION_KEY))
    previous = selected.value if selected else None
    if selected is None:
        selected = AppSetting(id=str(uuid4()), key=SELECTION_KEY, value="")
        db.add(selected)
    else:
        selected.value = ""
    record_audit(db, user, "maps.selection.clear", "map", previous)
    db.commit()
    return Response(status_code=204)


@router.post("/{map_id}/select")
def select_map(map_id: str, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    item = _map(db, map_id)
    if not item.active or not item.image_key:
        raise _error(409, "请选用已启用且有地图图像的地图", "MAP_NOT_AVAILABLE")
    selected = db.scalar(select(AppSetting).where(AppSetting.key == SELECTION_KEY))
    if selected is None:
        selected = AppSetting(id=str(uuid4()), key=SELECTION_KEY, value=map_id)
        db.add(selected)
    else:
        selected.value = map_id
        selected.updated_at = datetime.now(timezone.utc)
    record_audit(db, user, "maps.select", "map", map_id)
    db.commit()
    return {"map_id": map_id}


@router.post("/{map_id}/load-navigation")
async def load_navigation(map_id: str, payload: dict = Body(...), db: Session = Depends(get_db),
                          user: User = Depends(require_permission("maps.manage"))):
    item = _map(db, map_id)
    metadata = json_loads(item.meta, {})
    key = metadata.get("assets", {}).get("snapshot.json", "")
    if not item.active or metadata.get("source") != "slam" or not key.startswith(f"maps/{map_id}/"):
        raise _error(409, "请选择带原始栅格的已启用 SLAM 地图")
    raw = get_storage().get(key)
    if raw is None:
        raise _error(404, "地图文件缺失")
    setting = db.scalar(select(AppSetting).where(AppSetting.key == "robot_web_url"))
    try:
        gateway = get_robot_gateway(setting.value if setting else None)
        snapshot = json.loads(raw)
        if any(snapshot.get('keepout',[])):
            capabilities = await gateway.navigation_request('runtime')
            if 'keepout-v1' not in capabilities.get('map_features',[]):
                raise ValueError('车端尚不支持禁行遮罩，请先更新车端；地图未加载')
        result = await gateway.navigation_request("load-map", {
            "map_id": map_id, "digest": metadata.get("digest"), "snapshot": snapshot, "control_session_id": payload.get("control_session_id")})
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", "小车加载地图失败")
        raise _error(409 if exc.response.status_code < 500 else 502, str(detail)) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise _error(502, f"地图尚未确认加载：{exc}") from exc
    record_audit(db, user, "maps.load_navigation", "map", map_id, after=result)
    db.commit()
    return result


@router.post("/upload", status_code=201)
async def upload_map(
    request: Request,
    name: str = Query(min_length=1, max_length=128),
    floor: str = Query(default="1F", max_length=64),
    description: str = Query(default="", max_length=2000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("maps.manage")),
) -> dict:
    name = name.strip()
    if not name:
        raise _error(422, "地图名称不能为空")
    if request.headers.get("content-type", "").split(";", 1)[0] not in {"image/png", "image/jpeg", "image/webp"}:
        raise _error(415, "仅支持 PNG、JPG、WebP 图片")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_IMAGE_BYTES:
            raise _error(413, "地图图片不能超过 10 MB")
        data.extend(chunk)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("unsupported format")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise _error(413, "地图图片不能超过 1600 万像素")
            image.verify()
        with Image.open(io.BytesIO(data)) as original:
            image = ImageOps.exif_transpose(original)
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
            width, height = image.size
            output = io.BytesIO()
            image.save(output, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise _error(400, "图片无法读取，请上传有效的 PNG、JPG 或 WebP 图片")
    item = MapModel(id=str(uuid4()), name=name, floor=floor.strip(), description=description,
                    width=width, height=height, active=True, resolution=0.05,
                    origin="[]", meta=json.dumps({"source": "uploaded_image", "coordinate_space": "image_pixels", "navigation_ready": False}))
    item.image_key = f"maps/{item.id}.png"
    item.file_url = f"/api/v1/maps/{item.id}/image"
    get_storage().put(item.image_key, output.getvalue(), content_type="image/png")
    try:
        db.add(item)
        db.flush()
        record_audit(db, user, "maps.upload", "map", item.id, after=serialize_map(item))
        db.commit()
    except Exception:
        db.rollback()
        _delete_image(item.image_key)
        raise
    return serialize_map(item)


@router.get("/{map_id}")
def get_map(
    map_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("maps.read")),
) -> dict:
    item = db.get(MapModel, map_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "地图不存在"})
    return serialize_map(item)


@router.get("/{map_id}/image")
def get_map_image(map_id: str, db: Session = Depends(get_db), _: User = Depends(require_permission("maps.read"))):
    item = _map(db, map_id)
    data = get_storage().get(item.image_key) if item.image_key else None
    if data is None:
        raise _error(404, "该地图尚未上传图片", "NOT_FOUND")
    suffix = item.image_key.rsplit(".", 1)[-1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(suffix)
    if mime is None:
        raise _error(415, "该地图图片格式暂不支持显示")
    return Response(data, media_type=mime, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{map_id}/files/{kind}")
def get_map_file(map_id: str, kind: str, db: Session = Depends(get_db), _: User = Depends(require_permission("maps.read"))):
    names = {"yaml": ("map.yaml", "application/yaml"), "pgm": ("map.pgm", "image/x-portable-graymap"), "grid": ("snapshot.json", "application/json")}
    if kind not in names:
        raise _error(404, "地图文件不存在", "NOT_FOUND")
    item = _map(db, map_id)
    filename, mime = names[kind]
    key = json_loads(item.meta, {}).get("assets", {}).get(filename)
    if not isinstance(key, str) or not key.startswith(f"maps/{map_id}/"):
        raise _error(404, "这张地图没有对应的 SLAM 文件", "NOT_FOUND")
    data = get_storage().get(key)
    if data is None:
        raise _error(404, "地图文件已丢失，请重新保存", "NOT_FOUND")
    return Response(data, media_type=mime, headers={"Cache-Control": "private, no-store", "Content-Disposition": f'attachment; filename="{filename}"'})


@router.put("/{map_id}")
def update_map(map_id: str, payload: MapUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    item = _map(db, map_id)
    if payload.active is False:
        selected = db.scalar(select(AppSetting).where(AppSetting.key == SELECTION_KEY))
        if selected and selected.value == map_id:
            raise _error(409, "该地图正在选用，请先取消选用再停用", "MAP_IN_USE")
    before = serialize_map(item)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    record_audit(db, user, "maps.update", "map", item.id, before=before, after=serialize_map(item))
    db.commit()
    return serialize_map(item)


@router.delete("/{map_id}", status_code=204)
def delete_map(map_id: str, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    item = _map(db, map_id)
    selected = db.scalar(select(AppSetting).where(AppSetting.key == SELECTION_KEY))
    if selected and selected.value == map_id:
        raise _error(409, "该地图正在选用，请先取消选用或选用其他地图", "MAP_IN_USE")
    for model in (Route, PatrolTask, MissionTask):
        if db.scalar(select(model.id).where(model.map_id == map_id).limit(1)):
            raise _error(409, "地图已关联路线或任务，请先解除关联后再删除", "MAP_IN_USE")
    record_audit(db, user, "maps.delete", "map", item.id, before=serialize_map(item))
    key = item.image_key
    asset_keys = [value for value in json_loads(item.meta, {}).get("assets", {}).values() if isinstance(value, str) and value.startswith(f"maps/{map_id}/")]
    db.execute(delete(MapPlace).where(MapPlace.map_id == map_id))
    db.delete(item)
    db.commit()
    _delete_image(key)
    for asset in asset_keys: _delete_image(asset)
    return Response(status_code=204)


def serialize_place(item: MapPlace):
    return {"id": item.id, "map_id": item.map_id, "name": item.name, "x": item.x, "y": item.y, "yaw": item.yaw}


def _place(db: Session, map_id: str, place_id: str):
    item = db.get(MapPlace, place_id)
    if item is None or item.map_id != map_id:
        raise _error(404, "地点不存在", "NOT_FOUND")
    return item


def _save_place(db: Session, item: MapPlace, payload: MapPlaceIn, user: User, action: str):
    map_item = _map(db, item.map_id)
    if not map_item.image_key or map_item.width <= 0 or map_item.height <= 0:
        raise _error(409, "请先上传地图图片，再标注地点", "IMAGE_REQUIRED")
    if payload.x >= map_item.width or payload.y >= map_item.height:
        raise _error(422, "地点必须位于地图图片内")
    before = serialize_place(item) if item in db else None
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    map_item.updated_at = datetime.now(timezone.utc)
    db.add(item)
    try:
        db.flush()
        record_audit(db, user, action, "map_place", item.id, before=before, after=serialize_place(item))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(409, "这张地图上已经有同名地点，请换一个名称", "PLACE_NAME_EXISTS")
    return serialize_place(item)


@router.get("/{map_id}/places")
def list_places(map_id: str, db: Session = Depends(get_db), _: User = Depends(require_permission("maps.read"))):
    _map(db, map_id)
    return [serialize_place(p) for p in db.scalars(select(MapPlace).where(MapPlace.map_id == map_id).order_by(MapPlace.created_at, MapPlace.id))]


@router.post("/{map_id}/places", status_code=201)
def create_place(map_id: str, payload: MapPlaceIn, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    return _save_place(db, MapPlace(id=str(uuid4()), map_id=map_id), payload, user, "maps.places.create")


@router.put("/{map_id}/places/{place_id}")
def update_place(map_id: str, place_id: str, payload: MapPlaceIn, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    return _save_place(db, _place(db, map_id, place_id), payload, user, "maps.places.update")


@router.delete("/{map_id}/places/{place_id}", status_code=204)
def delete_place(map_id: str, place_id: str, db: Session = Depends(get_db), user: User = Depends(require_permission("maps.manage"))):
    item = _place(db, map_id, place_id)
    _map(db, map_id).updated_at = datetime.now(timezone.utc)
    record_audit(db, user, "maps.places.delete", "map_place", item.id, before=serialize_place(item))
    db.delete(item)
    db.commit()
    return Response(status_code=204)
