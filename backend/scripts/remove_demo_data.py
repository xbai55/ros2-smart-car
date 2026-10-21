"""Remove only the audited legacy seed records, with an online SQLite backup.

IDs and structural fingerprints deliberately restrict this migration to the
current legacy database. Unknown or user-modified records are retained.
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def clean(database, output):
    database, output = Path(database).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    backup = output / f"before-demo-cleanup-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    with sqlite3.connect(backup) as dest:
        conn.backup(dest)
    protected = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                 for t in ("users", "audit_logs", "map_places")}
    uploaded = [tuple(r) for r in conn.execute("SELECT * FROM maps WHERE image_key IS NOT NULL ORDER BY id")]
    deleted, skipped = {}, []
    candidates = {
        "incidents": {"9a2309f6-382d-4ab4-8a7f-9be502ec6012": lambda r: r["type"] == "smoke_fire" and json.loads(r["media_keys"]) == ["frame-20260918-001"] and not r["handled_by"] and not r["image_url"] and not r["video_url"]},
        "patrol_tasks": {key: lambda r: r["created_by"] is None and r["route_id"] == "aaeb13c3-dd5c-4038-9bb4-314952365343" and r["status"] in ("running", "pending") and r["progress"] in (62., 0.) for key in ("d84db59c-79af-4c0e-a583-2da7a5eb2171", "e8d1a1c9-37b7-4908-8101-196c08ecf561")},
        "mission_tasks": {key: lambda r: r["created_by"] is None and r["route_id"] == "aaeb13c3-dd5c-4038-9bb4-314952365343" and r["status"] in ("transporting", "queued") and r["pickup_code"] in ("8821", "4402") for key in ("90fb525a-df3a-4f2c-919f-fed3aaa80d5b", "567c2d5d-0295-414e-babb-4537af1931ad")},
        "routes": {"aaeb13c3-dd5c-4038-9bb4-314952365343": lambda r: r["created_by"] is None and r["map_id"] == "414a1e24-7783-426c-8b54-b79041f23dc5" and [(p["x"],p["y"]) for p in json.loads(r["points"])] == [(0.,0.),(4.,1.5),(6.5,-2.),(2.,-4.)]},
        "robots": {key: lambda r, name=name, serial=serial: r["name"] == name and r["serial"] == serial and r["last_heartbeat"] is None and r["last_seen"] is None and r["current_task"] is None and r["current_map"] is None for key,name,serial in (("9c2295c1-e98c-4048-9cc7-1d017888076c","Patrol-01","SP-0001"),("c13948b2-b18f-40a1-9d2e-dc4cb621143f","Patrol-02","SP-0002"),("3122cd7a-89b3-4adc-88e6-a7b3ebf32142","Carrier-01","SP-0003"))},
        "maps": {"414a1e24-7783-426c-8b54-b79041f23dc5": lambda r: r["image_key"] is None and r["file_url"] is None},
    }
    refs = {"robots": (("incidents","robot_id"),("patrol_tasks","robot_id"),("mission_tasks","robot_id")), "routes": (("patrol_tasks","route_id"),("mission_tasks","route_id")), "maps": (("routes","map_id"),("map_places","map_id"),("patrol_tasks","map_id"),("mission_tasks","map_id"))}
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table, records in candidates.items():
            deleted[table] = []
            for key, matches in records.items():
                row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
                if row is None:
                    continue
                referenced = any(conn.execute(f"SELECT count(*) FROM {t} WHERE {col}=?", (key,)).fetchone()[0] for t,col in refs.get(table, ()))
                audited_edits = conn.execute("SELECT count(*) FROM audit_logs WHERE resource_id=? AND action NOT LIKE 'auth.%' AND action != 'robots.control'", (key,)).fetchone()[0]
                if not matches(row) or referenced or audited_edits:
                    skipped.append({"table":table,"id":key,"reason":"modified, referenced, or fingerprint mismatch"})
                    continue
                conn.execute(f"DELETE FROM {table} WHERE id=?", (key,))
                deleted[table].append(key)
        for t, rows in protected.items():
            assert rows == [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")], t
        assert uploaded == [tuple(r) for r in conn.execute("SELECT * FROM maps WHERE image_key IS NOT NULL ORDER BY id")]
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    result = {"backup":str(backup),"deleted":deleted,"skipped":skipped,"remaining":{t:conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in candidates},"preserved":{"users":len(protected["users"]),"audit_logs":len(protected["audit_logs"]),"map_places":len(protected["map_places"]),"uploaded_maps":len(uploaded)}}
    (output / "demo-cleanup-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    conn.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("output")
    args = parser.parse_args()
    clean(args.database,args.output)
