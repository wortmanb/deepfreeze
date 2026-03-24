"""Async HTTP client for the TUI, wrapping httpx for REST and SSE."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger("deepfreeze.tui.client")


class TuiClient:
    """Async HTTP client for the TUI to talk to deepfreeze-server.

    Provides async methods matching the DeepfreezeService interface so the
    TUI app can swap between local and remote with minimal changes.
    """

    def __init__(
        self,
        server_url: str,
        api_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = server_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- Status --

    async def get_status(self, force_refresh: bool = False) -> dict[str, Any]:
        r = await self._client.get("/api/status", params={"force_refresh": force_refresh})
        r.raise_for_status()
        return r.json()

    async def get_action_history(self, limit: int = 50) -> list[dict]:
        r = await self._client.get("/api/history", params={"limit": limit})
        r.raise_for_status()
        return r.json().get("history", [])

    async def get_thaw_restore_progress(self, request_id: str) -> list[dict]:
        r = await self._client.get(f"/api/thaw-requests/{request_id}/restore-progress")
        r.raise_for_status()
        return r.json().get("repos", [])

    # -- Actions (wait=true for synchronous result) --

    async def rotate(self, **kwargs) -> dict[str, Any]:
        return await self._post_action("/api/actions/rotate", kwargs)

    async def thaw_create(self, **kwargs) -> dict[str, Any]:
        return await self._post_action("/api/actions/thaw", kwargs)

    async def thaw_check(self, request_id: str | None = None) -> dict[str, Any]:
        return await self._post_action("/api/actions/thaw/check", {"request_id": request_id})

    async def refreeze(self, request_id: str | None = None, **kwargs) -> dict[str, Any]:
        return await self._post_action("/api/actions/refreeze", {"request_id": request_id, **kwargs})

    async def cleanup(self, **kwargs) -> dict[str, Any]:
        return await self._post_action("/api/actions/cleanup", kwargs)

    async def repair_metadata(self, **kwargs) -> dict[str, Any]:
        return await self._post_action("/api/actions/repair", kwargs)

    # -- SSE --

    async def subscribe_events(self, channel: str | None = None) -> AsyncIterator[dict]:
        """Subscribe to SSE events from the server.

        Yields parsed event dicts: {"event": "...", "data": {...}}
        Reconnects automatically on disconnect.
        """
        params = {}
        if channel:
            params["channel"] = channel
        url = f"{self.base_url}/api/events"

        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as sse_client:
                    # Copy auth headers
                    headers = dict(self._client.headers)
                    async with sse_client.stream("GET", url, params=params, headers=headers) as response:
                        event_type = ""
                        data_buf = ""
                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                data_buf = line[5:].strip()
                            elif line == "" and data_buf:
                                # End of event
                                try:
                                    parsed = json.loads(data_buf)
                                except (json.JSONDecodeError, ValueError):
                                    parsed = {"raw": data_buf}
                                yield {"event": event_type, "data": parsed}
                                event_type = ""
                                data_buf = ""
            except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
                logger.warning("SSE disconnected: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                return

    # -- Internal --

    async def _post_action(self, path: str, body: dict) -> dict[str, Any]:
        r = await self._client.post(path, json=body, params={"wait": "true", "timeout": "120"})
        r.raise_for_status()
        return r.json()
