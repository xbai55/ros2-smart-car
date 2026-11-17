from types import SimpleNamespace
import pytest
from app.services.capabilities import evaluate_capabilities
from app.services.capability_evidence import PhysicalEvidence, CHECKS, COMMON_CHECKS, canonical_evidence
from datetime import datetime, timezone


def acceptance(value, capability="navigate"):
    telemetry = value["telemetry"]
    fingerprint = evaluate_capabilities(value, [])["capabilities"][capability]["fingerprint"]
    visual = capability in {"observe_target", "patrol_search"}
    evidence = PhysicalEvidence(
        version=1, environment="physical", robot_id=value["robot_id"], capability=capability,
        fingerprint=fingerprint, source_sha256=telemetry["component_manifest"]["source_sha256"],
        map_key=telemetry.get("active_map_key"), performed_at=datetime.now(timezone.utc),
        model_sha256=telemetry.get("vision", {}).get("model_sha256") if visual else None,
        checks=dict.fromkeys(CHECKS[capability] | COMMON_CHECKS, True),
        artifacts=[{"name": "test-log.json", "sha256": "d" * 64}],
        target_trials=[{"target": "服务器机柜", "appearances": 10, "successful_stops": 9}] if visual else [],
        interference_duration_sec=600 if visual else None, interference_false_stops=0 if visual else None,
    )
    encoded, digest = canonical_evidence(evidence)
    return SimpleNamespace(robot_id=value["robot_id"], capability=capability, fingerprint=fingerprint,
                           evidence=encoded, evidence_sha256=digest, revoked_at=None)


def context():
    return {"robot_id": "r-001", "available": True, "telemetry": {
        "component_manifest": {"protocol": 1, "source_sha256": "a" * 64},
        "active_map_key": "map-a", "emergency_stop": False, "navigation": {"ready": True},
        "vision": {"supported": True, "mobile_ready": True, "model_sha256": "b" * 64},
    }}


def test_ready_vehicle_executes_without_acceptance_record():
    result = evaluate_capabilities(context(), [])["capabilities"]
    assert result["navigate"]["ready"]
    assert not result["navigate"]["accepted"]
    assert result["navigate"]["executable"]
    assert result["navigate"]["acceptance_required"] is False
    assert "vehicle_acceptance_required" not in result["navigate"]["reasons"]
    assert not result["observe_target"]["supported"]


def test_changed_map_or_build_invalidates_acceptance():
    value = context()
    records = [acceptance(value)]
    assert evaluate_capabilities(value, records)["capabilities"]["navigate"]["executable"]
    value["telemetry"]["active_map_key"] = "map-b"
    assert not evaluate_capabilities(value, records)["capabilities"]["navigate"]["accepted"]
    assert evaluate_capabilities(value, records)["capabilities"]["navigate"]["executable"]
    value['telemetry']['component_manifest']['source_sha256']='c'*64
    assert evaluate_capabilities(value, records)['capabilities']['navigate']['executable']


def test_removing_acceptance_gate_keeps_emergency_stop_and_readiness_checks():
    value=context()
    value['telemetry']['emergency_stop']=True
    for state in evaluate_capabilities(value,[])['capabilities'].values():
        assert not state['executable']
        assert 'vehicle_acceptance_required' not in state['reasons']
    value=context();value['telemetry']['navigation']['ready']=False
    assert not evaluate_capabilities(value,[])['capabilities']['navigate']['executable']


def test_old_vehicle_and_stale_state_fail_closed():
    value = context()
    value["telemetry"]["component_manifest"] = {}
    assert not evaluate_capabilities(value, [])["capabilities"]["navigate"]["supported"]
    value = context()
    value["available"] = False
    assert not evaluate_capabilities(value, [])["capabilities"]["navigate"]["ready"]


@pytest.mark.parametrize("field,value", [("component_manifest", []), ("navigation", "ready"),
                                         ("active_map_key", float("nan"))])
def test_malformed_telemetry_never_enables_execution(field, value):
    snapshot = context()
    snapshot["telemetry"][field] = value
    assert not evaluate_capabilities(snapshot, [])["capabilities"]["navigate"]["ready"]


def test_acceptance_cannot_be_reused_for_another_robot():
    value = context()
    records = [acceptance(value)]
    value["robot_id"] = "another-robot"
    assert not evaluate_capabilities(value, records)["capabilities"]["navigate"]["accepted"]


def test_mobile_certificate_without_model_identity_is_not_ready():
    value = context()
    value["telemetry"]["vision"]["model_sha256"] = None
    result = evaluate_capabilities(value, [])["capabilities"]["patrol_search"]
    assert not result["ready"]
    assert "model_identity_required" in result["reasons"]


def test_stationary_search_requires_own_acceptance_without_nav2():
    value = context()
    value["telemetry"].update(active_map_key=None, navigation={}, mode="stop", odom={"ok": True})
    value["telemetry"]["vision"].update(stationary_search_supported=True, state="running", mobile_ready=False)
    result = evaluate_capabilities(value, [])["capabilities"]["observe_target"]
    assert result["ready"] and result["executable"]
    records = [acceptance(value, "observe_target")]
    assert evaluate_capabilities(value, records)["capabilities"]["observe_target"]["executable"]


