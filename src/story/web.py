"""網頁殼：用 textual-serve 把終端機版原封不動地放進瀏覽器。

每開一個分頁，伺服器就在背景啟動一個網頁模式（--web）的終端機版遊戲，畫面透過網頁上的終端機模擬器顯示。
遊戲本身只有一份（ui.py），這裡不寫任何介面或遊戲邏輯。
"""

import argparse
import shlex
import sys

from aiohttp import web
from textual_serve.server import Server

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8080  # 預設只接受本機連線
MAX_SESSIONS = 10  # 同時在線的人數上限；每個人會佔用一個遊戲程序


class LimitedServer(Server):
    """限制同時在線人數的 textual-serve 伺服器，避免太多人同時連線把主機資源用光。"""

    sessions = 0

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


def main() -> None:
    parser = argparse.ArgumentParser(description="在瀏覽器裡玩 Story")
    parser.add_argument("--host", default=DEFAULT_HOST, help="監聽位址；0.0.0.0 代表開放其他電腦連線（預設只有本機）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--public-url", help="從外部連進來的網址（例如經過反向代理時），預設依 host 與 port 推算")
    args = parser.parse_args()

    if args.host != "127.0.0.1":
        print("⚠ 已開放其他電腦連線。目前沒有 HTTPS，玩家輸入的 API key 會以明文傳送，只建議在信任的網路使用。", flush=True)
    print(f"伺服器已啟動：http://{args.host}:{args.port}　按 Ctrl+C 結束。", flush=True)
    command = f"{shlex.quote(sys.executable)} -m story --web"
    LimitedServer(command, host=args.host, port=args.port, title="Story", public_url=args.public_url).serve()
