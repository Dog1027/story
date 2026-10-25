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
  premise: null, // 開著的前提對話框
  exited: false,
};

// ---------- 連線 ----------

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => { input.placeholder = ""; };
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
  lobby({ title, members }) {
    const box = $("status");
    box.replaceChildren();
    const line = tag("div", "lobby", title + "　");
    members.forEach((m, i) => { if (i) line.append(" · "); line.append(tag("strong", "", m)); });
    box.append(line);
    $("turn").textContent = "";
    $("mode").hidden = true;
  },
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
  name(message) { nameSheet(message); },
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
function nameSheet({ id, hint, error, max_len }) {
  openSheet((sheet, close) => {
    const name = field("text", "name-input", t("name_placeholder"));
    name.maxLength = max_len;
    const errorLine = tag("p", "error", error || "");
    const submit = () => close(name.value);
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    sheet.append(tag("h2", "", t("name_title")), tag("p", "hint", hint || t("name_hint")), name, errorLine);
    sheet.append(buttons([[t("leave"), () => close(null)], [t("enter"), submit, true]]));
  }, (value) => answer(id, value), false, true);
}

const GENRE_AUTO = "auto", GENRE_NONE = "none"; // 題材的兩個特別選項（核心的代號）

function premiseSheet({ id, default: initial, timed, genre, genres }) {
  openSheet((sheet, close) => {
    const descriptions = Object.fromEntries(genres);
    let latest = 0, nextReq = 0, current = initial;
    const squash = (text) => text.split(/\s+/).join(" ").trim();

    const area = tag("textarea");
    area.id = "premise-input";
    area.placeholder = t("premise_placeholder");
    area.value = initial;
    // 換了預設的開頭：玩家還沒改過文字框（或 replace）就換上新的，改過的就保留玩家寫的
    const setDefault = (text, replace = false) => {
      if (replace || ["", squash(current)].includes(squash(area.value))) area.value = text;
      current = text;
    };
    area.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); start(); } });

    const timedBox = tag("input");
    timedBox.type = "checkbox";
    timedBox.id = "timed-input";
    timedBox.checked = timed;
    const timedLabel = tag("label", "check");
    timedLabel.append(timedBox, t("timed_option"));

    const select = tag("select");
    select.id = "genre-input";
    const genreHint = tag("p", "hint");
    const describe = (value) => {
      genreHint.textContent = value === GENRE_AUTO ? t("genre_auto_hint")
        : value === GENRE_NONE ? t("genre_none_hint") : descriptions[value] || "";
    };
    if (genres.length) {
      for (const [label, value] of [[t("genre_auto_option"), GENRE_AUTO], [t("genre_none_option"), GENRE_NONE], ...genres.map(([n]) => [t("genre_option", { name: n }), n])]) {
        const option = tag("option", "", label);
        option.value = value;
        select.append(option);
      }
      select.value = [GENRE_AUTO, GENRE_NONE, ...genres.map(([n]) => n)].includes(genre) ? genre : GENRE_AUTO;
      describe(select.value);
    }
    const chosenGenre = () => (genres.length ? select.value : genre);

    // 送指令給核心（換題材、換一個、幫我想），等 premise_update；被後面的操作取代的舊結果就不用
    const pending = {};
    const request = (commands, latestOnly = true) => new Promise((resolve) => {
      const req = ++nextReq;
      if (latestOnly) latest = req;
      pending[req] = (reply) => resolve(!latestOnly || req === latest ? reply : null);
      send({ t: "premise_ask", req, commands });
    });
    state.premise = { update: (reply) => { const done = pending[reply.req]; delete pending[reply.req]; if (done) done(reply); } };

    select.addEventListener("change", async () => {
      describe(select.value);
      const reply = await request([`/genre ${select.value}`]);
      if (reply && !reply.error) setDefault(reply.default);
    });

    const reroll = tag("button", "btn", t("reroll"));
    reroll.type = "button";
    reroll.onclick = async () => {
      const reply = await request([`/genre ${chosenGenre()}`, "/random"]);
      if (reply && !reply.error) setDefault(reply.default, true); // 按了「換一個」：文字框一定換掉
    };
    const suggest = tag("button", "btn", t("suggest"));
    suggest.type = "button";
    suggest.onclick = async () => {
      suggest.disabled = true;
      suggest.textContent = t("thinking");
      const reply = await request([`/genre ${chosenGenre()}`, "/suggest"], false);
      suggest.disabled = false;
      suggest.textContent = t("suggest");
      if (reply.error) toast(reply.error, { error: true, title: t("suggest_failed") });
      else { setDefault(reply.suggestion, true); if (!TOUCH) area.focus(); }
    };
    const startButton = tag("button", "btn primary", t("start"));
    startButton.type = "button";
    const start = () => close([area.value.trim() || current, timedBox.checked, chosenGenre()]);
    startButton.onclick = start;

    const row = tag("div", "buttons");
    reroll.classList.add("spacer");
    row.append(reroll, suggest, startButton);
    sheet.append(tag("h2", "", t("premise_title")));
    if (genres.length) sheet.append(select, genreHint);
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
