"""WS 连接管理与事件广播（design §12：GET /ws，认证后升级）。

M3 事件：message_delta / message_done / error。
M4/M5 增加 task_update、step_new、confirm_request 等事件类型。
"""

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.auth.session import COOKIE_NAME, read_session_token


class ConnectionManager:
    def __init__(self) -> None:
        # session_uuid → 该会话的活动连接集合
        self._conns: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_uuid: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.setdefault(session_uuid, set()).add(ws)

    async def disconnect(self, session_uuid: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._conns.get(session_uuid)
            if conns is not None:
                conns.discard(ws)
                if not conns:
                    self._conns.pop(session_uuid, None)

    async def broadcast(self, session_uuid: str, event: dict[str, Any]) -> None:
        async with self._lock:
            conns = list(self._conns.get(session_uuid, ()))
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 —— 断线连接清理即可
                dead.append(ws)
        for ws in dead:
            await self.disconnect(session_uuid, ws)


manager = ConnectionManager()


async def ws_endpoint(websocket: WebSocket) -> None:
    """GET /ws?session={uuid}：cookie 认证 + 会话过滤。"""
    settings = websocket.app.state.settings
    token = websocket.cookies.get(COOKIE_NAME)
    username = read_session_token(settings.secret, token) if token else None
    if username is None:
        await websocket.close(code=4401, reason="未登录")
        return

    session_uuid = websocket.query_params.get("session")
    if not session_uuid:
        await websocket.close(code=4400, reason="缺少 session 参数")
        return

    await manager.connect(session_uuid, websocket)
    try:
        while True:
            # M3 客户端只发 ping；task_stop/task_reply 是 M4/M5 的事
            msg = await websocket.receive_json()
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(session_uuid, websocket)
