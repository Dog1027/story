"""網頁版的玩家與伺服器（大廳、房間）之間的連線：一對 Connection，訊息直接在記憶體裡傳。

大廳、房間和所有瀏覽器分頁的共用層都在網頁伺服器這個程式裡，所以不需要網路連線；
每則訊息都轉成 JSON 再轉回來，兩端不共用物件，訊息格式就是唯一的約定。
"""

import asyncio
import json


class Connection:
    """玩家與伺服器之間連線的一端：send() 的訊息由另一端的 receive() 收到。
    任一端 close() 之後，另一端的 receive() 回傳 None，再 send() 會丟出 ConnectionError。"""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue):
        self.inbox, self.outbox = inbox, outbox
        self.peer: Connection | None = None
        self.closed = False

    @staticmethod
    def pair() -> tuple["Connection", "Connection"]:
        a, b = asyncio.Queue(), asyncio.Queue()
        one, other = Connection(a, b), Connection(b, a)
        one.peer, other.peer = other, one
        return one, other

    @property
    def open(self) -> bool:
        """兩端都還沒 close()。"""
        return not self.closed and not self.peer.closed

    async def send(self, message: dict) -> None:
        if not self.open:
            raise ConnectionError("connection closed")
        # 轉成 JSON 再轉回來：兩端不會共用同一個物件，收到的只有 JSON 的型別（tuple 變成 list），訊息格式才是唯一的約定
        self.outbox.put_nowait(json.loads(json.dumps(message, ensure_ascii=False)))

    async def receive(self) -> dict | None:
        """收下一則訊息；連線結束時回傳 None。"""
        if self.closed:
            return None
        return await self.inbox.get()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.outbox.put_nowait(None)  # 讓另一端的 receive() 結束
            self.inbox.put_nowait(None)  # 自己這端還在等的 receive() 也結束
