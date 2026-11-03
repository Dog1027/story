// The web interface: display only. The shared layer on the server decides what to show when; this draws each message and sends the player's input back.
// The message format is in story/shells/web/view.py.
"use strict";

const CHAR_DELAY = 50; // Delay per character (milliseconds), about 20 characters a second
const FAST_FACTOR = 0.15; // After pressing Enter once, the delay shrinks to this fraction
// Pause a little longer after punctuation (both Chinese and English punctuation)
const PAUSE_AFTER = { "。": 250, "！": 250, "？": 250, "，": 100, "、": 80, "…": 150, "\n": 100, ".": 250, "!": 250, "?": 250, ",": 100, ";": 100 };
const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;
// Phones and tablets: don't move focus to the input box automatically, or the keyboard keeps popping up
const TOUCH = matchMedia("(pointer: coarse)").matches || matchMedia("(hover: none)").matches;
// Typing speed from the menu: fast types quicker (pressing Enter once more shows it all), instant shows each passage at once
const TYPING = { normal: { speed: 1, skip: false }, fast: { speed: 0.4, skip: false }, instant: { speed: 1, skip: true } };

const $ = (id) => document.getElementById(id);
// Interface text: T is the string table the server puts in the page (story/shells/ui/<lang>/dialogs.md, web.md); {name} is replaced with the value in vars
const t = (key, vars = {}) => T[key].replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? "");
const log = $("log"), input = $("input"), choicesList = $("choices");

const state = {
  ws: null,
  busy: false,
  typing: null, // Typing in progress: { speed, skip }
  narration: null, // The narration being shown: { el, text, done, finished } (text keeps growing while the AI is still writing)
  waitingEnter: null, // While waiting for Enter: the function to run when it's pressed
  choices: [],
  active: -1, // The choice moved to with ↑↓
  follow: true, // While the story area is at the bottom, follow new content
  hint: "", // The input box hint from the server; while typing, the box says how to speed up instead
  dividers: [], // Turn dividers before passages whose turn isn't known yet (it comes with the status bar after the passage)
  turnShown: 0, // The last turn a divider was numbered with
  busyLine: null,
  timer: null, // { total, left, last }
  lobbyPane: "rooms", // Which lobby tab shows on phones: rooms, people
  premise: null, // The open premise dialog
  me: "", // My name, from the lobby screen
  bagKnown: null, // Everything in the bags last time (name + item), to spot what's new; null at the start of a game, so loading doesn't count as new
  bagNew: new Set(), // New items, highlighted until the list has been opened and closed again
  exited: false,
  autoNamed: false, // Already tried the remembered name once automatically (on failure, ask the player instead of retrying forever)
};