def test_legacy_tampered_and_revoked_evidence_cannot_enable_motion():
    from app.services.capability_evidence import valid_record

    value = context()
    record = acceptance(value)
    assert valid_record(record)
    record.evidence += " "
    assert not valid_record(record)
    record = acceptance(value)
    record.revoked_at = datetime.now(timezone.utc)
    assert not evaluate_capabilities(value, [record])["capabilities"]["navigate"]["accepted"]
    legacy = SimpleNamespace(capability="navigate", fingerprint=record.fingerprint)
    assert not evaluate_capabilities(value, [legacy])["capabilities"]["navigate"]["accepted"]


def test_acceptance_registration_checks_identity_permissions_and_revocation(client, login, seeded_db, monkeypatch):
    import json
    from uuid import uuid4
    from app.models import CapabilityAcceptance
    from app.services import control_access, robot_context

    value = context()
    value["robot_id"] = "fixture-robot-1"
    value["telemetry"].update(mode="stop", odom={"ok": True, "odom_age_sec": .1, "linear_speed": 0, "angular_speed": 0})
    monkeypatch.setattr(control_access, "vehicle_binding", lambda db: (value["robot_id"], "fixture"))
    monkeypatch.setattr(robot_context.robot_context_service, "context", lambda *args: value)
    record = acceptance(value)
    body = {"request_id": str(uuid4()), "evidence": json.loads(record.evidence)}
    root = "/api/v1/robots/fixture-robot-1/acceptances"
    admin = {"Authorization": "Bearer " + login("admin", "admin123")}
    operator = {"Authorization": "Bearer " + login("operator", "operator123")}
    assert client.post(root, json=body).status_code == 401
    assert client.post(root, headers=operator, json=body).status_code == 403
    template = client.get("/api/v1/robots/fixture-robot-1/acceptance-template?capability=navigate", headers=admin)
    assert template.status_code == 200
    assert not any(template.json()["evidence"]["checks"].values())
    assert client.post(root, headers=admin, json=template.json()).status_code == 422
    try:
        wrong = {**body, "evidence": {**body["evidence"], "source_sha256": "e" * 64}}
        assert client.post(root, headers=admin, json=wrong).status_code == 409
        incomplete = {**body, "evidence": {**body["evidence"], "checks": {}}}
        assert client.post(root, headers=admin, json=incomplete).status_code == 422
        value["telemetry"]["odom"]["odom_age_sec"] = 2
        assert client.post(root, headers=admin, json=body).status_code == 409
        value["telemetry"]["odom"]["odom_age_sec"] = .1
        first = client.post(root, headers=admin, json=body)
        assert first.status_code == 200, first.text
        assert client.post(root, headers=admin, json=body).json() == first.json()
        path = root + "/" + body["request_id"]
        assert client.get(path, headers=admin).json()["evidence_valid"]
        assert client.get("/api/v1/robots/fixture-robot-1/capabilities", headers=admin).json()["capabilities"]["navigate"]["executable"]
        revoked = client.post(path + "/revoke", headers=admin, json={"reason": "实车复测发现异常"})
        assert revoked.status_code == 200
        again = client.post(path + "/revoke", headers=admin, json={"reason": "迟到的重复撤销"})
        assert again.json()["revocation_reason"] == "实车复测发现异常"
        assert not client.get(path, headers=admin).json()["evidence_valid"]
        assert client.get("/api/v1/robots/fixture-robot-1/capabilities", headers=admin).json()["capabilities"]["navigate"]["executable"]
    finally:
        seeded_db.expire_all()
        row = seeded_db.get(CapabilityAcceptance, body["request_id"])
        if row is not None:
            seeded_db.delete(row)
            seeded_db.commit()


def test_search_evidence_requires_target_quality_and_joint_measurements():
    import json
    from pydantic import ValidationError
    from app.services.capability_evidence import validate_evidence

    value = context()
    report = json.loads(acceptance(value, "patrol_search").evidence)
    with pytest.raises(ValueError, match="联合性能"):
        validate_evidence(PhysicalEvidence.model_validate(report))
    report["mobile"] = {"joint_duration_sec": 600, "effective_hz": 3, "frame_age_p95_sec": .5,
                        "control_overruns_added": 0, "navigation_running": True, "video_running": True}
    validate_evidence(PhysicalEvidence.model_validate(report))
    report["target_trials"][0]["successful_stops"] = 11
    with pytest.raises(ValueError, match="计数"):
        validate_evidence(PhysicalEvidence.model_validate(report))
    report["mobile"]["effective_hz"] = 2.9
    with pytest.raises(ValidationError):
        PhysicalEvidence.model_validate(report)


def test_existing_acceptance_table_upgrades_without_losing_evidence():
    from sqlalchemy import create_engine, text
    from app.db.migrate import ensure_schema

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE capability_acceptances (id VARCHAR(36) PRIMARY KEY, robot_id VARCHAR(36), "
                              "capability VARCHAR(32), fingerprint VARCHAR(64), evidence_sha256 VARCHAR(64), "
                              "evidence TEXT, accepted_by VARCHAR(36), created_at DATETIME)"))
            conn.execute(text("INSERT INTO capability_acceptances (id, evidence) VALUES ('old', 'legacy proof')"))
        assert set(ensure_schema(engine)) == {"capability_acceptances.revoked_by", "capability_acceptances.revoked_at",
                                              "capability_acceptances.revocation_reason"}
        assert ensure_schema(engine) == []
        with engine.connect() as conn:
            assert conn.execute(text("SELECT evidence, revoked_at FROM capability_acceptances")).one() == ("legacy proof", None)
            assert conn.scalar(text("SELECT COUNT(*) FROM schema_migrations WHERE revision='v4-capability-evidence-1'")) == 1
    finally:
        engine.dispose()
