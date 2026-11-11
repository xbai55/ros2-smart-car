import hashlib
import json
import re
from sqlalchemy import select
from ..models import CapabilityAcceptance
from .capability_evidence import valid_record

CAPABILITIES = ("navigate", "patrol", "deliver", "observe_target", "patrol_search", "move_relative")


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _object(value):
    return value if isinstance(value, dict) else {}


def evaluate_capabilities(context, acceptances):
    telemetry = _object(context.get("telemetry"))
    manifest = _object(telemetry.get("component_manifest"))
    known = type(manifest.get("protocol")) is int and manifest.get("protocol") == 1 and _digest(manifest.get("source_sha256"))
    vision = _object(telemetry.get("vision"))
    navigation = _object(telemetry.get("navigation"))
    mapped = bool(telemetry.get("active_map_key"))
    result = {}
    for name in CAPABILITIES:
        visual = name in {"observe_target", "patrol_search"}
        stationary = name == "observe_target"
        relative = name == "move_relative"
        identity = {"robot_id": context["robot_id"], "capability": name,
                    "manifest": manifest, "map_key": telemetry.get("active_map_key")}
        if visual:
            identity["vision"] = {key: vision.get(key) for key in ("build_id", "model_sha256", "imgsz", "recovery_epoch")}
        try:
            fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError):
            fingerprint = None
        supported = (known and (not visual or vision.get("supported") is True)
                     and (not stationary or vision.get("stationary_search_supported") is True)
                     and (not relative or _object(telemetry.get("relative_motion")).get("supported") is True))
        motion_ready = (telemetry.get("mode") == "stop" and _object(telemetry.get("odom")).get("ok") is True
                        if stationary else mapped and navigation.get("ready") is True)
        if relative:
            active_task = _object(telemetry.get("navigation_task")).get("state")
            motion_ready = (telemetry.get("mode") == "stop"
                and all(_object(telemetry.get(key)).get("ok") is True for key in ("lidar","odom","tf","relative_motion"))
                and _object(telemetry.get("avoidance")).get("confirmed") is True
                and _object(telemetry.get("avoidance")).get("available") is True
                and _object(telemetry.get("search_control")).get("active") is not True
                and active_task in (None,"idle","completed","cancelled","failed"))
        ready = bool(context.get("available") is True and context.get("stale") is not True
                     and fingerprint and supported and motion_ready
                     and telemetry.get("emergency_stop") is False
                     and (not visual or ((vision.get("state") == "running" if stationary else vision.get("mobile_ready") is True)
                                          and _digest(vision.get("model_sha256")))))
        accepted = bool(fingerprint) and any(row.capability == name and row.fingerprint == fingerprint
                                             and valid_record(row) for row in acceptances)
        reasons = []
        if not supported:
            reasons.append("unsupported_protocol_or_capability")
        if not ready:
            reasons.append("vehicle_not_ready")
            if context.get("available") is not True or context.get("stale") is True:
                reasons.append("telemetry_stale_or_unknown")
            if not mapped and not stationary and not relative:
                reasons.append("active_map_required")
            if telemetry.get("emergency_stop") is not False:
                reasons.append("emergency_stop_active_or_unknown")
            if visual and not _digest(vision.get("model_sha256")):
                reasons.append("model_identity_required")
        if not accepted:
            reasons.append("vehicle_acceptance_required")
        result[name] = {"supported": supported, "ready": ready, "accepted": accepted,
                        "executable": supported and ready and accepted,
                        "fingerprint": fingerprint, "reasons": reasons}
    return {"robot_id": context["robot_id"], "capabilities": result, "components": manifest}


def capability_snapshot(db, context):
    records = db.scalars(select(CapabilityAcceptance).where(
        CapabilityAcceptance.robot_id == context["robot_id"]
    )).all()
    return evaluate_capabilities(context, records)