// ---------- Connection ----------

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws?token=${encodeURIComponent(browserToken())}`);
  state.ws = ws;
  ws.onopen = () => {
    input.placeholder = "";
    setBusy(false); // The input box starts disabled (not connected yet). Can't wait for the first "writing the story" to end: loading a save and the lobby never call the AI
  };
  ws.onmessage = (event) => handle(JSON.parse(event.data));
  ws.onclose = () => {
    if (!state.exited) {
      setBusy(true);
      $("offline").hidden = false; // A bar across the top on every screen (the lobby has no input box), with a button to reload
    }
  };
}

function send(message) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(message));
}

const answer = (id, value = null) => send({ t: "answer", id, value });

// ---------- Messages from the server ----------

const handlers = {
  clear({ premise }) {
    log.replaceChildren();
    $("app").classList.remove("lobby");
    state.busyLine = null;
    state.follow = true;
    $("jump").hidden = true;
    state.dividers = [];
    state.turnShown = 0;
    if (premise) {
      const el = add("div", "premise");
      el.append(tag("b", "", t("premise")), premise);
    }
    renderChoices([]);
    renderStatus(null);
  },
  action({ text }) {
    const row = add("div", "action");
    row.append(tag("span", "", text));
    scrollLog(true); // You just acted: always scroll to the bottom to see the result
  },
  note({ text }) { add("div", "note", text); },
  narration_start() { closeBag(); startNarration(); }, // A new passage needs the room: fold the bag away
  past_narration({ text }) { addDivider(); add("div", "narration", text); }, // Earlier narration when loading: shown at once, no typing
  narration_text({ text }) { if (state.narration) state.narration.text = text; },
  narration_end({ id, text }) {
    if (!state.narration) startNarration();
    state.narration.text = text;
    state.narration.done = true;
    state.narration.finished.then(() => answer(id));
  },
  narration_discard() {
    if (!state.narration) return;
    state.narration.discarded = true;
    state.narration.el.remove();
    state.narration = null;
    state.typing = null;
    const divider = state.dividers.pop();
    if (divider) divider.remove();
    showHint();
  },
  changes({ name, groups }) {
    const el = add("div", "changes");
    const line = tag("div");
    if (name) line.append(tag("span", "who", name));
    groups.forEach(([label, items], i) => {
      if (i) line.append("　");
      line.append(tag("span", "label", label));
      for (const [text, tone] of items) line.append(tag("span", `item t-${tone}`, text));
    });
    el.append(line);
  },
  ending_title({ title }) { add("div", "ending-title", title); scrollLog(true); },
  wait_enter({ id, hint }) {
    const button = add("button", "continue", hint);
    button.type = "button";
    state.waitingEnter = () => { button.remove(); state.waitingEnter = null; showHint(); answer(id); };
    button.onclick = state.waitingEnter;
    input.placeholder = hint; // So you know to press Enter next even while scrolled up reading earlier story
    input.disabled = false;
    focusInput();
    nudge();
  },
  prepare_choices({ choices, timed }) {
    state.typing = state.typing || { speed: 1, skip: false }; // From now on Enter only speeds up typing and never picks a choice that isn't visible yet
    renderChoices(choices, true);
    if (timed) { $("timer").hidden = false; $("timer").classList.add("reserved"); }
  },
  choices({ choices }) {
    if (choices.length && choicesList.classList.contains("hidden") && same(choices, state.choices)) { // The narration finished typing: reveal the choices placed earlier
      choicesList.classList.remove("hidden");
      choicesList.classList.add("reveal");
    } else if (!choices.length && choicesList.children.length) {
      // After picking: keep the old choices' space but fully invisible (not even borders), so the story area doesn't jump around and text doesn't drop
      state.choices = [];
      state.active = -1;
      choicesList.classList.add("hidden");
    } else {
      renderChoices(choices);
    }
    if (choices.length) nudge();
  },
  mark_choice({ index }) { // Turtle soup: mark the input mode currently picked (ask, guess); what's typed next is sent in that mode
    choicesList.querySelectorAll(".choice").forEach((b, i) => b.classList.toggle("selected", i === index));
    focusInput();
  },
  hint({ placeholder }) {
    state.hint = placeholder;
    if (!state.typing) showHint();
  },
  status({ status }) { renderStatus(status); },
  lobby({ screen }) { renderLobby(screen); },
  busy({ on }) { setBusy(on); },
  busy_line({ text }) {
    if (!state.busy) return;
    if (!state.busyLine) {
      state.busyLine = add("div", "busy-line");
      state.busyLine.append(tag("span", "spinner"), tag("span"));
    }
    state.busyLine.lastChild.textContent = text;
    scrollLog();
  },
  timer({ seconds }) { startTimer(seconds); },
  stop_timer() { stopTimer(); },
  notify({ text, error, lasting }) { toast(text, { error, lasting }); },
  activity({ text }) { activity(text); },
  info({ title, body }) { infoSheet(title, body); },
  fatal({ text }) { add("div", "fatal", text); setBusy(true); input.placeholder = text; },
  confirm({ id, question, yes, no }) {
    nudge();
    openSheet((sheet, close) => {
      sheet.append(tag("h2", "", question));
      sheet.append(buttons([[no, () => close(false)], [yes, () => close(true), true]]));
    }, (value) => answer(id, value), false);
  },
  ending({ id, title, record }) {
    nudge();
    openSheet((sheet, close) => {
      sheet.append(tag("h2", "", title ? t("ending_title", { title }) : t("story_over")), tag("p", "record", record));
      sheet.append(buttons([[t("leave"), () => close(false)], [t("play_again"), () => close(true), true]]));
    }, (value) => answer(id, value), false);
  },
  name(message) {
    // Remember the last name: on the first ask, go straight in with it; only if it can't be used (e.g. the old connection hasn't dropped yet) show the dialog, with the reason and the name filled in
    const saved = stored("story-name");
    if (saved && !message.error && !state.autoNamed) {
      state.autoNamed = true;
      answer(message.id, saved);
    } else nameSheet(message);
  },
  premise(message) { nudge(); premiseSheet(message); },
  premise_update(message) { if (state.premise) state.premise.update(message); },
  exit() {
    state.exited = true;
    sheetQueue.length = 0;
    closeSheet();
    setBusy(true);
    log.replaceChildren(tag("div", "exit-screen", t("exited")));
    renderChoices([]);
    input.placeholder = t("exited_hint");
    if (state.ws) state.ws.close();
  },
};

function handle(message) {
  const handler = handlers[message.t];
  if (handler) handler(message);
}

// ---------- Story area ----------

function tag(name, className = "", text = "") {
  const el = document.createElement(name);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
}

function add(name, className, text) {
  const el = tag(name, className, text);
  if (state.busyLine && state.busyLine.isConnected) log.insertBefore(el, state.busyLine);
  else log.append(el);
  scrollLog();
  return el;
}

function scrollLog(force = false) {
  if (force) state.follow = true;
  if (state.follow) log.scrollTop = log.scrollHeight;
  else $("jump").hidden = false; // Reading back: say there's something new below instead of pulling the reader down
}

// Keep following new content while at the bottom; stop when scrolled up (so you can read back while text is typing), and resume when back at the bottom
log.addEventListener("scroll", () => {
  state.follow = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
  if (state.follow) $("jump").hidden = true;
});
$("jump").addEventListener("click", () => scrollLog(true));

// A divider before each passage, numbered once the status bar brings the turn; it stays hidden while empty. The epilogue isn't a turn
function addDivider() {
  const last = log.lastElementChild;
  if (last && last.classList.contains("ending-title")) return;
  state.dividers.push(add("div", "turn-divider"));
}

function numberDividers(turn) {
  if (turn <= state.turnShown) return; // The same turn again (someone came or went): a passage in progress keeps waiting
  state.dividers.reverse().forEach((el, i) => { // Counting back from this turn: loading shows several earlier passages at once
    const number = turn - i;
    if (number > 1 && number > state.turnShown) el.textContent = t("turn", { turn: number });
    else el.remove(); // The opening needs no divider
  });
  state.dividers = [];
  state.turnShown = turn;
}

// The input box hint: the server's, unless waiting for Enter (which shows its own)
function showHint() {
  if (!state.waitingEnter) input.placeholder = state.hint;
}

// When it's your turn while this tab is in the background, say so in the tab's title; back to normal once the tab is shown
function nudge() {
  if (document.hidden) document.title = t("your_turn_title", { title: T.title });
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = T.title; });

// A passage of narration: start typing while the AI is still writing, with the typing chasing the text received so far; done once it's all received and typed
function startNarration() {
  if (state.busyLine) { state.busyLine.remove(); state.busyLine = null; }
  addDivider();
  const narration = { el: add("div", "narration"), text: "", done: false };
  state.narration = narration;
  state.typing = { ...TYPING[setting("speed")] };
  const typing = state.typing;
  if (!typing.skip && !REDUCED_MOTION) input.placeholder = t(TOUCH ? "typing_hint_touch" : "typing_hint");
  narration.finished = (async () => {
    let shown = 0;
    while (!narration.discarded) {
      const text = narration.text;
      // Tab in the background, Enter pressed twice, or reduced motion: show everything received so far at once
      if ((typing.skip || document.hidden || REDUCED_MOTION) && shown < text.length) {
        shown = text.length;
        narration.el.textContent = text;
        scrollLog();
      }
      if (shown < text.length) {
        shown += 1;
        narration.el.textContent = text.slice(0, shown);
        scrollLog();
        await sleep((CHAR_DELAY + (PAUSE_AFTER[text[shown - 1]] || 0)) * typing.speed);
      } else if (narration.done) {
        break;
      } else {
        await sleep(50); // The AI is still writing
      }
    }
    if (state.narration === narration) state.narration = null;
    if (state.typing === typing) { state.typing = null; showHint(); }
  })();
}

function speedUp() {
  if (state.typing.speed < 1) state.typing.skip = true;
  state.typing.speed = FAST_FACTOR;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

// Clicking the story area: speeds up typing, or continues while waiting for Enter
log.addEventListener("click", (event) => {
  if (event.target.closest("button")) return;
  if (state.waitingEnter) state.waitingEnter();
  else if (state.typing) speedUp();
});

// ---------- Status bar ----------

function renderStatus(status) {
  const box = $("status");
  box.replaceChildren();
  renderBag(status);
  if (!status) {
    $("turn").textContent = "";
    $("mode").hidden = true;
    return;
  }
  $("turn").textContent = t("turn", { turn: status.turn });
  numberDividers(status.turn);
  $("mode").hidden = !status.timed;
  $("mode").textContent = status.mode;
  for (const c of status.characters) {
    const row = tag("div", "status-row" + (c.alive ? "" : " fallen"));
    if (status.named) row.append(tag("span", "status-name", c.name));
    const chips = tag("div", "chips");
    if (!c.alive) chips.append(tag("span", "t-muted", t("fallen")));
    else {
      if (c.warning) chips.append(tag("span", "chip warning", `⚠ ${c.warning_text}`));
      for (const [text, tone] of c.items) chips.append(tag("span", `chip t-${tone}`, text));
    }
    row.append(chips);
    box.append(row);
  }
}

// The bag: a button on the top bar (only once someone carries something) opens a list below the status bar, so the bar itself stays short
// New items make the count pulse and stay highlighted in the list until it's been looked at. With several people, my own bag comes first
function renderBag(status) {
  const people = status ? status.characters.filter((c) => c.bag && c.bag.length) : [];
  people.sort((a, b) => (b.name === state.me) - (a.name === state.me));
  const button = $("bag-button"), panel = $("bag");
  const keys = new Set(people.flatMap((c) => c.bag.map((item) => `${c.name}\n${item}`)));
  const fresh = state.bagKnown ? [...keys].filter((k) => !state.bagKnown.has(k)) : [];
  state.bagKnown = status ? keys : null;
  fresh.forEach((k) => state.bagNew.add(k));
  if (fresh.length) {
    button.classList.remove("pulse");
    void button.offsetWidth; // Restart the animation
    button.classList.add("pulse");
  }
  button.hidden = !people.length;
  if (!people.length) closeBag();
  $("bag-count").textContent = people.reduce((n, c) => n + c.bag.length, 0) || "";
  panel.replaceChildren();
  for (const c of people) {
    const group = tag("div", "bag-group");
    if (status.named) group.append(tag("div", "bag-name", c.name));
    const list = tag("ul", "bag-list");
    for (const item of c.bag) list.append(tag("li", state.bagNew.has(`${c.name}\n${item}`) ? "new" : "", item));
    group.append(list);
    panel.append(group);
  }
}

function closeBag() {
  const panel = $("bag");
  if (!panel.hidden) { // Looked at: new items are no longer new
    state.bagNew.clear();
    panel.querySelectorAll(".new").forEach((el) => el.classList.remove("new"));
  }
  panel.hidden = true;
  $("bag-button").setAttribute("aria-expanded", "false");
}

$("bag-button").addEventListener("click", (event) => {
  event.stopPropagation();
  if (!$("bag").hidden) return closeBag();
  $("bag").hidden = false;
  $("bag-button").setAttribute("aria-expanded", "true");
});
document.addEventListener("click", (event) => { if (!$("bag").hidden && !$("bag").contains(event.target)) closeBag(); }); // Tapping anywhere else folds it away

// ---------- Lobby and room waiting screens ----------

// Lobby: rooms on the left (the first tab on phones) and everyone online on the right; room: seats plus start and leave buttons.
// Buttons send the choice's number, the same as typing it in the input box
function renderLobby(screen) {
  renderStatus(null);
  if (screen.you) { store("story-name", screen.you); state.me = screen.you; } // Only remember a name the server accepted
  renderChoices([]); // Also clear choices left over from the last game, invisible but still taking space: the waiting screen's buttons are in the panel
  $("app").classList.toggle("lobby", screen.view === "lobby"); // The lobby has two columns side by side
  log.querySelectorAll(".lobby-panel").forEach((el) => el.remove());
  const panel = screen.view === "room" ? roomPanel(screen) : lobbyPanel(screen);
  add("section", "lobby-panel").replaceWith(panel);
  scrollLog(true);
}

function pick(choice) {
  if (!state.busy) send({ t: "act", text: choice });
}

function actionButton(label, choice, primary = false) {
  const button = tag("button", "btn" + (primary ? " primary" : ""), label);
  button.type = "button";
  button.onclick = () => pick(choice);
  return button;
}

function initial(name) {
  return [...name][0] || "?";
}

function lobbyPanel({ title, you, choices, rooms, people, max_rooms, seats }) {
  const panel = tag("section", "lobby-panel lobby-view");
  const head = tag("div", "lobby-head");
  head.append(tag("h1", "", title), tag("span", "lobby-count", t("lobby_counts", { rooms: rooms.length, max: max_rooms, people: people.length })));

  const tabs = tag("div", "lobby-tabs");
  tabs.setAttribute("role", "tablist");
  const roomsPane = tag("div", "lobby-pane rooms-pane"), peoplePane = tag("div", "lobby-pane people-pane");
  const showPane = (which) => {
    panel.dataset.pane = which;
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pane === which)));
  };
  for (const [which, label] of [["rooms", t("lobby_rooms_tab", { count: rooms.length })], ["people", t("lobby_people_tab", { count: people.length })]]) {
    const button = tag("button", "", label);
    button.type = "button";
    button.dataset.pane = which;
    button.setAttribute("role", "tab");
    button.onclick = () => { state.lobbyPane = which; showPane(which); };
    tabs.append(button);
  }

  roomsPane.append(tag("h2", "", t("lobby_rooms")));
  const create = actionButton("＋ " + choices[0], "1", true);
  create.classList.add("new-room");
  roomsPane.append(create);
  if (!rooms.length) roomsPane.append(tag("p", "lobby-empty", t("lobby_no_rooms")));
  const list = tag("ul", "room-list");
  for (const room of rooms) {
    const card = tag("li", `room-card ${room.state}`);
    const top = tag("div", "room-top");
    top.append(tag("strong", "", room.title), tag("span", `room-state ${room.state}`, t(`room_state_${room.state}`, { count: room.members.length, max: seats, game: room.game })));
    const members = tag("div", "room-members");
    room.members.forEach((m) => {
      const who = tag("span", "member", m);
      if (m === room.host) who.append(tag("span", "host-tag", t("host_tag")));
      members.append(who);
    });
    card.append(top, members);
    if (room.choice) card.append(actionButton(t("join"), room.choice));
    list.append(card);
  }
  roomsPane.append(list);

  peoplePane.append(tag("h2", "", t("lobby_people")));
  const roster = tag("ul", "people-list");
  for (const person of people) {
    const row = tag("li", "person" + (person.room ? (person.playing ? " playing" : " in-room") : ""));
    const name = tag("span", "person-name", person.name);
    if (person.name === you) name.append(tag("span", "you-tag", t("you_tag")));
    const where = person.room
      ? t(person.playing ? "where_playing" : "where_room", { host: person.room })
      : t("where_lobby");
    row.append(tag("span", "avatar", initial(person.name)), name, tag("span", "person-where", where));
    roster.append(row);
  }
  peoplePane.append(roster);

  panel.append(head, tabs, tag("div", "lobby-cols"));
  panel.lastChild.append(roomsPane, peoplePane);
  showPane(state.lobbyPane);
  return panel;
}

function roomPanel({ title, host, you, members, seats, choices, games = [] }) {
  const panel = tag("section", "lobby-panel room-view");
  const head = tag("div", "lobby-head");
  head.append(tag("h1", "", title), tag("span", "lobby-count", t("room_seats", { count: members.length, max: seats })));
  const list = tag("ol", "seats");
  for (let i = 0; i < seats; i++) {
    const name = members[i];
    const seat = tag("li", "seat" + (name ? "" : " empty"));
    if (name) {
      const info = tag("span", "seat-info"), tags = tag("span", "seat-tags"); // The tags go on a line under the name, so a narrow seat still shows the name
      info.append(tag("span", "seat-name", name));
      if (name === you) tags.append(tag("span", "you-tag", t("you_tag")));
      if (name === host) tags.append(tag("span", "host-tag", t("host_tag")));
      if (tags.childElementCount) info.append(tags);
      seat.append(tag("span", "avatar", initial(name)), info);
    } else {
      seat.append(tag("span", "avatar", ""), tag("span", "seat-name", t("seat_empty")));
    }
    list.append(seat);
  }
  panel.append(head, list);
  const actions = tag("div", "room-actions");
  if (games.length) { // The host: pick a game from the menu, then start it
    const [picker, chosen] = gamePicker(games);
    const start = tag("button", "btn primary", t("start"));
    start.type = "button";
    start.onclick = () => pick(chosen().choice);
    panel.append(picker);
    actions.append(start);
  }
  actions.prepend(actionButton(choices[choices.length - 1], String(choices.length))); // "Leave room" is always the last option
  panel.append(actions);
  return panel;
}

// The host's game picker: one card per game, with its name and a line about it. The browser remembers the last game picked.
// Returns [the picker, a function giving the game currently picked]
function gamePicker(games) {
  const box = tag("fieldset", "game-picker");
  box.append(tag("legend", "", t("pick_game")));
  let chosen = games.find((g) => g.code === stored("story-game")) || games[0];
  for (const game of games) {
    const option = tag("label", "game-option");
    const radio = tag("input");
    radio.type = "radio";
    radio.name = "game";
    radio.checked = game === chosen;
    radio.onchange = () => { chosen = game; store("story-game", game.code); };
    const text = tag("span", "game-text");
    text.append(tag("strong", "", game.title), tag("span", "game-description", game.description));
    option.append(radio, text);
    box.append(option);
  }
  return [box, () => chosen];
}

// ---------- Choices and input ----------

function renderChoices(choices, hidden = false) {
  state.choices = choices.slice();
  state.active = -1;
  choicesList.replaceChildren();
  choicesList.classList.toggle("hidden", hidden);
  choicesList.classList.remove("reveal");
  choices.forEach((text, i) => {
    const item = tag("li");
    const button = tag("button", "choice");
    button.type = "button";
    button.append(tag("span", "num", String(i + 1)), tag("span", "", text));
    button.onclick = () => choose(i);
    item.append(button);
    choicesList.append(item);
  });
}

function choose(index) {
  if (state.busy || state.typing || choicesList.classList.contains("hidden")) return;
  send({ t: "act", text: String(index + 1) });
}

function setActive(index) {
  const buttons = choicesList.querySelectorAll(".choice");
  if (!buttons.length) return;
  state.active = (index + buttons.length) % buttons.length;
  buttons.forEach((b, i) => b.classList.toggle("active", i === state.active));
  buttons[state.active].scrollIntoView({ block: "nearest" });
}

function focusInput() {
  if (!TOUCH) input.focus(); // Computers: back in the input box, ready to type or press Enter
}

function setBusy(busy) {
  state.busy = busy;
  input.disabled = busy && !state.waitingEnter;
  $("send").disabled = busy && !state.waitingEnter;
  if (!busy) {
    if (state.busyLine) state.busyLine.remove();
    state.busyLine = null;
    if (!state.premise && $("overlay").hidden) focusInput();
  }
}

$("input-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.waitingEnter) return state.waitingEnter();
  if (state.typing) return speedUp();
  if (state.busy) return;
  const text = input.value.trim();
  input.value = "";
  if (!text) {
    if (state.active >= 0) choose(state.active);
    return;
  }
  if (text.startsWith("/")) return send({ t: "command", text });
  send({ t: "act", text });
});

input.addEventListener("keydown", (event) => {
  if (input.value || !(event.key === "ArrowDown" || event.key === "ArrowUp")) return;
  event.preventDefault();
  setActive(state.active + (event.key === "ArrowDown" ? 1 : state.active < 0 ? 0 : -1));
});

// When no dialog is open, pressing Enter anywhere on the page speeds up typing or continues
document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !$("overlay").hidden || event.target === input) return;
  if (state.waitingEnter) { event.preventDefault(); state.waitingEnter(); }
  else if (state.typing) { event.preventDefault(); speedUp(); }
});

// ---------- Timed mode ----------

function startTimer(seconds) {
  state.timer = { total: seconds, left: seconds, last: performance.now() };
  $("timer").hidden = false;
  $("timer").classList.remove("reserved");
  renderTimer();
}

function stopTimer() {
  state.timer = null;
  $("timer").hidden = true;
  $("timer").classList.remove("reserved", "urgent");
}

function renderTimer() {
  const { total, left } = state.timer;
  $("timer-fill").style.width = `${(100 * left) / total}%`;
  $("timer-text").textContent = t("seconds", { seconds: Math.ceil(left) });
  $("timer").classList.toggle("urgent", left <= 5);
}

setInterval(() => {
  const timer = state.timer;
  if (!timer) return;
  const now = performance.now();
  const elapsed = (now - timer.last) / 1000;
  timer.last = now;
  if (state.busy) return;
  timer.left = Math.max(0, timer.left - elapsed);
  renderTimer();
  if (timer.left === 0) stopTimer(); // The room handles time's up; this only displays it
}, 100);

// ---------- Dialogs ----------

let closeCurrent = null;
const sheetQueue = []; // When a dialog is already open, later ones wait in line instead of covering the one being answered

// Every dialog is centered on computers and comes up from the bottom on phones (style.css)
function openSheet(build, onClose, dismissible = true) {
  if (closeCurrent) {
    sheetQueue.push([build, onClose, dismissible]);
    return;
  }
  const overlay = $("overlay"), sheet = $("sheet");
  sheet.replaceChildren();
  let done = false;
  const close = (value) => {
    if (done) return;
    done = true;
    overlay.hidden = true;
    sheet.replaceChildren();
    closeCurrent = null;
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose(value);
    if (sheetQueue.length) openSheet(...sheetQueue.shift());
    else if (!state.busy || state.waitingEnter) focusInput();
  };
  const onKey = (event) => { if (event.key === "Escape" && dismissible) close(null); };
  closeCurrent = () => close(null);
  build(sheet, close);
  const heading = sheet.querySelector("h2");
  if (heading) heading.id = "sheet-title";
  overlay.hidden = false;
  document.addEventListener("keydown", onKey);
  // Only dialogs that need typing (the name) focus the input; on phones the premise can just use the default, so don't pop up the keyboard on opening
  const focus = sheet.querySelector(TOUCH ? "input[type=text]" : "textarea, input:not([type=checkbox]), .btn.primary");
  if (focus) focus.focus();
}

function closeSheet() { if (closeCurrent) closeCurrent(); }

function buttons(list) {
  const row = tag("div", "buttons");
  list.forEach(([label, action, primary], i) => {
    const button = tag("button", "btn" + (primary ? " primary" : ""), label);
    button.type = "button";
    button.onclick = action;
    if (i === 0 && list.length > 2) button.classList.add("spacer");
    row.append(button);
  });
  return row;
}

function infoSheet(title, body) {
  openSheet((sheet, close) => {
    sheet.append(tag("h2", "", title), infoBody(body), buttons([[t("close"), () => close(), true]]));
  });
}

// The game's text for /state and /help: a line alone in 【】 is a section heading, lines starting with "- " a list, anything else a paragraph
function infoBody(text) {
  const box = tag("div", "body");
  let list = null;
  for (const line of text.split("\n")) {
    const heading = line.trim().match(/^【(.+)】$/);
    if (heading) box.append(tag("h3", "", heading[1]));
    else if (line.startsWith("- ")) {
      if (!list) box.append(list = tag("ul"));
      list.append(tag("li", "", line.slice(2)));
      continue;
    } else if (line.trim()) box.append(tag("p", "", line));
    list = null;
  }
  return box;
}

// Changing names leaves the room, and the save belongs to the team's names, so it's like starting over: ask first
function renameSheet() {
  openSheet((sheet, close) => {
    sheet.append(tag("h2", "", t("rename_question")), tag("p", "", t("rename_warning")));
    sheet.append(buttons([[t("rename_no"), () => close(false), true], [t("rename_yes"), () => close(true)]]));
  }, (sure) => {
    if (!sure) return;
    store("story-name", ""); // Forget the name and reconnect: leaves the current room and asks for a name again
    state.exited = true;
    location.reload();
  });
}

// Settings remembered only in this browser (the name, the last game picked, the appearance); if storage fails (e.g. private browsing), there's nothing remembered
function stored(key) {
  try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
}

function store(key, value) {
  try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch (e) {}
}

// This browser's ID: when the same browser connects again with the same name, the server lets the new connection replace the old one (without waiting for it to drop).
// getRandomValues rather than randomUUID: a LAN http address isn't a secure context, so randomUUID isn't available
function browserToken() {
  try {
    let token = localStorage.getItem("story-token");
    if (!token) {
      token = [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem("story-token", token);
    }
    return token;
  } catch (e) {
    return ""; // Can't store it (e.g. private browsing): no replacing, so as before, wait for the old connection to drop
  }
}

// The server decides whether a name can be used; if not, it asks again with the reason (error)
function nameSheet({ id, error, max_len }) {
  openSheet((sheet, close) => {
    const name = tag("input");
    name.type = "text";
    name.id = "name-input";
    name.placeholder = t("name_placeholder");
    name.maxLength = max_len;
    name.value = stored("story-name");
    const errorLine = tag("p", "error", error || "");
    const submit = () => close(name.value);
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    sheet.append(tag("h2", "", t("name_title")), tag("p", "hint", t("name_hint")), name, errorLine);
    sheet.append(buttons([[t("enter"), submit, true]]));
  }, (value) => answer(id, value), false);
}

// The rules (the genre menu, whether to replace the text box, which commands to send) are in the server's shared layer (PremiseForm): this only draws them and sends actions along with the text box content,
// then puts in the new opening from the reply (leaving it as is when text is null)
function premiseSheet({ id, default: initial, timed, genre, options, hints }) {
  openSheet((sheet, close) => {
    let nextReq = 0;
    const area = tag("textarea");
    area.id = "premise-input";
    area.placeholder = t("premise_placeholder");
    area.value = initial;
    area.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); start(); } });

    const timedBox = tag("input");
    timedBox.type = "checkbox";
    timedBox.id = "timed-input";
    timedBox.checked = timed;
    const timedLabel = tag("label", "check");
    timedLabel.append(timedBox, t("timed_option"));

    const select = tag("select");
    select.id = "genre-input";
    const genreHint = tag("p", "hint", hints[genre] || "");
    for (const [label, value] of options) {
      const option = tag("option", "", label);
      option.value = value;
      select.append(option);
    }
    select.value = genre;

    const pending = {};
    const request = (fields) => new Promise((resolve) => {
      const req = ++nextReq;
      pending[req] = resolve;
      send({ t: "premise_event", req, text: area.value, ...fields });
    });
    state.premise = { update: (reply) => { const done = pending[reply.req]; delete pending[reply.req]; if (done) done(reply); } };
    const show = (reply) => {
      if (reply.error) toast(reply.error, { error: true });
      else if (reply.text !== null && reply.text !== undefined) area.value = reply.text;
    };

    select.addEventListener("change", async () => {
      genreHint.textContent = hints[select.value] || "";
      show(await request({ action: "genre", genre: select.value }));
    });

    const reroll = tag("button", "btn", t("reroll"));
    reroll.type = "button";
    reroll.onclick = async () => show(await request({ action: "reroll" }));
    const suggest = tag("button", "btn", t("suggest"));
    suggest.type = "button";
    suggest.onclick = async () => {
      suggest.disabled = true;
      suggest.textContent = t("thinking");
      const reply = await request({ action: "suggest" });
      suggest.disabled = false;
      suggest.textContent = t("suggest");
      if (reply.error) toast(reply.error, { error: true, title: t("suggest_failed") });
      else { show(reply); if (!TOUCH) area.focus(); }
    };
    const startButton = tag("button", "btn primary", t("start"));
    startButton.type = "button";
    const start = () => close([area.value, timedBox.checked]);
    startButton.onclick = start;

    const row = tag("div", "buttons");
    reroll.classList.add("spacer");
    row.append(reroll, suggest, startButton);
    const field = (...parts) => { const box = tag("div", "field"); box.append(...parts); return box; }; // A control with its explanation, set apart from the next one
    sheet.append(tag("h2", "", t("premise_title")));
    if (options.length) sheet.append(field(select, genreHint));
    sheet.append(field(tag("p", "hint", t("premise_hint")), area), timedLabel, row);
  }, (value) => {
    state.premise = null;
    answer(id, value);
  }, false);
}

// ---------- Notices ----------

function toast(text, { error = false, lasting = false, title = "" } = {}) {
  const el = tag("div", "toast" + (error ? " error" : ""));
  if (error) el.append(tag("b", "", title || t("error_title")));
  el.append(text);
  $("toasts").append(el);
  setTimeout(() => el.remove(), lasting ? 30000 : error ? 8000 : 3500);
}

// Others' activity (e.g. "Hua acted"): shown briefly at the top right, below the status bar, without covering the story or choices
function activity(text) {
  const box = $("activity");
  box.style.top = `${$("top").getBoundingClientRect().bottom + 8}px`;
  const el = tag("div", "activity-item", text);
  box.append(el);
  while (box.children.length > 3) box.firstChild.remove();
  setTimeout(() => el.classList.add("leaving"), 2200);
  setTimeout(() => el.remove(), 2600);
}

// ---------- Menu ----------

const menu = $("menu");
$("reload").addEventListener("click", () => location.reload());
$("menu-button").addEventListener("click", (event) => {
  event.stopPropagation();
  menu.hidden = !menu.hidden;
  const playing = $("turn").textContent !== ""; // The status bar shows a turn only during a game: in the lobby and rooms these commands do nothing
  menu.querySelectorAll("[data-command]").forEach((b) => { b.hidden = !playing; });
  markSettings();
});
document.addEventListener("click", (event) => { if (!menu.hidden && !menu.contains(event.target)) menu.hidden = true; });
menu.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.command) {
    menu.hidden = true;
    if (!state.busy && !state.typing) send({ t: "command", text: button.dataset.command });
  } else if (button.dataset.local === "rename") {
    menu.hidden = true;
    renameSheet();
  } else if (button.dataset.value) {
    const name = button.closest("[data-setting]").dataset.setting, value = button.dataset.value;
    store(`story-${name}`, value === SETTINGS[name] ? "" : value);
    if (name !== "speed") setRoot(name, value === SETTINGS[name] ? "" : value); // Speed is read when the next passage starts
    markSettings();
  }
});

// The menu's settings and their defaults (index.html applies the stored appearance and text size before the page draws)
const SETTINGS = { theme: "system", size: "medium", speed: "normal" };

function setting(name) {
  const value = stored(`story-${name}`);
  return value && menu.querySelector(`[data-setting="${name}"] [data-value="${value}"]`) ? value : SETTINGS[name];
}

function setRoot(name, value) {
  if (value) document.documentElement.dataset[name] = value;
  else delete document.documentElement.dataset[name];
}

function markSettings() {
  menu.querySelectorAll("[data-setting]").forEach((group) => {
    const current = setting(group.dataset.setting);
    group.querySelectorAll("[data-value]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === current)));
  });
}

// Notices must appear above the choice area at the bottom: record the choice area's height
new ResizeObserver(() => document.documentElement.style.setProperty("--dock-height", `${$("dock").offsetHeight}px`)).observe($("dock"));

connect();
