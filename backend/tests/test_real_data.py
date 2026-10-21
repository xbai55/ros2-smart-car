import time
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Incident, MapModel, MissionTask, PatrolTask, Robot, Route, User
from app.seed import seed_session
from app.services.realtime import get_realtime_store
from app.services.robots import serialize_robot


def test_initialization_never_invents_business_records():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_session(db)
        assert db.query(User).count() == 3
        for model in (Robot, MapModel, Route, PatrolTask, MissionTask, Incident):
            assert db.query(model).count() == 0


def test_missing_or_expired_telemetry_is_unknown():
    robot = Robot(id="physical",name="Actual",serial="ACT",status="online",mode="patrol",battery=100,speed=1,health="good",position='{"x":1}',network='{}')
    for realtime in (None,{"status":"online","battery":99,"updated_at":time.time()-90}):
        value = serialize_robot(robot,realtime)
        assert value["status"] == "offline"
        assert value["battery"] is None
        assert value["mode"] is None
        assert value["position"] == {}
        assert value["source"] == "unavailable"
    fresh = serialize_robot(robot,{"status":"online","battery":63,"updated_at":time.time()})
    assert fresh["battery"] == 63
    assert fresh["source"] == "realtime"


def test_simulation_endpoints_removed(client):
    assert client.post("/api/v1/robots/physical/simulate",json={}).status_code == 404
    assert client.post("/api/v1/robots/physical/activity",json={}).status_code == 405


@pytest.mark.parametrize("accepted", [False, True])
def test_commands_do_not_change_observed_state(client,login,seeded_db,monkeypatch,accepted):
    from app.api.routes import robots
    robot = Robot(id="failed-control-physical",name="Actual",serial="ACTUAL-TEST",status="offline",mode="stop",battery=0,speed=0)
    seeded_db.add(robot)
    seeded_db.commit()
    store = get_realtime_store()
    store.set_status(robot.id,{"status":"online","mode":"stop","speed":0,"emergency_stop":False})
    before = store.get_status(robot.id)
    class Gateway:
        async def send_command(self,*args,**kwargs):
            return {"ok":accepted,"gateway":"http","target":None,"detail":"accepted" if accepted else "unavailable","command":{},"response":None}
        async def emergency_stop(self,*args,**kwargs):
            return await self.send_command()
    monkeypatch.setattr(robots,"get_robot_gateway",lambda *a:Gateway())
    headers = {"Authorization":"Bearer "+login("admin","admin123")}
    response = client.post(f"/api/v1/robots/{robot.id}/control",headers=headers,json={"command":"set_mode","speed":0.3,"params":{"mode":"manual"}})
    assert response.status_code == 200 and response.json()["ok"] == accepted
    assert store.get_status(robot.id) == before
    response = client.post(f"/api/v1/robots/{robot.id}/emergency-stop",headers=headers,json={"enabled":True})
    assert response.status_code == 200 and response.json()["ok"] == accepted
    assert store.get_status(robot.id) == before
    seeded_db.refresh(robot)
    assert robot.mode == "stop" and robot.status == "offline"
    store.clear_status(robot.id)
    seeded_db.delete(robot)
    seeded_db.commit()


def test_accepted_request_without_telemetry_stays_unknown(client,login,seeded_db,monkeypatch):
    from app.api.routes import robots
    robot = Robot(id="no-telemetry",name="No telemetry",serial="NO-TELEMETRY",status="offline",mode="stop")
    seeded_db.add(robot)
    seeded_db.commit()
    class Gateway:
        async def emergency_stop(self,*args,**kwargs):
            return {"ok":True,"gateway":"http","target":None,"detail":"accepted","command":{}}
    monkeypatch.setattr(robots,"get_robot_gateway",lambda *a:Gateway())
    headers = {"Authorization":"Bearer "+login("admin","admin123")}
    response = client.post(f"/api/v1/robots/{robot.id}/emergency-stop",headers=headers,json={"enabled":False})
    assert response.json()["ok"]
    value = response.json()["robot"]
    assert value["status"] == "offline" and value["mode"] is None and value["emergency_stop"] is None
    assert get_realtime_store().get_status(robot.id) is None
    seeded_db.delete(robot)
    seeded_db.commit()
