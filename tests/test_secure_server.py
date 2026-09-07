from __future__ import annotations

import asyncio
import os
import unittest


os.environ["MCP_API_TOKEN"] = "unit-test-token"
os.environ["MCP_READ_ONLY"] = "1"

import secure_server  # noqa: E402

from fastmcp import Client  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


class SecureServerTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MCP_API_TOKEN"] = "unit-test-token"

    def test_health_is_public(self) -> None:
        os.environ.pop("MCP_API_TOKEN", None)
        with TestClient(secure_server.create_app()) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_mcp_is_locked_when_token_is_missing(self) -> None:
        os.environ.pop("MCP_API_TOKEN", None)
        with TestClient(secure_server.create_app()) as client:
            response = client.post("/mcp")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def test_mcp_rejects_missing_and_wrong_bearer_tokens(self) -> None:
        with TestClient(secure_server.create_app()) as client:
            missing = client.post("/mcp")
            wrong = client.post(
                "/mcp/anything",
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)

    def test_mcp_accepts_correct_bearer_token(self) -> None:
        with TestClient(secure_server.create_app()) as client:
            response = client.post(
                "/mcp",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer unit-test-token",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "security-test", "version": "1.0"},
                    },
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Garmin Coach MCP", response.text)

    def test_read_only_hides_all_mutating_garmin_tools(self) -> None:
        visible = {
            tool.name for tool in asyncio.run(secure_server.mcp.list_tools())
        }
        self.assertTrue(secure_server.READ_ONLY_ENABLED)
        self.assertTrue(secure_server.MUTATING_GARMIN_TOOLS.isdisjoint(visible))
        self.assertIn("get_stats", visible)

    def test_read_only_rejects_direct_mutating_tool_call(self) -> None:
        async def call_disabled_tool() -> None:
            async with Client(secure_server.mcp) as client:
                await client.call_tool("add_weigh_in", {"weight_kg": 70.0})

        with self.assertRaises(Exception) as caught:
            asyncio.run(call_disabled_tool())
        self.assertIn("Unknown tool", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
