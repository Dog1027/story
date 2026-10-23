"""網頁版：瀏覽器打開就能玩，手機和電腦用同一個頁面。

伺服器（aiohttp）對每個瀏覽器分頁建立一個共用層的 Client，介面是 WebView（view.py）：
共用層的每個呼叫變成一則 JSON 訊息，經由 WebSocket 送到瀏覽器，瀏覽器（static/）只負責畫出來。
流程都在共用層，跟終端機版是同一份。

沒加 --party：每個人各自玩，先輸入名字（每個名字有自己的存檔）與自己的 Gemini API key。
加上 --party：線上多人，伺服器裡開一個房間（room.py），大家一起玩同一局，呼叫 AI 用伺服器的 API key。
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from aiohttp import WSMsgType, web

from story.shells.apikey import get_saved_api_key
from story.shells.client import Client
from story.shells.room import Room
from story.shells.web.view import WebView

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8080  # 預設只接受本機連線
MAX_SESSIONS = 10  # 同時在線的人數上限，避免太多人同時連線把主機資源用光
STATIC = Path(__file__).parent / "static"


def make_app(room: Room | None = None, room_path: str = "") -> web.Application:
    """建立網頁伺服器。給了 room 就是線上多人：房間跟著伺服器一起啟動與關閉。"""
    app = web.Application()
    sessions = 0  # 目前在線的分頁數

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        nonlocal sessions
        if sessions >= MAX_SESSIONS:
            await ws.send_json({"t": "fatal", "text": f"目前在線人數已滿（{MAX_SESSIONS} 人），請稍後再試。"})
            await ws.close()
            return ws
        sessions += 1
        view = WebView(ws)
        client = Client(view, web=room is None, room=room_path or None)
        view.client = client
        writer = asyncio.create_task(view.write_loop())
        game = asyncio.create_task(client.run())
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(message.data)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    view.receive(data)
        finally:
            sessions -= 1
            view.close()
            for task in (game, writer):
                task.cancel()
            client.close()
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_static("/static", STATIC)
    if room:
        app.on_startup.append(lambda _: room.start(room_path))
        app.on_cleanup.append(lambda _: room.stop())
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="在瀏覽器裡玩 Story")
    parser.add_argument("--host", default=DEFAULT_HOST, help="監聽位址；0.0.0.0 代表開放其他電腦連線（預設只有本機）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--party", action="store_true", help="線上多人：所有連進來的人一起玩同一局，使用伺服器的 API key")
    args = parser.parse_args()

    room, room_path = None, ""
    if args.party:
        key = get_saved_api_key()
        if not key:
            sys.exit("線上多人使用伺服器的 API key：請先設定環境變數 GEMINI_API_KEY，或執行一次 uv run story 儲存 key。")
        room = Room.for_server(key)
        room_path = str(Path(tempfile.mkdtemp(prefix="story-")) / "room.sock")

    if args.host != "127.0.0.1":
        print("⚠ 已開放其他電腦連線。目前沒有 HTTPS，玩家輸入的 API key 會以明文傳送，只建議在信任的網路使用。", flush=True)
    mode = "線上多人（大家一起玩同一局）" if args.party else "單人（每個人各自玩）"
    print(f"伺服器已啟動：http://{args.host}:{args.port}　模式：{mode}　按 Ctrl+C 結束。", flush=True)
    web.run_app(make_app(room, room_path), host=args.host, port=args.port, print=None)
