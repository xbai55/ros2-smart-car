"""Time-bounded incident statistics with immutable report snapshots."""
from datetime import date, datetime, time, timedelta, timezone
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..models import Incident, SafetyCoverage
from .ops import json_loads
from .fall_review import alert_clause

SHANGHAI = ZoneInfo("Asia/Shanghai")
DETAIL_LIMIT = 200
TYPES = {
    "smoke_fire": "烟火告警", "fallen_person": "倒地告警", "blocked_passage": "通道异常",
    "suspected_clutter": "疑似杂物（占道未确认）", "target_found": "目标发现",
}
STATUSES = {"open": "待核查", "acknowledged": "已确认事件", "handling": "处理中",
            "resolved": "已解决", "dismissed": "已排除"}


def report_window(start_date: date | None = None, end_date: date | None = None, *, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(SHANGHAI).date()
    start_date = start_date or today
    end_date = end_date or start_date
    if not timedelta(0) <= end_date - start_date < timedelta(days=31) or end_date > today:
        raise ValueError("日期范围须为过去或今天，最多 31 天")
    start = datetime.combine(start_date, time.min, SHANGHAI).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, SHANGHAI).astimezone(timezone.utc)
    return start, end


def record_coverage(db, robot_id, state, *, now=None):
    minute = int((now or datetime.now(timezone.utc)).timestamp()) // 60
    row = db.get(SafetyCoverage, (robot_id, minute))
    if row is None:
        db.add(SafetyCoverage(robot_id=robot_id, minute=minute, state=state))
        db.commit()
    elif row.state != "interrupted" and state == "interrupted":
        row.state = state
        db.commit()


def _coverage(db, robot_id, start, end, now):
    first, last = int(start.timestamp()) // 60, int(min(end, now).timestamp()) // 60
    minutes = dict(db.execute(select(SafetyCoverage.minute, SafetyCoverage.state).where(
        SafetyCoverage.robot_id == robot_id, SafetyCoverage.minute >= first, SafetyCoverage.minute < last
    )).all())
    intervals = []
    for minute in range(first, last):
        state = minutes.get(minute, "unknown")
        if intervals and intervals[-1][2] == state:
            intervals[-1][1] = minute + 1
        else:
            intervals.append([minute, minute + 1, state])

    def timestamp(minute):
        return datetime.fromtimestamp(minute * 60, SHANGHAI).isoformat()

    return [{"start": timestamp(a), "end": timestamp(b), "state": state} for a, b, state in intervals]


def incident_report(db, robot_id, start_date=None, end_date=None, *, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = report_window(start_date, end_date, now=now)
    window = (Incident.occurred_at >= start, Incident.occurred_at < end, alert_clause())
    grouped = db.execute(select(Incident.type, Incident.status, func.count()).where(
        *window
    ).group_by(Incident.type, Incident.status)).all()
    by_type, by_status = {}, {}
    for kind, status, count in grouped:
        by_type[kind] = by_type.get(kind, 0) + count
        by_status[status] = by_status.get(status, 0) + count
    rows = db.scalars(select(Incident).where(*window).order_by(
        Incident.occurred_at.desc(), Incident.id.desc()).limit(DETAIL_LIMIT)).all()
    details = []
    for row in rows:
        evidence = json_loads(row.evidence, {})
        evidence = evidence if isinstance(evidence, dict) else {}
        stamp = row.occurred_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        details.append({
            "id": row.id, "type": row.type, "type_label": TYPES.get(row.type, row.type),
            "status": row.status, "status_label": STATUSES.get(row.status, row.status),
            "occurred_at": stamp.astimezone(SHANGHAI).isoformat(), "title": row.title,
            "source": "车端识别" if evidence.get("source_event_id") else "人工或导入记录",
            "evidence_path": "/incidents/" + quote(row.id, safe=""),
        })
    missing_time = db.scalar(select(func.count()).select_from(Incident).where(
        Incident.occurred_at.is_(None), Incident.created_at >= start, Incident.created_at < end, alert_clause()))
    total = sum(by_type.values())
    return {"timezone": "Asia/Shanghai", "start": start.astimezone(SHANGHAI).isoformat(),
            "end": end.astimezone(SHANGHAI).isoformat(), "generated_at": now.isoformat(),
            "total": total, "by_type": by_type, "by_status": by_status,
            "type_labels": TYPES, "status_labels": STATUSES,
            "missing_occurrence_time": missing_time, "details": details, "truncated": total > len(details),
            "coverage_robot_id": robot_id,
            "coverage": _coverage(db, robot_id, start, end, now) if robot_id else [],
            "coverage_note": "覆盖仅反映当前绑定车辆上报链路的分钟采样。未记录时段的覆盖未知。"}


def report_reply(report):
    return (f"已汇总上海时间 {report['start'][:10]} 至 "
            f"{(datetime.fromisoformat(report['end']).date()-timedelta(days=1)).isoformat()} 的异常记录，"
            f"数据库共计 {report['total']} 条。详情见报告。")


def markdown(report):
    def inline(value):
        return re.sub(r"([\\`*_{}\[\]()#+.!|<>])", r"\\\1", " ".join(str(value).split()))

    lines = ["# 异常事件报告", "", report_reply(report), "",
             f"范围（左闭右开）：{report['start']} 至 {report['end']}", "",
             f"缺少发生时间、未计入统计的记录：{report['missing_occurrence_time']} 条", "",
             "## 分类统计", ""]
    lines.extend(f"- {inline(TYPES.get(kind, kind))}：{count}" for kind, count in sorted(report["by_type"].items()))
    lines.extend(["", "## 处理状态", ""])
    lines.extend(f"- {inline(STATUSES.get(status, status))}：{count}" for status, count in sorted(report["by_status"].items()))
    lines.extend(["", "## 证据", ""])
    focus = set(report.get("focus_ids", []))
    for row in sorted(report["details"], key=lambda item: item["id"] not in focus):
        prefix = "重点 · " if row["id"] in focus else ""
        lines.append(f"- [{inline(row['id'])}](#{row['evidence_path']}) · {row['occurred_at']} · "
                     f"{prefix}{inline(row['type_label'])} · {inline(row['status_label'])} · {inline(row['source'])} · {inline(row['title'])}")
    if report["truncated"]:
        lines.append(f"- 证据列表仅列出最近 {len(report['details'])} 条。")
    lines.extend(["", "## 采集覆盖", "", report["coverage_note"], ""])
    labels = {"observed": "观察到正常上报", "interrupted": "上报中断或待补传", "unknown": "覆盖未知"}
    lines.extend(f"- {item['start']} 至 {item['end']} · {labels[item['state']]}" for item in report["coverage"])
    return "\n".join(lines) + "\n"
