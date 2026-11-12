"""The document upload allowance does not relax other routes or trust headers."""

import asyncio

import httpx
from starlette.responses import JSONResponse

from agentproof.middleware import RequestBodyLimitMiddleware


async def echo_size(scope, receive, send):
    total = 0
    while True:
        message = await receive()
        total += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    await JSONResponse({"bytes": total})(scope, receive, send)


def test_upload_allowance_is_exact_path_and_post_only():
    async def exercise():
        app = RequestBodyLimitMiddleware(echo_size, max_bytes=10,
                                        post_path_limits={"/api/support/documents": 20})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
            assert (await c.post("/api/support/documents", content=b"x" * 20)).status_code == 200
            assert (await c.post("/api/support/documents", content=b"x" * 21)).status_code == 413
            assert (await c.post("/api/answers/run", content=b"x" * 11)).status_code == 413
            assert (await c.put("/api/support/documents", content=b"x" * 11)).status_code == 413
    asyncio.run(exercise())


def test_chunked_upload_enforces_actual_route_limit_with_misleading_length():
    async def exercise():
        async def chunks():
            yield b"x" * 12
            yield b"x" * 12
        app = RequestBodyLimitMiddleware(echo_size, max_bytes=10,
                                        post_path_limits={"/api/support/documents": 20})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
            response = await c.post("/api/support/documents", content=chunks(),
                                    headers={"content-length": "1"})
            assert response.status_code == 413
    asyncio.run(exercise())
