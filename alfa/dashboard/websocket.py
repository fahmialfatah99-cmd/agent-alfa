"""WebSocket manager and real-time streaming endpoints for ALFA Dashboard."""

import asyncio
import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from alfa.dashboard.common import DASHBOARD_AUTH_TOKEN, logger

websocket_router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket client connections and message broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.channel_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: Optional[str] = None):
        await websocket.accept()
        self.active_connections.add(websocket)
        if channel:
            if channel not in self.channel_subscribers:
                self.channel_subscribers[channel] = set()
            self.channel_subscribers[channel].add(websocket)

    def disconnect(self, websocket: WebSocket, channel: Optional[str] = None):
        self.active_connections.discard(websocket)
        if channel and channel in self.channel_subscribers:
            self.channel_subscribers[channel].discard(websocket)
        for ch, conns in list(self.channel_subscribers.items()):
            conns.discard(websocket)

    async def send_personal_message(self, message: Any, websocket: WebSocket):
        try:
            if isinstance(message, (dict, list)):
                await websocket.send_text(json.dumps(message))
            else:
                await websocket.send_text(str(message))
        except Exception as e:
            logger.debug(f"Failed to send personal websocket message: {e}")

    async def broadcast(self, message: Any, channel: Optional[str] = None):
        target_connections = (
            list(self.channel_subscribers.get(channel, set()))
            if channel
            else list(self.active_connections)
        )
        payload = json.dumps(message) if isinstance(message, (dict, list)) else str(message)
        for connection in target_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                self.disconnect(connection, channel)


ws_manager = ConnectionManager()


def _is_ws_authorized(websocket: WebSocket) -> bool:
    """Verify WebSocket token if DASHBOARD_AUTH_TOKEN is configured."""
    if not DASHBOARD_AUTH_TOKEN:
        return True
    token = websocket.query_params.get("token") or websocket.headers.get("X-Session-Token")
    if token == DASHBOARD_AUTH_TOKEN:
        return True
    from alfa.dashboard.routes.auth import validate_session
    if token and validate_session(token):
        return True
    cookie_token = websocket.cookies.get("session_token")
    if cookie_token and validate_session(cookie_token):
        return True
    return False


@websocket_router.websocket("/ws/terminal")
async def ws_terminal_endpoint(websocket: WebSocket):
    """Interactive command-line execution and streaming terminal."""
    if not _is_ws_authorized(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await ws_manager.connect(websocket, channel="terminal")
    await ws_manager.send_personal_message({
        "type": "output",
        "data": "ALFA Sovereign Terminal Session Connected\r\n"
    }, websocket)

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
                command = msg.get("command", "").strip()
            except Exception:
                command = raw_data.strip()

            if not command:
                continue

            if command == "ping":
                await ws_manager.send_personal_message({"type": "pong"}, websocket)
                continue

            # Execute bash command asynchronously and stream stdout/stderr
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT
                )
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    await ws_manager.send_personal_message({
                        "type": "output",
                        "data": line.decode("utf-8", errors="replace")
                    }, websocket)
                await proc.wait()
                await ws_manager.send_personal_message({
                    "type": "exit",
                    "code": proc.returncode
                }, websocket)
            except Exception as e:
                await ws_manager.send_personal_message({
                    "type": "error",
                    "data": f"Execution error: {str(e)}\r\n"
                }, websocket)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel="terminal")
    except Exception as e:
        logger.debug(f"Terminal websocket error: {e}")
        ws_manager.disconnect(websocket, channel="terminal")


@websocket_router.websocket("/ws/logs")
async def ws_logs_endpoint(websocket: WebSocket):
    """Live system log streaming over WebSocket."""
    if not _is_ws_authorized(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await ws_manager.connect(websocket, channel="logs")
    unit = websocket.query_params.get("unit", "telegram-ai-bot.service")

    try:
        # Stream recent logs and follow
        cmd = ["journalctl", "--user", "-u", unit, "-n", "50", "-f", "--no-pager"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await ws_manager.send_personal_message({
                    "type": "log",
                    "unit": unit,
                    "data": line.decode("utf-8", errors="replace")
                }, websocket)
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel="logs")
    except Exception as e:
        logger.debug(f"Logs websocket error: {e}")
        ws_manager.disconnect(websocket, channel="logs")


@websocket_router.websocket("/ws/broadcast")
async def ws_broadcast_endpoint(websocket: WebSocket):
    """General telemetry & swarm event broadcast channel."""
    if not _is_ws_authorized(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await ws_manager.connect(websocket, channel="broadcast")
    try:
        while True:
            # Keepalive listener
            data = await websocket.receive_text()
            if data == "ping":
                await ws_manager.send_personal_message({"type": "pong"}, websocket)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel="broadcast")
    except Exception as e:
        logger.debug(f"Broadcast websocket error: {e}")
        ws_manager.disconnect(websocket, channel="broadcast")
