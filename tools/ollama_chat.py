"""A small terminal chat for trying out local models in Ollama: the answer streams in, and the conversation is remembered until /clear.

    uv run python tools/ollama_chat.py
    uv run python tools/ollama_chat.py --model <name> --system "你是說書人" --ollama http://localhost:11434

While chatting: /system <text> sets the system prompt (empty clears it), /model lists or switches models, /clear forgets the conversation,
/once switches one-shot mode on or off (each message is sent on its own, nothing earlier is remembered; also --once), /quit (or Ctrl+D) leaves. Ctrl+C during an answer stops it.

Inkling models get their prompt written by hand and sent raw, like story/core/ollama.py (their chat template stops Ollama before the first word);
other models go through Ollama's normal chat. Standalone: doesn't import the game, only httpx.
"""

import argparse
import json
import time

import httpx

try:
    import readline  # noqa: F401  Arrow keys and history in input()
except ImportError:
    pass

TIMEOUT = httpx.Timeout(connect=10, read=300, write=30, pool=None)
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
INKLING_ROLES = {"system": "system", "user": "user", "assistant": "model"}


def inkling_prompt(system: str, messages: list[dict]) -> str:
    """The whole conversation in Inkling's own format, ending where the model starts its answer, with thinking off (as in story/core/ollama.py)."""

    def message(role: str, text: str) -> str:
        end = "<|content_model_end_sampling|>" if role == "model" else ""
        return f"<|message_{role}|><|content_text|>{text.replace('<|', '<')}<|end_message|>{end}"

    head = message("system", system) if system.strip() else ""
    body = "".join(message(INKLING_ROLES.get(m["role"], "user"), m["content"]) for m in messages)
    return head + message("system", "Thinking effort level: 0") + body + "<|message_model|><|content_text|>"


class Chat:
    def __init__(self, url: str, model: str, system: str, num_ctx: int, once: bool = False):
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=TIMEOUT)
        self.system, self.num_ctx = system, num_ctx
        self.once = once  # One-shot mode: each message is sent alone (with the system prompt), and nothing is kept
        self.messages: list[dict] = []
        self.model = model or self.models()[0]

    def models(self) -> list[str]:
        names = [m["name"] for m in self.http.get("/api/tags").json().get("models", [])]
        if not names:
            raise SystemExit("Ollama has no models (ollama pull <name> first).")
        return names

    def inkling(self) -> bool:
        response = self.http.post("/api/show", json={"model": self.model})
        return response.is_success and response.json().get("details", {}).get("family", "").startswith("inkling")

    def ask(self, text: str) -> None:
        """Send one message and print the answer as it streams in. In one-shot mode, only this message is sent and neither it nor the answer is kept."""
        sent = [{"role": "user", "content": text}]
        if not self.once:
            self.messages += sent
            sent = self.messages
        body: dict = {"model": self.model, "stream": True, "options": {"num_ctx": self.num_ctx}}
        if self.inkling():
            path, body["raw"], body["prompt"] = "/api/generate", True, inkling_prompt(self.system, sent)
        else:
            path = "/api/chat"
            body["messages"] = ([{"role": "system", "content": self.system}] if self.system.strip() else []) + sent
        answer, stats, started = "", {}, time.monotonic()
        try:
            with self.http.stream("POST", path, json=body) as response:
                if not response.is_success:
                    response.read()
                    raise RuntimeError(f"Ollama {response.status_code}: {response.text}")
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if error := chunk.get("error"):
                        raise RuntimeError(error)
                    if piece := chunk.get("response") or (chunk.get("message") or {}).get("content"):
                        if not answer:
                            print("\b \b", end="")  # Erase the waiting mark
                        answer += piece
                        print(piece, end="", flush=True)
                    if chunk.get("done"):
                        stats = chunk
        except KeyboardInterrupt:
            print(f"\n{DIM}(stopped){RESET}", end="")
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"\nError: {e}", end="")
        if not self.once:
            self.messages.append({"role": "assistant", "content": answer})
        seconds = time.monotonic() - started
        info = f"{seconds:.1f} s"
        if stats:
            rate = stats["eval_count"] / (stats["eval_duration"] / 1e9) if stats.get("eval_duration") else 0
            info += f" · prompt {stats.get('prompt_eval_count', '?')} tokens · answer {stats.get('eval_count', '?')} tokens · {rate:.1f} tokens/s"
        print(f"\n{DIM}{info}{RESET}\n")

    def command(self, line: str) -> bool:
        """Run a /command; False to quit."""
        name, _, arg = line.partition(" ")
        if name in ("/quit", "/exit"):
            return False
        if name == "/clear":
            self.messages = []
            print(f"{DIM}Conversation cleared.{RESET}\n")
        elif name == "/once":
            self.once, self.messages = not self.once, []
            state = "on: each message is sent on its own" if self.once else "off: the conversation is remembered again"
            print(f"{DIM}One-shot mode {state} (conversation cleared).{RESET}\n")
        elif name == "/system":
            self.system = arg.strip()
            print(f"{DIM}System prompt {'set' if self.system else 'cleared'}.{RESET}\n")
        elif name == "/model":
            names = self.models()
            if arg.strip():
                choice = names[int(arg) - 1] if arg.strip().isdigit() and 1 <= int(arg) <= len(names) else arg.strip()
                self.model, self.messages = choice, []
                print(f"{DIM}Now using {self.model} (conversation cleared).{RESET}\n")
            else:
                for i, n in enumerate(names, 1):
                    print(f"  {i}. {n}{'  ←' if n == self.model else ''}")
                print(f"{DIM}/model <number or name> to switch.{RESET}\n")
        else:
            print(f"{DIM}Commands: /system <text>, /model [n], /clear, /once, /quit{RESET}\n")
        return True

    def run(self) -> None:
        print(f"{BOLD}{self.model}{RESET}  {DIM}(/system, /model, /clear, /once, /quit; Ctrl+C stops an answer){RESET}")
        print(f"{DIM}One-shot mode: each message is sent on its own.{RESET}\n" if self.once else "")
        while True:
            try:
                line = input(f"{BOLD}{'once> ' if self.once else '> '}{RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            if line.startswith("/"):
                if not self.command(line):
                    return
                continue
            print(f"{DIM}…{RESET}", end="", flush=True)
            self.ask(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="A small terminal chat for trying out local models in Ollama")
    parser.add_argument("--model", default="", help="Model name (default: the first in ollama list)")
    parser.add_argument("--system", default="", help="System prompt")
    parser.add_argument("--ollama", default="http://localhost:11434", help="Ollama's address")
    parser.add_argument("--once", action="store_true", help="One-shot mode: each message is sent on its own, nothing earlier is remembered")
    parser.add_argument("--num-ctx", type=int, default=16384, help="Context length in tokens")
    args = parser.parse_args()
    try:
        Chat(args.ollama, args.model, args.system, args.num_ctx, args.once).run()
    except httpx.ConnectError:
        raise SystemExit(f"Can't reach Ollama at {args.ollama}.") from None


if __name__ == "__main__":
    main()
