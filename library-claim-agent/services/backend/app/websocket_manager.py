"""
WebSocket connection manager — singleton pattern.
Used by webhooks, agents, and workers to push live updates to the browser.

Design: fire-and-forget broadcasts (asyncio.create_task) so callers never
block on a slow browser connection.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        # sweep_id → WebSocket
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, sweep_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[sweep_id] = websocket
        logger.info(f"WebSocket connected for sweep {sweep_id}")

    def disconnect(self, sweep_id: str) -> None:
        self._connections.pop(sweep_id, None)
        logger.info(f"WebSocket disconnected for sweep {sweep_id}")

    async def broadcast(self, sweep_id: str, data: dict[str, Any]) -> None:
        """
        Send JSON to the browser for this sweep.
        Fire-and-forget: does NOT block the caller.
        If the browser is disconnected, the error is logged and swallowed.
        """
        ws = self._connections.get(sweep_id)
        if ws is None:
            return

        async def _send() -> None:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(data)
            except Exception as exc:
                logger.warning(f"WebSocket send failed [{sweep_id}]: {exc}")
                self.disconnect(sweep_id)

        asyncio.create_task(_send())

    def is_connected(self, sweep_id: str) -> bool:
        return sweep_id in self._connections


# Module-level singleton — imported by webhooks, agents, workers
manager = WebSocketManager()
