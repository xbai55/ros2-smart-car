"""Read-only transfer from the authenticated gateway of the bound vehicle."""
import asyncio
import json
import sqlite3
from contextlib import closing
from hashlib import sha256

import httpx

from ...db.session import SessionLocal
from ...gateway.robot_gateway import RobotGateway
from ...models import Robot
from ..robot_context import vehicle_binding
from . import identifier, utc

CHANNELS = {f"{slot}-{lane}" for slot in ("controller", "web", "launch") for lane in (0, 1)}


def binding():
    with SessionLocal() as db:
        robot, address = vehicle_binding(db)
        return (robot, address) if address and db.get(Robot, robot) else None


def progress(store, key):
    with closing(store.connect(readonly=True)) as db:
        row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None


async def pull(gateway, cursors):
    async with gateway._client(2) as client:
        async with client.stream("GET", gateway._url("/api/diagnostics/events"),
                                 params={"cursors": json.dumps(cursors, separators=(",", ":"))}) as response:
            response.raise_for_status()
            content = bytearray()
            async for block in response.aiter_bytes(chunk_size=4096):
                if len(content) + len(block) > 256 * 1024:
                    raise ValueError("vehicle response too large")
                content.extend(block)
    page = json.loads(content)
    events, cursors = page["events"], page["cursors"]
    if (not isinstance(events, list) or len(events) > 64 or not isinstance(cursors, dict)
            or not cursors.keys() <= CHANNELS or any(not identifier(value) for value in cursors.values())):
        raise ValueError("invalid vehicle page")
    return page


async def ingest_vehicle(store):
    delay = 2
    while True:
        try:
            current = await asyncio.to_thread(binding)
            if not current:
                store.health["vehicle"] = {"status": "unbound"}
            elif store.health["status"] == "ready":
                robot, address = current
                gateway = RobotGateway(address)
                address_key = 'vehicle-address:' + sha256(address.encode()).hexdigest()
                address_pin = await asyncio.to_thread(progress, store, address_key)
                previous_instance = (address_pin or {}).get('instance_id')
                previous_key = 'vehicle:' + previous_instance if previous_instance else None
                previous = await asyncio.to_thread(progress, store, previous_key) if previous_key else None
                page = await pull(gateway, previous['cursors'] if previous else {})
                instance = page.get('instance_id')
                if not isinstance(instance, str) or len(instance) != 32 or any(c not in '0123456789abcdef' for c in instance):
                    raise ValueError('vehicle diagnostic installation identity missing')
                key = 'vehicle:' + instance
                if instance != previous_instance:
                    previous = await asyncio.to_thread(progress, store, key)
                    if previous or previous_instance:
                        page = await pull(gateway, previous['cursors'] if previous else {})
                        if page.get('instance_id') != instance:
                            raise ValueError('vehicle changed during transfer')
                if await asyncio.to_thread(binding) != current:
                    await asyncio.sleep(2)
                    continue
                rows = []
                changed = previous is not None and previous["robot"] != robot
                invalid = page.get("invalid", 0)
                invalid = invalid if type(invalid) is int and invalid >= 0 else 0
                gaps = page.get("gaps")
                gaps = [item for item in gaps[:6] if isinstance(item, str) and item in CHANNELS] if isinstance(gaps, list) else []
                for row in page["events"]:
                    if not isinstance(row, dict) or row.get("schema_version") != 1 or not identifier(row.get("event_id")):
                        invalid += 1
                        continue
                    if not changed and not (previous or {}).get("quarantine"):
                        rows.append({**row, "source": "jetson", "robot_id": robot,
                                     "event_id": sha256((key + row["event_id"]).encode()).hexdigest(),
                                     "task_id": None, "execution_id": None, "exception": None})
                quarantine = changed or bool((previous or {}).get("quarantine"))
                await asyncio.to_thread(store.write, rows, [
                    (key, json.dumps({'robot': robot, 'cursors': page['cursors'], 'quarantine': quarantine})),
                    (address_key, json.dumps({'instance_id': instance})),
                ])
                health = page.get('health') if isinstance(page.get('health'), dict) else {}
                store.health['vehicle'] = {
                    'status': 'quarantined' if quarantine else 'degraded' if gaps or invalid else 'ready',
                    'last_sync': utc(), 'gaps': gaps, 'invalid': invalid,
                    'version': identifier(health.get('version')),
                    'build': identifier(health.get('build')),
                    'pose_write_failed': health.get('pose_write_failed') is True,
                    'web_write_failed': health.get('web_write_failed')
                    if type(health.get('web_write_failed')) is int else None,
                }
            delay = 2
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            previous = store.health.get("vehicle", {})
            store.health["vehicle"] = {**previous, "status": "offline"}
            delay = min(30, delay * 2)
        await asyncio.sleep(delay)
