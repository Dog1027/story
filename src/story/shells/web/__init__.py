"""網頁版：瀏覽器打開就能玩，手機和電腦用同一個頁面。

伺服器（aiohttp）對每個瀏覽器分頁建立一個共用層的 Client，介面是 WebView（view.py）：
共用層的每個呼叫變成一則 JSON 訊息，經由 WebSocket 送到瀏覽器，瀏覽器（static/）只負責畫出來。
流程都在共用層（client.py）。

伺服器裡有一個大廳（lobby.py）：每個分頁的 Client 都連進大廳，輸入名字後開房間或加入別人的房間，
每個房間各自玩一局（一個人玩就是只有自己的房間）。呼叫 AI 用架站者的 Gemini API key（設定檔或環境變數），玩家不用輸入。
"""

import argparse
import asyncio
import html
import json
import re
import sys
from pathlib import Path

from aiohttp import WSMsgType, web

from story import settings
from story.core import MAX_PLAYERS
from story.shells.client import Client
from story.shells.lobby import MAX_ROOMS, Lobby
from story.shells.text import ui_text
from story.shells.web.view import WebView

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8080  # 預設只接受本機連線
UI = ui_text("shells")  # story/shells/ui/語言/shells.md
MAX_SESSIONS = MAX_ROOMS * MAX_PLAYERS  # 同時在線的人數上限：每個房間都坐滿的人數，避免太多連線把主機資源用光
STATIC = Path(__file__).parent / "static"


def render_page() -> str:
    """index.html 換上這個語言的文字：{{名稱}} 換成 web.md、dialogs.md 的文字，{{texts}} 換成整份字串表（給 app.js）。"""
    texts = ui_text("dialogs") | ui_text("web")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = page.replace("{{texts}}", json.dumps(texts, ensure_ascii=False).replace("</", "<\\/"))
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda m: html.escape(texts[m.group(1)]), page)


PAGE = render_page()


def make_app(lobby: Lobby) -> web.Application:
    """建立網頁伺服器：每個分頁都連進 lobby（大廳）。伺服器關閉時大廳跟著關閉。"""
    app = web.Application()
    sessions = 0  # 目前在線的分頁數

    async def index(request: web.Request) -> web.Response:
        return web.Response(text=PAGE, content_type="text/html")

    async def no_stale_files(request: web.Request, response: web.StreamResponse) -> None:
        # 頁面與 JS、CSS 每次都先問伺服器有沒有更新（沒變就不用重新下載）。
        # 不然瀏覽器可能沿用快取的舊 app.js，跟更新後的伺服器對不上，劇情和選項就出不來
        if not request.path.startswith("/ws"):
            response.headers["Cache-Control"] = "no-cache"

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        nonlocal sessions
        if sessions >= MAX_SESSIONS:
            await ws.send_json({"t": "fatal", "text": UI["server_full"].format(max=MAX_SESSIONS)})
            await ws.close()
            return ws
        sessions += 1
        view = WebView(ws)
        client = Client(view, lobby, token=request.query.get("token", "")[:64])
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

    app.on_response_prepare.append(no_stale_files)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_static("/static", STATIC)
    app.on_cleanup.append(lambda _: lobby.stop())
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=UI["server_description"])
    parser.add_argument("--host", default=DEFAULT_HOST, help=UI["server_host_help"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    key = settings.api_key()
    if not key:
        sys.exit(UI["server_no_key"])

    if args.host != "127.0.0.1":
        print(UI["server_open_warning"], flush=True)
    print(UI["server_started"].format(host=args.host, port=args.port), flush=True)
    web.run_app(make_app(Lobby.for_server(key)), host=args.host, port=args.port, print=None)
