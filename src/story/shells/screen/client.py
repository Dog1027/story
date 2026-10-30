"""The shells' shared layer: the flow of interacting with human players. One Client per browser tab, connected to the lobby and rooms.

Division of labor:
- The core (story.core) and games (story.games): game rules, the AI, saves. Text goes in and a Reply comes out; no sense of time, and no idea a screen exists.
- The lobby and rooms (shells/rooms/): who's in which room; pass each person's input to the core and send replies to everyone in the room.
- This layer (Client): "what to show when". Which dialog to pop up for a reply's phase, showing choices only after the text is typed out,
  starting the countdown once everyone has read, revealing the ending one part at a time…
- The interface (an implementation of View in view.py, WebView on the web): only "what it looks like"; it draws each View method
  and passes the player's input to Client (act, command). The new story dialog's rules are in premise.py.

Put new features in this layer where possible; only new screen elements need a little display code in the interface.
Rule of thumb: changes the game's outcome or facts → the core; changes the order, timing or flow people see → this layer; changes the looks → the interface.
"""

import asyncio
from collections.abc import Callable

from story.core import HOST_PHASES, Ending, InputMode, Reply, Status, pick_choice
from story.shells.connection import Connection
from story.shells.players import MAX_NAME_LEN, InvalidName, check_name
from story.shells.screen.premise import PremiseForm
from story.shells.screen.view import View, status_line
from story.shells.text import UI

MAX_INPUT_LEN = 1000  # Longest input passed on (an action, a question, a premise): it goes into prompts sent on the host's key


