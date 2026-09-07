from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse


# These defaults must be set before importing server.py because that module reads
# its configuration at import time. Explicit Railway variables always win.
_RECOMMENDED_DEFAULTS = {
    "GARMIN_TIMEZONE": "America/Santiago",
    "GARMIN_LANGUAGE": "es",
    "CACHE_MINUTES": "10",
    "ACTIVITY_LIMIT": "20",
    "AUTO_SYNC_TOKENS": "1",
    "AUTO_SYNC_INTERVAL_SECONDS": "43200",
    "MCP_READ_ONLY": "1",
}
for _name, _value in _RECOMMENDED_DEFAULTS.items():
    os.environ.setdefault(_name, _value)


import server as original_server  # noqa: E402  (defaults must be applied first)


MUTATING_GARMIN_TOOLS = frozenset(
    {
        "add_weigh_in",
        "delete_weigh_in",
        "delete_weigh_ins",
        "schedule_workout",
        "set_gear_default",
        "unschedule_workout",
        "upload_activity",
    }
)


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().casefold() in {"1", "true", "yes", "on"}


READ_ONLY_ENABLED = _env_flag("MCP_READ_ONLY", "1")
mcp = original_server.mcp

if READ_ONLY_ENABLED:
    # FastMCP 3.2.4 visibility rules remove these tools from listings and reject
    # direct calls as unknown tools. This is applied after server.py registers all
    # tools, so the original implementation remains untouched.
    mcp.disable(names=set(MUTATING_GARMIN_TOOLS))


class MCPBearerAuthMiddleware:
    """Require a configured bearer token for /mcp and every path below it."""

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    @staticmethod
    def _protects(path: str) -> bool:
        return path == "/mcp" or path.startswith("/mcp/")

    @staticmethod
    def _presented_token(scope: dict[str, Any]) -> str | None:
        authorization_values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"authorization"
        ]
        if len(authorization_values) != 1:
            return None

        try:
            authorization = authorization_values[0].decode("latin-1")
        except (AttributeError, UnicodeDecodeError):
            return None

        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not token:
            return None
        return token

    @classmethod
    def _authorized(cls, scope: dict[str, Any]) -> bool:
        expected = os.getenv("MCP_API_TOKEN", "").strip()
        presented = cls._presented_token(scope)
        if not expected or presented is None:
            return False
        return secrets.compare_digest(presented, expected)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope.get("type") in {"http", "websocket"} and self._protects(path):
            if not self._authorized(scope):
                if scope.get("type") == "websocket":
                    await send({"type": "websocket.close", "code": 4401})
                else:
                    response = JSONResponse(
                        {"error": "Unauthorized"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _http_middleware() -> list[Middleware]:
    return [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "MCP-Protocol-Version",
                "MCP-Session-Id",
            ],
            expose_headers=["MCP-Session-Id"],
        ),
        Middleware(MCPBearerAuthMiddleware),
        Middleware(original_server._MCPHitTracker),
    ]


def create_app():
    """Build the ASGI app used by tests and alternate ASGI runners."""
    return mcp.http_app(middleware=_http_middleware())


def _start_background_workers() -> None:
    refresh_thread = threading.Thread(
        target=original_server._background_refresh_loop,
        daemon=True,
        name="garmin-cache-refresh",
    )
    refresh_thread.start()

    if original_server.AUTO_SYNC_TOKENS:
        sync_thread = threading.Thread(
            target=original_server._auto_sync_tokens_loop,
            daemon=True,
            name="auto-sync-tokens",
        )
        sync_thread.start()


def run() -> None:
    original_server.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    _start_background_workers()

    if original_server._is_first_run():
        print("=" * 60, flush=True)
        print("Garmin Coach MCP - PRIMER ARRANQUE", flush=True)
        print("Abre la URL publica del servicio y usa el asistente de login.", flush=True)
        print("=" * 60, flush=True)

    token_configured = bool(os.getenv("MCP_API_TOKEN", "").strip())
    print(
        "MCP Bearer auth: " + ("activa" if token_configured else "BLOQUEADO: falta MCP_API_TOKEN"),
        flush=True,
    )
    print(
        "MCP Garmin mode: " + ("solo lectura" if READ_ONLY_ENABLED else "lectura y escritura"),
        flush=True,
    )

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=original_server.PORT,
        middleware=_http_middleware(),
    )


if __name__ == "__main__":
    run()
