"""網頁殼：用 textual-serve 把終端機版原封不動地放進瀏覽器。

每開一個分頁，伺服器就在背景啟動一個網頁模式（--web）的終端機版遊戲，畫面透過網頁上的終端機模擬器顯示。
遊戲本身只有一份（textual/），這裡不寫任何介面或遊戲邏輯。

加上 --party 是線上多人：伺服器裡開一個房間（room.py），每個分頁的遊戲都連到這個房間，大家一起玩同一局，
呼叫 AI 用伺服器的 API key。
"""

import argparse
import shlex
import sys
import tempfile
from pathlib import Path

from aiohttp import web
from textual_serve.server import Server

from story.shells.apikey import get_saved_api_key
from story.shells.room import Room

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8080  # 預設只接受本機連線
MAX_SESSIONS = 10  # 同時在線的人數上限；每個人會佔用一個遊戲程序
TEMPLATES = Path(__file__).parent / "web_templates"  # 加上手機支援的網頁模板


class LimitedServer(Server):
    """限制同時在線人數的 textual-serve 伺服器，避免太多人同時連線把主機資源用光。"""

    sessions = 0

    def __init__(self, *args, public_url: str | None = None, room: Room | None = None, room_path: str = "", **kwargs) -> None:
        kwargs.setdefault("templates_path", TEMPLATES)
        super().__init__(*args, public_url=public_url, **kwargs)
        self.fixed_public_url = public_url
        self.room, self.room_path = room, room_path  # 線上多人：跟著伺服器一起啟動與關閉的房間

    async def _make_app(self) -> web.Application:
        app = await super()._make_app()
        if self.room:
            app.on_startup.append(lambda _: self.room.start(self.room_path))
            app.on_cleanup.append(lambda _: self.room.stop())
        return app

    async def handle_index(self, request: web.Request) -> web.StreamResponse:
        # textual-serve 預設把頁面裡的 JS 與 websocket 網址寫死成啟動時的 host:port，
        # 用 0.0.0.0、WSL 的 IP 或其他電腦連進來時會載不到，畫面只停在「Story」。
        # 沒指定 --public-url 時，改用瀏覽器實際連進來的網址。
        if self.fixed_public_url is None:
            self.public_url = f"{request.scheme}://{request.host}"
        return await super().handle_index(request)

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        if LimitedServer.sessions >= MAX_SESSIONS:
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            message = f"\r\n  目前在線人數已滿（{MAX_SESSIONS} 人），請稍後再試。\r\n"
            await websocket.send_bytes(message.encode())
            await websocket.close()
            return websocket
        LimitedServer.sessions += 1
        try:
            return await super().handle_websocket(request)
        finally:
            LimitedServer.sessions -= 1


def game_command(room_path: str = "") -> str:
    """每個連線要啟動的遊戲：同一個 Python 執行網頁模式的終端機版；線上多人時連到房間。"""
    command = f"{shlex.quote(sys.executable)} -m story --web"
    return f"{command} --room {shlex.quote(room_path)}" if room_path else command


def main() -> None:
    parser = argparse.ArgumentParser(description="在瀏覽器裡玩 Story")
    parser.add_argument("--host", default=DEFAULT_HOST, help="監聽位址；0.0.0.0 代表開放其他電腦連線（預設只有本機）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--public-url", help="從外部連進來的網址（例如經過反向代理時），預設依 host 與 port 推算")
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
    LimitedServer(
        game_command(room_path), host=args.host, port=args.port, title="Story",
        public_url=args.public_url, room=room, room_path=room_path,
    ).serve()
