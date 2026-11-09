"""Machine authentication for HTTP and WebSocket vehicle interfaces."""
import hmac
import os
from starlette.responses import JSONResponse


class ServiceAuthentication:
    def __init__(self, app):
        self.app = app
        self.token = os.environ.get("ROBOT_SERVICE_TOKEN", "")

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"} or scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-insightrover-service-token", b"")
        valid = len(self.token) >= 32 and hmac.compare_digest(supplied, self.token.encode())
        if not valid:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401})
            else:
                status = 503 if len(self.token) < 32 else 401
                response = JSONResponse({"detail": "车端机器凭据未配置" if status == 503 else "机器凭据无效"}, status_code=status)
                await response(scope, receive, send)
            return
        from .diagnostic_log import correlation, request_ids
        keys = {b'traceparent', b'x-request-id', b'x-insightrover-run-id'}
        ids = correlation({key.decode(): value.decode('latin1') for key, value in headers.items() if key in keys})
        token = request_ids.set(ids)
        try:
            await self.app(scope, receive, send)
        finally:
            request_ids.reset(token)
