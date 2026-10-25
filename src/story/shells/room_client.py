"""網頁版的共用層：每個瀏覽器分頁一個 RoomClient，連進網頁伺服器的大廳（lobby.py），在房間（room.py）裡玩。

沒有自己的核心：輸入送到房間，回覆、進度、正在寫的劇情由房間推回來，畫面照常用 Client.handle() 顯示。
"""

import asyncio

from story.core import Reply, pick_choice
from story.shells.client import UI, Client, View
from story.shells.connection import Connection
from story.shells.lobby import Lobby


class RoomClient(Client):
    def __init__(self, view: View, lobby: Lobby):
        super().__init__(view)
        self.lobby = lobby
        self.room: Connection | None = None  # 和大廳（與房間）的連線
        self.my_name = ""
        self.waiting: list[str] = []  # 這回合還沒行動的人
        self.room_progress = ""  # 房間推來的進度
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()  # 房間推來、要依序處理的訊息
        self.premise_answer: asyncio.Future | None = None  # 前提對話框在等房間回覆

    # ---------- Client 的掛勾 ----------

    @property
    def connected(self) -> bool:
        return self.room is not None

    async def run(self) -> None:
        self.room = self.lobby.connect()
        name = await self.ask_name(self.claim_seat)
        if name is None:
            self.view.exit()
            return
        self.my_name = name
        inbox = asyncio.create_task(self.process_inbox())
        try:
            await self.listen()
        finally:
            inbox.cancel()

    async def deliver(self, text: str) -> None:
        await self.room.send({"type": "send", "text": text})  # 回覆會由房間推回來

    async def deliver_quietly(self, text: str) -> None:
        await self.room.send({"type": "send", "text": text})

    def premise_asker(self):
        loop = asyncio.get_running_loop()

        def ask(*commands: str) -> Reply:  # 請房間代問後等結果
            return asyncio.run_coroutine_threadsafe(self.ask_room(list(commands)), loop).result()

        return ask

    def echo_for(self, text: str) -> str:
        """還沒行動時，照畫面上的選項對應；房間的時間到、指令不顯示。"""
        if not self.actor or text.startswith("/"):
            return ""
        return pick_choice(text, self.choices) or text

    def progress(self) -> str:
        return self.room_progress

    async def narration_read(self, reply: Reply) -> None:
        await self.room.send({"type": "ready"})  # 大家都看完，房間才開始倒數

    def close(self) -> None:
        if self.room:
            self.room.close()

    def refresh_hint(self) -> None:
        """行動的進度放在輸入框的提示，不用會蓋住劇情的通知：自己行動完了提示還在等誰，還沒行動時提示誰已經行動了。"""
        team = [s.name for s in self.shown[1] if s.alive]  # 狀態列上的隊伍
        acted = [n for n in team if n not in self.waiting and n != self.my_name] if self.waiting else []
        if not self.actor and self.waiting:
            self.view.set_hint(UI["hint_waiting"].format(names=UI["list_sep"].join(self.waiting)))
        elif self.actor and acted:
            self.view.set_hint(UI["hint_others_acted"].format(names=UI["list_sep"].join(acted)))
        else:
            super().refresh_hint()

    # ---------- 和大廳、房間對話 ----------

    async def claim_seat(self, name: str) -> str:
        await self.room.send({"type": "join", "name": name})
        answer = await self.room.receive()
        if answer is None:
            return UI["room_lost"]
        return answer.get("reason", "") if answer["type"] == "rejected" else ""

    async def listen(self) -> None:
        """收房間推來的訊息。簡單的直接處理；回覆、大廳等要等前一個顯示完的，排進 inbox 依序處理。"""
        while (message := await self.room.receive()) is not None:
            kind = message["type"]
            if kind == "busy":
                self.room_progress = message.get("progress", "")
                self.set_busy(message["on"])
                if message["on"]:
                    self.view.show_busy()
            elif kind == "draft":  # 房間轉來的 AI 正在寫的劇情
                self.follow_draft(message["text"])
            elif kind == "timer":
                self.view.start_timer(message["seconds"])
            elif kind == "waiting":
                self.update_waiting(message["names"])
            elif kind == "notice":
                self.view.notify(message["text"])
            elif kind == "new_story":  # 立刻清空，不排隊：緊接著的「故事生成中」才不會被一起清掉
                self.clear_story(message.get("premise", ""))
            elif kind == "premise" and self.premise_answer:
                self.premise_answer.set_result(Reply.from_dict(message["reply"]))
            else:
                self.inbox.put_nowait(message)
        self.set_busy(False)
        self.view.notify(UI["room_disconnected"], error=True, lasting=True)

    def update_waiting(self, names: list[str]) -> None:
        """這回合還沒行動的人變了：更新提示（不重建選項，畫面才不會閃）。"""
        self.waiting = names
        self.refresh_hint()

    async def process_inbox(self) -> None:
        while True:
            message = await self.inbox.get()
            kind = message["type"]
            if kind == "reply":
                await self.handle(Reply.from_dict(message["reply"]))
            elif kind == "lobby":
                self.show_lobby(message)

    async def ask_room(self, commands: list[str]) -> Reply:
        """依序送出指令，只有最後一個要求房間回覆（answer），收到的一定是這一個的結果。"""
        self.premise_answer = asyncio.get_running_loop().create_future()
        for i, command in enumerate(commands):
            await self.room.send({"type": "send", "text": command, "answer": i == len(commands) - 1})
        try:
            return await self.premise_answer
        finally:
            self.premise_answer = None

    def show_lobby(self, screen: dict) -> None:
        """大廳或房間的等人畫面（內容由大廳、房間決定）。剛進來或剛離開房間時先清空畫面。"""
        if screen.get("clear"):
            self.clear_story()
        self.view.show_lobby({k: v for k, v in screen.items() if k not in ("type", "clear", "hint")})
        self.actor, self.waiting = "", []
        self.choices = list(screen["choices"])  # 輸入框打編號也能選；按鈕由介面畫在大廳的畫面裡，下方的選項區不用再列一次
        self.view.show_choices([])
        self.view.set_hint(screen["hint"])

