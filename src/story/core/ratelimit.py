"""AI 呼叫的次數限制：好幾局遊戲（網頁版的房間、just eval 的情境）共用一把 API key 時，一分鐘內最多呼叫幾次。

Gemini 的免費方案每個模型每分鐘有次數上限（flash-lite 是 15 次）。超過上限的呼叫在這裡排隊，等最早的那次滿一分鐘再送；
沒超過就立刻送，一個人玩的時候不會變慢。還是被 Gemini 擋下（429）時，等它說的秒數再送。
"""

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace

from google.genai import errors

WINDOW = 60  # 秒
RETRIES = 3  # 被 Gemini 擋下（429）時最多再送幾次


class RateLimit:
    """會在背景執行緒被呼叫（核心在背景執行緒呼叫 AI），所以用 threading 的鎖。"""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.sent: deque[float] = deque()  # 最近一分鐘內送出的時間
        self.lock = threading.Lock()

    def wait(self, on_queue: Callable[[bool], None] | None = None) -> None:
        """等到可以送出為止。要排隊時先呼叫 on_queue(True)，輪到時呼叫 on_queue(False)，讓畫面顯示「排隊中」。"""
        queued = False
        while True:
            with self.lock:
                now = time.monotonic()
                while self.sent and now - self.sent[0] >= WINDOW:
                    self.sent.popleft()
                if len(self.sent) < self.per_minute:
                    self.sent.append(now)
                    break
                delay = self.sent[0] + WINDOW - now
            if on_queue and not queued:
                on_queue(True)
            queued = True
            time.sleep(delay)
        if on_queue and queued:
            on_queue(False)

    def call(self, send, on_queue=None):
        for attempt in range(RETRIES + 1):
            self.wait(on_queue)
            try:
                return send()
            except errors.ClientError as e:
                if e.code != 429 or attempt == RETRIES:
                    raise
                delay = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(float(delay.group(1)) if delay else 30)

    def wrap(self, client, on_queue: Callable[[bool], None] | None = None):
        """包住 Gemini client，經過它的呼叫都受次數限制。串流的請求在讀第一段時才送出，所以讀第一段也包進來。"""
        models = client.models

        def stream(**request):
            def first():
                chunks = models.generate_content_stream(**request)
                return chunks, next(chunks, None)

            chunks, head = self.call(first, on_queue)
            if head is not None:
                yield head
                yield from chunks

        return SimpleNamespace(client=client, models=SimpleNamespace(  # client 要留著，被回收時會關掉連線
            generate_content=lambda **request: self.call(lambda: models.generate_content(**request), on_queue),
            generate_content_stream=stream,
        ))
