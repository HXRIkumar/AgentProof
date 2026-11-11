"""Small local-server resource boundary; checks actual bytes before JSON parsing."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = 1_048_576


class BodyTooLarge(HTTPException):
    def __init__(self, limit):
        super().__init__(413, f"Request body exceeds {limit} bytes")


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes=MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    return await JSONResponse(
                        {"detail": "Invalid Content-Length"}, status_code=400
                    )(scope, receive, send)
                if declared < 0:
                    return await JSONResponse(
                        {"detail": "Invalid Content-Length"}, status_code=400
                    )(scope, receive, send)
                if declared > self.max_bytes:
                    return await JSONResponse(
                        {"detail": f"Request body exceeds {self.max_bytes} bytes"}, status_code=413
                    )(scope, receive, send)
        consumed = 0

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise BodyTooLarge(self.max_bytes)
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge as exc:
            # FastAPI's exception middleware normally handles this. Keep the wrapper
            # usable for standalone ASGI consumers without converting the error to 500.
            await JSONResponse({"detail": exc.detail}, status_code=413)(scope, receive, send)
