"""Request-local correlation for diagnostic events."""
import re
from contextvars import ContextVar
from uuid import uuid4

context = ContextVar("diagnostic_context", default={})
IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
TRACE = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}\Z")


def request_context(headers):
    request_id = headers.get("x-request-id", "")
    return {
        "request_id": request_id if IDENT.fullmatch(request_id) else uuid4().hex,
        "trace_id": uuid4().hex,
    }


def wire_headers():
    value = context.get()
    if not value.get("trace_id"):
        return {}
    span = uuid4().hex[:16]
    result = {"traceparent": f"00-{value['trace_id']}-{span}-00"}
    if value.get('run_id') and IDENT.fullmatch(value['run_id']):
        result['X-InsightRover-Run-ID'] = value['run_id']
    if value.get("request_id"):
        result["X-Request-ID"] = value["request_id"]
    return result
