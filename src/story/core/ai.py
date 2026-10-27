"""呼叫 Gemini：建立 client、送出請求、串流時先取出劇情、記下每次呼叫的時間與 token 用量。

每種玩法呼叫 AI 的類別都繼承 AICaller（冒險的 Engine、海龜湯的 SoupJudge），用 generate()、stream() 呼叫 AI；
這裡不知道遊戲規則與提示詞的內容。
"""

import json
import re
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from story.core.prompts import UI  # 給玩家看的錯誤訊息（story/core/ui/語言/core.md）

MODEL = "gemini-3.5-flash-lite"
REQUEST_TIMEOUT = 40  # 一次 AI 請求最多等幾秒；Gemini 偶爾卡住一兩分鐘，重送通常比較快
REQUEST_ATTEMPTS = 3  # 逾時或伺服器忙（429、5xx）時最多送幾次（含第一次）
LOG_PATH = Path("story_log.jsonl")  # 每回合的狀態變化紀錄


def new_client(api_key: str | None) -> genai.Client:
    """逾時或伺服器忙時自動重送（間隔約 1、2 秒），不讓玩家一直等一個卡住的請求。"""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT * 1000,  # 毫秒
            retry_options=types.HttpRetryOptions(attempts=REQUEST_ATTEMPTS),
        ),
    )


def is_key_error(e: Exception) -> bool:
    """判斷 Gemini 的錯誤是不是 API key 無效或沒有權限造成的。"""
    code = getattr(e, "code", None)
    text = str(e)
    return code in (400, 401, 403) and ("API key" in text or "API_KEY" in text)


def raise_friendly(e: Exception) -> None:
    """重送幾次都逾時或連不上：轉成核心會處理的錯誤；其他錯誤照原樣丟出。"""
    if isinstance(e, (httpx.TimeoutException, httpx.ConnectError)):
        raise RuntimeError(UI["timeout"]) from e
    raise e


class StopStream(Exception):
    """串流時發現不用再收下去（例如冒險的 AI 太早宣告結局）：從 stream() 的 on_text 丟出，中斷並往外丟。"""

    reason = "stopped"  # 寫進紀錄的中斷原因


def partial_string(text: str, key: str) -> str | None:
    """從還沒生成完的 JSON 取出某個字串欄位目前收到的內容（例如串流中的 narration）。還沒出現時回傳 None。"""
    match = re.search(r'"%s"\s*:\s*"' % re.escape(key), text)
    if not match:
        return None
    out, i = [], match.end()
    while i < len(text) and text[i] != '"':
        if text[i] != "\\":
            out.append(text[i])
            i += 1
            continue
        if i + 1 >= len(text) or (text[i + 1] == "u" and i + 6 > len(text)):
            break  # 跳脫字元還沒收完整，等下一段
        escaped = text[i + 1]
        if escaped == "u":
            out.append(chr(int(text[i + 2 : i + 6], 16)))
            i += 6
        else:
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(escaped, escaped))
            i += 2
    return "".join(out)


def partial_bool(text: str, key: str) -> bool | None:
    """從還沒生成完的 JSON 取出布林欄位；還沒出現時回傳 None。"""
    match = re.search(r'"%s"\s*:\s*(true|false)' % re.escape(key), text)
    return None if match is None else match.group(1) == "true"


class AICaller:
    """所有 AI 呼叫都經過這裡：記下種類、花了幾秒與 Gemini 回報的 token 用量（送出、命中快取、輸出、思考），
    寫進每回合的紀錄，方便查等待時間花在哪裡。"""

    def __init__(self, api_key: str | None, client, log_path: Path):
        self.client = client or new_client(api_key)
        self.log_path = log_path  # 網頁版每一隊各自一份紀錄
        self.calls: list[dict] = []  # 上次寫紀錄之後的 AI 呼叫（寫進紀錄後清空）
        self.draft = ""  # AI 正在寫的劇情（串流中目前收到的部分），外殼可以先顯示；沒有在寫時是空字串

    def set_api_key(self, api_key: str) -> None:
        self.client = new_client(api_key)

    def generate(self, kind: str, **request):
        """一次拿完整結果的呼叫。"""
        started = time.monotonic()
        try:
            response = self.client.models.generate_content(**request)
        except Exception as e:  # 重送幾次都失敗：失敗的呼叫也記下來，跟下一回合的紀錄寫在一起
            self.record(kind, started, None, error=str(e)[:200])
            raise_friendly(e)
        self.record(kind, started, response)
        return response

    def stream(self, kind: str, on_text, **request):
        """串流的呼叫：每收到一段，就用目前為止的全文呼叫 on_text。回傳 (全文, 最後一段)。on_text 丟出 StopStream 時中斷並往外丟。"""
        started, text, last, extra = time.monotonic(), "", None, {}
        chunks = None
        try:
            chunks = self.client.models.generate_content_stream(**request)
            for chunk in chunks:
                last = chunk
                if piece := chunk.text:
                    text += piece
                    on_text(text)
        except StopStream as e:
            extra["stopped"] = e.reason
            raise
        except Exception as e:
            extra["error"] = str(e)[:200]
            raise_friendly(e)
        finally:
            if chunks is not None and hasattr(chunks, "close"):
                chunks.close()  # 中斷時不再接收剩下的部分
            self.record(kind, started, last, **extra)
        return text, last

    def record(self, kind: str, started: float, response, **extra) -> None:
        call = {"kind": kind, "seconds": round(time.monotonic() - started, 2)}
        usage = getattr(response, "usage_metadata", None)
        for field, name in (
            ("prompt_token_count", "prompt"),
            ("cached_content_token_count", "cached"),
            ("candidates_token_count", "output"),
            ("thoughts_token_count", "thinking"),
        ):
            if (value := getattr(usage, field, None)) is not None:
                call[name] = value
        self.calls.append(call | extra)

    def write_log(self, record: dict) -> None:
        """寫一行紀錄，附上這段期間的 AI 呼叫。"""
        record["calls"], self.calls = self.calls, []
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 紀錄寫不進去不影響遊戲