class Client:
    """The flow of one browser tab interacting with a human player: connect to the web server's lobby and play in a room (shells/rooms/).
    How a turn appears, how the ending is revealed one part at a time, the status bar, and the input box hint all live here.

    It has no core of its own: input goes to the room; replies, progress and narration being written are pushed back by the room, then handed to View according to the reply's phase."""

    def __init__(self, view: View, connect: Callable[[], Connection] | None, token: str = ""):
        self.view = view
        self.connect = connect  # Opens a connection to the lobby (the web server passes lobby.connect); this side never sees the lobby itself
        self.token = token  # An ID the browser remembers: when the same browser connects again, the new connection replaces the old one (see rooms/lobby.py)
        self.conn: Connection | None = None  # The connection to the lobby (and rooms); None until run() connects
        self.replaced = False
        self.my_name = ""
        self.actor = ""  # Your own name while you haven't acted this turn; empty once you have
        self.choices: list[str] = []
        self.inputs: list[InputMode] = []  # Input modes (turtle soup): when present, choices switch modes, and typed text is sent in the current mode
        self.input_mode = 0  # The mode currently picked (an index into inputs)
        self.draft = ""  # Narration already handed to the interface and still streaming
        self.busy = False
        self.timed = False
        self.shown: tuple[int, list[Status]] = (0, [])  # What the status bar shows now: (turn, each character), redrawn when the mode changes
        self.waiting: list[str] = []  # Who hasn't acted this turn
        self.progress = ""  # Progress pushed by the room (e.g. "planning the story outline")
        self.busy_label = ""  # What the game calls the wait, pushed by the room with it (e.g. "writing the story")
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()  # Messages pushed by the room, handled in order
        self.premise_answer: asyncio.Future | None = None  # The premise dialog is waiting for the room's reply

    @property
    def ready(self) -> bool:
        """Can take the player's input: still connected (sending after a disconnect raises ConnectionError) and not waiting on the AI."""
        return self.conn is not None and self.conn.open and not self.busy

    async def run(self) -> None:
        if self.connect is None:
            raise RuntimeError("Client.run() needs connect (only unit tests that drive the client by hand leave it out)")
        self.conn = self.connect()
        name = await self.ask_name()
        if name is None:
            self.view.exit()
            return
        self.my_name = name
        showing = asyncio.create_task(self.show_inbox_forever())
        try:
            await self.listen()
        finally:
            showing.cancel()

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    async def ask_name(self) -> str | None:
        """Ask for a name and take its seat in the lobby, asking again with the reason when it can't be used."""
        error = ""
        while True:
            raw = await self.view.ask_name(error, MAX_NAME_LEN)
            if raw is None:
                return None
            try:
                name = check_name(raw)
            except InvalidName as e:
                error = str(e)
                continue
            if not (error := await self.claim_seat(name)):
                return name

    async def act(self, text: str) -> None:
        """The player's action: a choice number or free text. Show the action in the story area first, then send it."""
        if self.inputs and self.actor:
            await self.act_with_inputs(text)
        else:
            await self.send(text, echo=self.echo_for(text))

    def echo_for(self, text: str) -> str:
        """The action to show before sending: while you haven't acted, matched to the choices on screen; commands aren't shown."""
        if not self.actor or text.startswith("/"):
            return ""
        return pick_choice(text, self.choices) or text

    async def act_with_inputs(self, text: str) -> None:
        """With input modes (turtle soup): picking a mode that needs text switches to it and waits for typing; one that doesn't is sent at once; typed text is sent in the current mode."""
        labels = [m.label for m in self.inputs]
        if (picked := pick_choice(text, labels)) is not None:
            index = labels.index(picked)
            mode = self.inputs[index]
            if not mode.needs_text:
                if mode.confirm and not await self.view.ask_confirm(*mode.confirm):  # e.g. giving up: make sure first
                    return
                await self.send(mode.command, echo=mode.label)
                return
            self.input_mode = index
            self.view.mark_choice(index)
            self.refresh_hint()
            return
        mode = self.inputs[self.input_mode]
        await self.send(f"{mode.command} {text}", echo=UI["input_echo"].format(label=mode.label, text=text))

    async def send(self, text: str, echo: str = "") -> None:
        """Send a line of text and show the reply. echo is the player's action to show in the story area first."""
        if self.busy:
            return
        self.view.stop_timer()
        if echo:
            self.set_choices([])
            self.view.show_action(echo)
        await self.deliver(text)

    async def deliver(self, text: str, form: bool = False, answer: bool = False) -> None:
        """Pass a line of input to the room; the reply will be pushed back by the room. form marks an action in the new game dialog: it gets a reply only with answer."""
        await self.conn.send({"type": "send", "text": text[:MAX_INPUT_LEN], "form": form, "answer": answer})

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.view.set_busy(busy)

    def follow_draft(self, draft: str) -> None:
        """The narration the AI is writing has new text: hand it to the interface to show."""
        if draft and draft != self.draft:
            self._continue_narration(draft)
            self.draft = draft
            self.view.extend_narration(draft)

    async def narrate(self, text: str) -> None:
        """Show a complete passage of narration; if it's already streaming, finish showing it."""
        self._continue_narration(text)
        self.draft = ""
        await self.view.finish_narration(text)

    def _continue_narration(self, text: str) -> None:
        """If text continues the narration already shown, keep going; if not (the AI rewrote it), take back the old one and start a new passage."""
        if self.draft and not text.startswith(self.draft):
            self.discard_draft()
        if not self.draft:
            self.view.start_narration()

    def discard_draft(self) -> None:
        self.view.discard_narration()
        self.draft = ""

    def busy_text(self) -> str:
        """The waiting hint's text, e.g. "Writing the story: planning the story outline…"."""
        progress = self.progress
        return UI["busy"].format(label=self.busy_label or UI["busy_default"], progress=UI["busy_progress"].format(progress=progress) if progress else "")

    async def show_reply(self, reply: Reply) -> None:
        """Decide what happens next from the reply's phase."""
        if reply.phase != "playing":
            self.waiting = []  # This game's actions are over (the ending, back to the premise…): the hint no longer says "waiting for X"
            self.view.stop_timer()
        if self.draft and not reply.narration:  # Streaming failed midway and the turn didn't advance: take back the half-written narration
            self.discard_draft()
        if reply.timed != self.timed:
            self.timed = reply.timed
            self.view.set_status(status_line(*self.shown, self.timed))
        self.actor = reply.actor
        if reply.inputs != self.inputs or reply.narration:  # A new turn: back to the first mode (ask)
            self.inputs, self.input_mode = list(reply.inputs), 0
        if reply.info:
            self.view.show_info(*reply.info)
        if reply.error == "api":
            self.view.notify(reply.notice, error=True)
        elif reply.notice and reply.phase in ("playing", "ending", "ended") and not reply.narration:
            self.view.notify(reply.notice)

        if reply.form is not None:
            await self.show_setup_form(reply)
        elif reply.phase in HOST_PHASES and reply.choices:
            # The core's question and two options: continue/new game, confirm/cancel, or turtle soup's bank/AI puzzle
            yes = await self.view.ask_confirm(reply.notice, *reply.choices)
            await self.send("1" if yes else "2")
        elif reply.phase in ("playing", "ending"):
            await self.show_turn(reply)  # The turn that ended the story; the room goes on to write the epilogue
        elif reply.phase == "ended":
            await self.show_ending(reply.ending)

    async def show_setup_form(self, reply: Reply) -> None:
        """The game asked for its setup form (Reply.form): let the view draw it, apply its choices, then send what the host wrote."""
        if reply.error == "api":
            return  # Writing the opening failed: the error is already shown; stay put, and players can try again with /restart
        form = PremiseForm(reply, self.ask_room)
        answer = await self.view.ask_premise(form)
        if answer is None:
            return
        premise, want_timed, _ = answer
        for command in form.setup_commands(want_timed):
            await self.deliver(command, form=True)  # The mode and genre chosen in the dialog: no need to show the reply
        self.clear_story(premise)
        await self.send(premise)

    # ---------- Showing a turn and the ending ----------

    async def show_turn(self, reply: Reply) -> None:
        """With new narration, show the narration first, and only then the changes, choices and status bar update, so nothing is given away early."""
        if reply.narration:
            self.view.stop_timer()
            if reply.resumed:  # Loading or reconnecting: from a clean screen, show earlier narration and the current passage at once; it's all been read, so no typing
                self.clear_story()
                self.show_history(reply)
                self.view.show_past_narration(reply.narration)
                self.choices = list(reply.choices)  # Clearing the screen clears the choices, so set them after clearing
                self.refresh_hint()
            else:
                self.choices = list(reply.choices)
                self.view.prepare_choices(self.choices, timed=bool(reply.time_limit))
                self.refresh_hint()
                await self.narrate(reply.narration)
            for name, groups in reply.changes:
                self.view.show_changes(groups, name if len(reply.characters) > 1 else "")  # No name needed when playing alone
            self.view.show_choices(self.choices)
        else:
            self.set_choices(reply.choices)
        self.set_status(reply.turn, reply.characters)
        if reply.narration and reply.time_limit:
            await self.conn.send({"type": "ready"})  # The room starts the countdown once everyone has read it

    def show_history(self, reply: Reply) -> None:
        """Loading or reconnecting: first show all earlier narration and everyone's actions at once, then the current passage."""
        if reply.notice:
            self.view.show_note(reply.notice)  # "Loaded save: …"
        if reply.history_trimmed:
            self.view.show_note(UI["history_trimmed"])
        for narration, action in reply.history:
            self.view.show_past_narration(narration)
            for line in action.splitlines():
                self.view.show_action(line)
        if reply.history:
            self.view.show_note(UI["history_end"])

    async def show_ending(self, ending: Ending) -> None:
        """One part at a time: read the last narration first, press Enter for the epilogue, and again for the summary."""
        if ending.epilogue:
            await self.view.wait_enter(ending.reveal or UI["wait_epilogue"])
            self.view.show_ending_title(ending.title)
            await self.narrate(ending.epilogue)
        else:
            self.view.show_ending_title(UI["story_over"])
        await self.view.wait_enter(UI["wait_ending"])
        if not await self.view.ask_ending(ending.title, ending.record):
            self.view.exit()  # To play again, the room goes back to its waiting screen

    def clear_story(self, premise: str = "") -> None:
        self.choices = []
        self.draft = ""  # A cleared screen has no narration in progress
        self.shown = (0, [])
        self.view.clear_story(premise)
        self.refresh_hint()

    def set_choices(self, choices: list[str]) -> None:
        self.choices = list(choices)
        self.view.show_choices(self.choices)
        self.refresh_hint()

    def set_status(self, turn: int, characters: list[Status]) -> None:
        self.shown = (turn, characters)
        self.view.set_status(status_line(turn, characters, self.timed))

    def refresh_hint(self) -> None:
        """Progress on actions goes in the input box hint rather than a notice that covers the story: once you've acted, it shows who's still pending; before, it shows who has acted."""
        team = [s.name for s in self.shown[1] if s.alive]  # The team on the status bar
        acted = [n for n in team if n not in self.waiting and n != self.my_name] if self.waiting else []
        if not self.actor and self.waiting:
            self.view.set_hint(UI["hint_waiting"].format(names=UI["list_sep"].join(self.waiting)))
        elif self.actor and acted:
            self.view.set_hint(UI["hint_others_acted"].format(names=UI["list_sep"].join(acted), hint=self.input_hint()))
        else:
            self.view.set_hint(self.input_hint())

    def input_hint(self) -> str:
        """The input box's usual hint; with input modes, the current mode's explanation."""
        if self.inputs and self.actor and self.inputs[self.input_mode].hint:
            return self.inputs[self.input_mode].hint
        return UI["hint_input"]

    # ---------- Talking to the lobby and room ----------

    async def claim_seat(self, name: str) -> str:
        """Ask the lobby for this name: an empty string on success, otherwise why it can't be used."""
        await self.conn.send({"type": "join", "name": name, "token": self.token})
        answer = await self.conn.receive()
        if answer is None:
            return UI["room_lost"]
        return answer.get("reason", "") if answer["type"] == "rejected" else ""

    async def listen(self) -> None:
        """Receive messages pushed by the room. Simple ones are handled directly; replies, lobby screens and others that must wait for the previous one to finish showing are queued in inbox and handled in order."""
        while (message := await self.conn.receive()) is not None:
            kind = message["type"]
            if kind == "busy":
                self.progress = message.get("progress", "")
                self.busy_label = message.get("label", "") or self.busy_label
                self.set_busy(message["on"])
                if message["on"]:
                    self.view.show_busy()  # The room sends busy again whenever the progress changes
            elif kind == "draft":  # Narration the AI is writing, forwarded by the room
                self.follow_draft(message["text"])
            elif kind == "timer":
                self.view.start_timer(message["seconds"])
            elif kind == "waiting":
                self.update_waiting(message["names"])
            elif kind == "notice":
                self.view.notify(message["text"])
            elif kind == "replaced":  # The same browser came in from elsewhere: this one ends
                self.replaced = True
                self.view.notify(UI["session_replaced"], lasting=True)
                self.view.exit()
            elif kind == "new_story":  # Clear at once without queuing, so the "writing the story" right after isn't cleared too
                self.clear_story(message.get("premise", ""))
            elif kind == "premise" and self.premise_answer:
                self.premise_answer.set_result(Reply.from_dict(message["reply"]))
            else:
                self.inbox.put_nowait(message)
        if self.premise_answer and not self.premise_answer.done():  # The premise dialog is still waiting for the room: otherwise it would wait forever
            self.premise_answer.set_exception(ConnectionError(UI["room_disconnected"]))
        self.set_busy(False)
        if not self.replaced:
            self.view.notify(UI["room_disconnected"], error=True, lasting=True)

    def update_waiting(self, names: list[str]) -> None:
        """Who hasn't acted this turn changed: if someone just acted, show a brief notice and update the hint (without rebuilding the choices, so the screen doesn't flicker)."""
        if set(names) < set(self.waiting):  # The list got shorter: someone just acted (it resets to everyone on a new turn)
            if acted := [n for n in self.waiting if n not in names and n != self.my_name]:
                self.view.show_activity(UI["acted"].format(names=UI["list_sep"].join(acted)))
        self.waiting = names
        self.refresh_hint()

    async def show_inbox_forever(self) -> None:
        """Runs for as long as the client does: show queued replies and lobby screens one at a time, each once the last has finished showing."""
        while True:
            message = await self.inbox.get()
            kind = message["type"]
            if kind == "reply":
                await self.show_reply(Reply.from_dict(message["reply"]))
            elif kind == "lobby":
                self.show_lobby(message)

    async def ask_room(self, *commands: str) -> Reply:
        """Actions in the premise dialog (change genre, another one, suggest one): send the commands in order, asking the room to reply (answer) only to the last, so the reply received is always for that one."""
        self.premise_answer = asyncio.get_running_loop().create_future()
        for i, command in enumerate(commands):
            await self.deliver(command, form=True, answer=i == len(commands) - 1)
        try:
            return await self.premise_answer
        finally:
            self.premise_answer = None

    def show_lobby(self, screen: dict) -> None:
        """The lobby or a room's waiting screen (the content is up to the lobby and room). Clear the screen first right after arriving or leaving a room."""
        if screen.get("clear"):
            self.clear_story()
        self.view.show_lobby({k: v for k, v in screen.items() if k not in ("type", "clear", "hint")})
        self.actor, self.waiting = "", []
        self.choices = list(screen["choices"])  # Typing a number in the input box works too; the interface draws the buttons in the lobby screen, so the choice area below doesn't list them again
        self.view.show_choices([])
        self.view.set_hint(screen["hint"])
