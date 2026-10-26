// 網頁介面：只負責畫面。伺服器上的共用層決定什麼時候顯示什麼，這裡把每則訊息畫出來，再把玩家的輸入送回去。
// 訊息格式見 story/shells/web/view.py。
"use strict";

const CHAR_DELAY = 50; // 每個字的間隔（毫秒），大約一秒 20 個字（跟終端機版一樣）
const FAST_FACTOR = 0.15; // 按一次 Enter 後，間隔縮成原本的幾倍
// 標點後面多停一下（中文與英文的標點都有，跟終端機版一樣）
const PAUSE_AFTER = { "。": 250, "！": 250, "？": 250, "，": 100, "、": 80, "…": 150, "\n": 100, ".": 250, "!": 250, "?": 250, ",": 100, ";": 100 };
const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;
// 手機、平板：不要自動把焦點移到輸入框，不然鍵盤會一直跳出來
const TOUCH = matchMedia("(pointer: coarse)").matches || matchMedia("(hover: none)").matches;

const $ = (id) => document.getElementById(id);
// 介面文字：T 是伺服器放進頁面的字串表（story/ui/語言/dialogs.md、web.md），{名稱} 換成 vars 裡的值
const t = (key, vars = {}) => T[key].replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? "");
const log = $("log"), input = $("input"), choicesList = $("choices");

const state = {
  ws: null,
  busy: false,
  typing: null, // 正在打字：{ speed, skip }
  narration: null, // 正在顯示的劇情：{ el, text, done, finished }（AI 還在寫時 text 會越來越長）
  waitingEnter: null, // 等玩家按 Enter 時：按下後要執行的函式
  choices: [],
  active: -1, // 用 ↑↓ 移到的選項
  follow: true, // 故事區停在最底時，新內容出現就跟著捲
  busyLine: null,
  timer: null, // { total, left, last }
  lobbyPane: "rooms", // 手機上大廳顯示哪個分頁：rooms、people
  premise: null, // 開著的前提對話框
  exited: false,
  autoNamed: false, // 已經自動用記住的名字試過一次（失敗時改問玩家，不會一直重試）
};

