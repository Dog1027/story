"""The web version: open it in a browser and play, with the same page on phones and computers.

The server (aiohttp) creates a shared-layer Client for each browser tab, with WebView (view.py) as its interface:
each call from the shared layer becomes a JSON message sent over a WebSocket to the browser, and the browser (static/) only draws it.
The flow is all in the shared layer (screen/client.py).

The server has one lobby (rooms/lobby.py), set up in hosting.py with every game in GAMES: each tab's Client connects to it, enters a name, then opens a room or joins someone else's;
each room plays its own game (playing alone is a room with just you). The AI is called with the host's Gemini API key (config or environment variable); players never enter one.
"""

import argparse
import asyncio
import html
import json
import logging
import re
import sys
from pathlib import Path

from aiohttp import WSMsgType, web

from story import settings
from story.core import MAX_PLAYERS
from story.shells.rooms.lobby import MAX_ROOMS, Lobby
from story.shells.screen.client import Client
from story.shells.text import ui_text
from story.shells.web.hosting import make_lobby
from story.shells.web.view import WebView

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8080  # By default only accept connections from this computer
UI = ui_text("shells")  # story/shells/ui/<lang>/shells.md
MAX_SESSIONS = MAX_ROOMS * MAX_PLAYERS  # Most people online at once: every room full, so too many connections can't exhaust the host
STATIC = Path(__file__).parent / "static"


def render_page() -> str:
    """index.html with this language's text: a key in double braces becomes that text from web.md or dialogs.md, and the texts placeholder the whole string table (for app.js)."""
    texts = ui_text("dialogs") | ui_text("web")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = page.replace("{{texts}}", json.dumps(texts, ensure_ascii=False).replace("</", "<\\/"))
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda m: html.escape(texts[m.group(1)]), page)


PAGE = render_page()


def make_app(lobby: Lobby) -> web.Application:
    """Build the web server: every tab connects to lobby. The lobby closes with the server."""
    app = web.Application()
    sessions = 0  # Tabs online now

    async def index(request: web.Request) -> web.Response:
        return web.Response(text=PAGE, content_type="text/html")

    async def no_stale_files(request: web.Request, response: web.StreamResponse) -> None:
        # The page, JS and CSS always ask the server for updates first (no download if unchanged).
        # Otherwise the browser may keep a cached old app.js that doesn't match the updated server, and the story and choices never appear
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
        client = Client(view, lobby.connect, token=request.query.get("token", "")[:64])
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

    # Unexpected errors go to the output (server.log under just start) with the full traceback, to find out what happened
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.host != "127.0.0.1":
        print(UI["server_open_warning"], flush=True)
    print(UI["server_started"].format(host=args.host, port=args.port), flush=True)
    web.run_app(make_app(make_lobby(key)), host=args.host, port=args.port, print=None)