// ---------- 連線 ----------

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws?token=${encodeURIComponent(browserToken())}`);
  state.ws = ws;
  ws.onopen = () => {
    input.placeholder = "";
    setBusy(false); // 頁面一開始的輸入框是停用的（還沒連上）。不能等到第一次「故事生成中」結束才打開：讀檔、大廳都不會呼叫 AI
  };
  ws.onmessage = (event) => handle(JSON.parse(event.data));
  ws.onclose = () => {
    if (!state.exited) {
      setBusy(true);
      input.placeholder = t("disconnected");
      toast(t("server_lost"), { error: true, lasting: true });
    }
  };
}

function send(message) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(message));
}

const answer = (id, value = null) => send({ t: "answer", id, value });

// ---------- 伺服器送來的訊息 ----------

const handlers = {
  clear({ premise }) {
    log.replaceChildren();
    $("app").classList.remove("wide");
    state.busyLine = null;
    state.follow = true;
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
    scrollLog(true); // 自己剛行動：一定捲到最底看結果
  },
  note({ text }) { add("div", "note", text); },
  narration_start() { startNarration(); },
  past_narration({ text }) { add("div", "narration", text); }, // 讀檔時之前的劇情：直接顯示，不打字
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
    state.waitingEnter = () => { button.remove(); state.waitingEnter = null; input.placeholder = placeholder; answer(id); };
    button.onclick = state.waitingEnter;
    const placeholder = input.placeholder;
    input.placeholder = hint; // 往上捲在看前面的劇情時，也知道接下來要按 Enter
    input.disabled = false;
    focusInput();
  },
  prepare_choices({ choices, timed }) {
    state.typing = state.typing || { speed: 1, skip: false }; // 從現在起按 Enter 都算加速，不會選到還看不見的選項
    renderChoices(choices, true);
    if (timed) { $("timer").hidden = false; $("timer").classList.add("reserved"); }
  },
  choices({ choices }) {
    if (choices.length && choicesList.classList.contains("hidden") && same(choices, state.choices)) { // 劇情打完字：讓先放好的選項出現
      choicesList.classList.remove("hidden");
      choicesList.classList.add("reveal");
    } else if (!choices.length && choicesList.children.length) {
      // 選完選項：保留原本選項的位置，只是完全看不見（連框線都不畫），故事區才不會忽高忽低、文字往下掉
      state.choices = [];
      state.active = -1;
      choicesList.classList.add("hidden");
    } else {
      renderChoices(choices);
    }
  },
  hint({ placeholder }) {
    if (!state.waitingEnter) input.placeholder = placeholder;
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
  info({ title, body }) { infoSheet(title, body); },
  fatal({ text }) { add("div", "fatal", text); setBusy(true); input.placeholder = text; },
  confirm({ id, question, yes, no }) {
    openSheet((sheet, close) => {
      sheet.append(tag("h2", "", question));
      sheet.append(buttons([[no, () => close(false)], [yes, () => close(true), true]]));
    }, (value) => answer(id, value), false);
  },
  ending({ id, title, record }) {
    openSheet((sheet, close) => {
      sheet.append(tag("h2", "", title ? t("ending_title", { title }) : t("story_over")), tag("p", "record", record));
      sheet.append(buttons([[t("leave"), () => close(false)], [t("play_again"), () => close(true), true]]));
    }, (value) => answer(id, value), false);
  },
  name(message) {
    // 記得上次的名字：第一次問時直接用它進去；不能用（例如舊的連線還沒斷）才跳出對話框，說明原因並預先填好
    const saved = savedName();
    if (saved && !message.error && !state.autoNamed) {
      state.autoNamed = true;
      answer(message.id, saved);
    } else nameSheet(message);
  },
  premise(message) { premiseSheet(message); },
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

// ---------- 故事區 ----------

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
}

// 停在最底就繼續跟著新內容，往上捲就不跟（文字還在打的時候也能往回看），捲回最底再恢復
log.addEventListener("scroll", () => { state.follow = log.scrollTop + log.clientHeight >= log.scrollHeight - 4; });

// 一段劇情：AI 還在寫時就開始打字，打字效果追著目前收到的文字；收完、打完才結束
function startNarration() {
  if (state.busyLine) { state.busyLine.remove(); state.busyLine = null; }
  const narration = { el: add("div", "narration"), text: "", done: false };
  state.narration = narration;
  state.typing = { speed: 1, skip: false };
  const typing = state.typing;
  narration.finished = (async () => {
    let shown = 0;
    while (!narration.discarded) {
      const text = narration.text;
      // 分頁在背景、按了兩次 Enter、或不要動畫時：直接顯示目前收到的全部
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
        await sleep(50); // AI 還在寫
      }
    }
    if (state.narration === narration) state.narration = null;
    if (state.typing === typing) state.typing = null;
  })();
}

function speedUp() {
  if (state.typing.speed < 1) state.typing.skip = true;
  state.typing.speed = FAST_FACTOR;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

// 點故事區：打字中就加速，等 Enter 時就繼續
log.addEventListener("click", (event) => {
  if (event.target.closest("button")) return;
  if (state.waitingEnter) state.waitingEnter();
  else if (state.typing) speedUp();
});

// ---------- 狀態列 ----------

function renderStatus(status) {
  const box = $("status");
  box.replaceChildren();
  if (!status) {
    $("turn").textContent = "";
    $("mode").hidden = true;
    return;
  }
  $("turn").textContent = t("turn", { turn: status.turn });
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

// ---------- 大廳與房間的等人畫面 ----------

// 大廳：左邊（手機是第一個分頁）是房間，右邊是所有在線的人；房間：座位與開始、離開的按鈕。
// 按鈕送出的是選項的編號，跟在輸入框打編號一樣
function renderLobby(screen) {
  renderStatus(null);
  if (screen.you) saveName(screen.you); // 伺服器接受的名字才記住
  renderChoices([]); // 上一局留下來、看不見但還佔著位置的選項也清掉：等人的畫面的按鈕在面板裡
  $("app").classList.toggle("wide", screen.view === "lobby"); // 大廳兩欄並排：上下的狀態列、輸入框跟著變寬
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
    top.append(tag("strong", "", room.title), tag("span", `room-state ${room.state}`, t(`room_state_${room.state}`, { count: room.members.length, max: seats })));
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

function roomPanel({ title, host, you, members, seats, choices }) {
  const panel = tag("section", "lobby-panel room-view");
  const head = tag("div", "lobby-head");
  head.append(tag("h1", "", title), tag("span", "lobby-count", t("room_seats", { count: members.length, max: seats })));
  const list = tag("ol", "seats");
  for (let i = 0; i < seats; i++) {
    const name = members[i];
    const seat = tag("li", "seat" + (name ? "" : " empty"));
    if (name) {
      const label = tag("span", "seat-name", name);
      if (name === you) label.append(tag("span", "you-tag", t("you_tag")));
      seat.append(tag("span", "avatar", initial(name)), label);
      if (name === host) seat.append(tag("span", "host-tag", t("host_tag")));
    } else {
      seat.append(tag("span", "avatar", ""), tag("span", "seat-name", t("seat_empty")));
    }
    list.append(seat);
  }
  const actions = tag("div", "room-actions");
  choices.forEach((label, i) => actions.append(actionButton(label, String(i + 1), i === 0 && choices.length > 1)));
  panel.append(head, list, actions);
  return panel;
}

// ---------- 選項與輸入 ----------

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
  if (!TOUCH) input.focus(); // 電腦：回到輸入框就能直接打字或按 Enter
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
  if (text === "/help") return helpSheet();
  if (text.startsWith("/")) return send({ t: "command", text });
  send({ t: "act", text });
});

input.addEventListener("keydown", (event) => {
  if (input.value || !(event.key === "ArrowDown" || event.key === "ArrowUp")) return;
  event.preventDefault();
  setActive(state.active + (event.key === "ArrowDown" ? 1 : state.active < 0 ? 0 : -1));
});

// 對話框沒開時，在頁面任何地方按 Enter 都能加速打字或繼續
document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !$("overlay").hidden || event.target === input) return;
  if (state.waitingEnter) { event.preventDefault(); state.waitingEnter(); }
  else if (state.typing) { event.preventDefault(); speedUp(); }
});

// ---------- 限時 ----------

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
  if (timer.left === 0) stopTimer(); // 時間到由房間處理，這裡只負責顯示
}, 100);

// ---------- 對話框 ----------

let closeCurrent = null;
const sheetQueue = []; // 已經有對話框開著時，後來的排隊，不會蓋掉正在回答的那個

// top：要打字的對話框（名字、故事前提）出現在畫面上方，手機的鍵盤從下面彈出來才不會蓋住
function openSheet(build, onClose, dismissible = true, top = false) {
  if (closeCurrent) {
    sheetQueue.push([build, onClose, dismissible, top]);
    return;
  }
  const overlay = $("overlay"), sheet = $("sheet");
  overlay.classList.toggle("top", top);
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
  // 要打字的對話框（名字）才聚焦到輸入框；手機上前提可以直接用預設的，不要一打開就跳出鍵盤
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

function field(type, id, placeholder) {
  const el = tag("input");
  el.type = type;
  el.id = id;
  el.placeholder = placeholder;
  return el;
}

function infoSheet(title, body) {
  openSheet((sheet, close) => {
    sheet.append(tag("h2", "", title), tag("div", "body", body), buttons([[t("close"), () => close(), true]]));
  });
}

function helpSheet() {
  infoSheet(t("menu_help"), t("help"));
}

// 名字能不能用由伺服器判斷，不能用時會帶著原因（error）再問一次
// 這個瀏覽器的識別碼：同一個瀏覽器用同一個名字再連進來時，伺服器讓新的連線取代舊的（不用等舊的斷線）。
// 用 getRandomValues 而不是 randomUUID：區網的 http 網址不是安全環境，沒有 randomUUID
function browserToken() {
  try {
    let token = localStorage.getItem("story-token");
    if (!token) {
      token = [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem("story-token", token);
    }
    return token;
  } catch (e) {
    return ""; // 存不了（例如無痕模式）：就不取代，跟以前一樣要等舊的連線斷掉
  }
}

// 上次用的名字只存在這個瀏覽器（跟外觀一樣），讀寫失敗（例如無痕模式）就當作沒有
function savedName() {
  try { return localStorage.getItem("story-name") || ""; } catch (e) { return ""; }
}

function saveName(name) {
  try { if (name) localStorage.setItem("story-name", name); else localStorage.removeItem("story-name"); } catch (e) {}
}

function nameSheet({ id, hint, error, max_len }) {
  openSheet((sheet, close) => {
    const name = field("text", "name-input", t("name_placeholder"));
    name.maxLength = max_len;
    name.value = savedName();
    const errorLine = tag("p", "error", error || "");
    const submit = () => close(name.value);
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    sheet.append(tag("h2", "", t("name_title")), tag("p", "hint", hint || t("name_hint")), name, errorLine);
    sheet.append(buttons([[t("leave"), () => close(null)], [t("enter"), submit, true]]));
  }, (value) => answer(id, value), false, true);
}


// 規則（題材選單、換不換掉文字框、送什麼指令）在伺服器的共用層（PremiseForm）：這裡只畫出來，把操作連同文字框的內容送過去，
// 照回覆換上新的開頭（text 是 null 時保持原樣）
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
    const show = (reply) => { if (reply.text !== null && reply.text !== undefined) area.value = reply.text; };

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
    sheet.append(tag("h2", "", t("premise_title")));
    if (options.length) sheet.append(select, genreHint);
    sheet.append(tag("p", "hint", t("premise_hint")), area, timedLabel, row);
  }, (value) => {
    state.premise = null;
    answer(id, value);
  }, false, true);
}

// ---------- 通知 ----------

function toast(text, { error = false, lasting = false, title = "" } = {}) {
  const el = tag("div", "toast" + (error ? " error" : ""));
  if (error) el.append(tag("b", "", title || t("error_title")));
  el.append(text);
  $("toasts").append(el);
  setTimeout(() => el.remove(), lasting ? 30000 : error ? 8000 : 3500);
}

// ---------- 選單 ----------

const menu = $("menu");
$("menu-button").addEventListener("click", (event) => {
  event.stopPropagation();
  menu.hidden = !menu.hidden;
  markTheme();
});
document.addEventListener("click", (event) => { if (!menu.hidden && !menu.contains(event.target)) menu.hidden = true; });
menu.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.command) {
    menu.hidden = true;
    if (!state.busy && !state.typing) send({ t: "command", text: button.dataset.command });
  } else if (button.dataset.local === "help") {
    menu.hidden = true;
    helpSheet();
  } else if (button.dataset.local === "rename") {
    saveName(""); // 忘掉名字再重新連線：會離開目前的房間，重新問名字
    state.exited = true;
    location.reload();
  } else if (button.dataset.themeChoice) {
    const choice = button.dataset.themeChoice;
    if (choice === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = choice;
    try { localStorage.setItem("story-theme", choice); } catch (e) {}
    markTheme();
  }
});

function markTheme() {
  const current = document.documentElement.dataset.theme || "system";
  menu.querySelectorAll("[data-theme-choice]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoice === current)));
}

// 通知要出現在下方選項區的上面：記下選項區的高度
new ResizeObserver(() => document.documentElement.style.setProperty("--dock-height", `${$("dock").offsetHeight}px`)).observe($("dock"));

connect();
