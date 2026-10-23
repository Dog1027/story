// 網頁介面：只負責畫面。伺服器上的共用層決定什麼時候顯示什麼，這裡把每則訊息畫出來，再把玩家的輸入送回去。
// 訊息格式見 story/shells/web/view.py。
"use strict";

const CHAR_DELAY = 50; // 每個字的間隔（毫秒），大約一秒 20 個字
const FAST_FACTOR = 0.15; // 按一次 Enter 後，間隔縮成原本的幾倍
const PAUSE_AFTER = { "。": 250, "！": 250, "？": 250, "，": 100, "、": 80, "…": 150, "\n": 100 };
const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;
// 手機、平板：不要自動把焦點移到輸入框，不然鍵盤會一直跳出來
const TOUCH = matchMedia("(pointer: coarse)").matches || matchMedia("(hover: none)").matches;

const $ = (id) => document.getElementById(id);
const log = $("log"), input = $("input"), choicesList = $("choices");

const state = {
  ws: null,
  busy: false,
  typing: null, // 正在打字：{ speed, skip }
  narration: null, // 正在顯示的劇情：{ el, text, done, finished }（AI 還在寫時 text 會越來越長）
  waitingEnter: null, // 等玩家按 Enter：回覆的 id
  choices: [],
  active: -1, // 用 ↑↓ 移到的選項
  follow: true, // 故事區停在最底時，新內容出現就跟著捲
  busyLine: null,
  timer: null, // { total, left, pausable, last }
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
      input.placeholder = "連線中斷了，請重新整理頁面。";
      toast("和伺服器的連線中斷了，請重新整理頁面。", { error: true, lasting: true });
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
      el.append(tag("b", "", "故事前提"), premise);
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
    if (choicesList.classList.contains("hidden") && same(choices, state.choices)) {
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
  hint({ title, placeholder }) {
    $("choices-title").textContent = title === "接下來" ? "" : title;
    $("choices-title").hidden = title === "接下來";
    if (!state.waitingEnter) input.placeholder = placeholder;
  },
  status({ status }) { renderStatus(status); },
  lobby({ members }) {
    const box = $("status");
    box.replaceChildren();
    const line = tag("div", "lobby", "大廳　");
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
  timer({ seconds, pausable }) { startTimer(seconds, pausable); },
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
      sheet.append(tag("h2", "", title ? `結局：${title}` : "故事結束"), tag("p", "record", record));
      sheet.append(buttons([["離開", () => close(false)], ["再玩一次", () => close(true), true]]));
    }, (value) => answer(id, value), false);
  },
  name(message) { nameSheet(message); },
  api_key(message) { apiKeySheet(message); },
  premise(message) { premiseSheet(message); },
  premise_update(message) { if (state.premise) state.premise.update(message); },
  exit() {
    state.exited = true;
    sheetQueue.length = 0;
    closeSheet();
    setBusy(true);
    log.replaceChildren(tag("div", "exit-screen", "已經離開了。重新整理頁面就能再進來。"));
    renderChoices([]);
    input.placeholder = "已離開";
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
  $("turn").textContent = `第 ${status.turn} 回`; // 章回小說的「回」
  $("mode").hidden = !status.timed;
  $("mode").textContent = status.mode;
  for (const c of status.characters) {
    const row = tag("div", "status-row" + (c.alive ? "" : " fallen"));
    if (status.party) row.append(tag("span", "status-name", c.name));
    const chips = tag("div", "chips");
    if (!c.alive) chips.append(tag("span", "t-muted", "已倒下"));
    else {
      if (c.warning) chips.append(tag("span", "chip warning", `⚠ ${c.warning}`));
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

function startTimer(seconds, pausable) {
  state.timer = { total: seconds, left: seconds, pausable, last: performance.now() };
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
  $("timer-text").textContent = `${Math.ceil(left)} 秒`;
  $("timer").classList.toggle("urgent", left <= 5);
}

setInterval(() => {
  const timer = state.timer;
  if (!timer) return;
  const now = performance.now();
  const elapsed = (now - timer.last) / 1000;
  timer.last = now;
  // 開著對話框時暫停（線上多人大家共用一個倒數，不能暫停）
  if (state.busy || (timer.pausable && !$("overlay").hidden)) return;
  timer.left = Math.max(0, timer.left - elapsed);
  renderTimer();
  if (timer.left === 0) {
    stopTimer();
    send({ t: "timeout" });
  }
}, 100);

// ---------- 對話框 ----------

let closeCurrent = null;
const sheetQueue = []; // 已經有對話框開著時，後來的排隊，不會蓋掉正在回答的那個

// top：要打字的對話框（名字、key、故事前提）出現在畫面上方，手機的鍵盤從下面彈出來才不會蓋住
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
  // 要打字的對話框（名字、key）才聚焦到輸入框；手機上前提可以直接用預設的，不要一打開就跳出鍵盤
  const focus = sheet.querySelector(TOUCH ? "input[type=text], input[type=password]" : "textarea, input:not([type=checkbox]), .btn.primary");
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
    sheet.append(tag("h2", "", title), tag("div", "body", body), buttons([["關閉", () => close(), true]]));
  });
}

function helpSheet() {
  infoSheet("說明", [
    "選項：點一下，或在輸入框用 ↑↓ 選擇後按 Enter，也可以輸入數字。",
    "自由行動：直接在輸入框寫下你想做的事。",
    "文字顯示中：點故事區或按 Enter 加速，再按一次全部顯示。",
    "文字顯示中也可以往上捲回去看，捲回最底就繼續跟著新文字。",
    "",
    "右上角的 ⋯ 選單：",
    "程式記住的東西：背包、已確立的事實、重大事件、劇情摘要",
    "重新開始：放棄目前進度，開一個新故事",
    "外觀：跟隨系統、淺色或深色",
    "",
    "限時模式（開新故事時選擇）：情勢緊迫時會出現倒數，時間到就當作你遲疑了。單人時開著對話框倒數會暫停。",
  ].join("\n"));
}

function nameSheet({ id, hint, error }) {
  openSheet((sheet, close) => {
    const name = field("text", "name-input", "例如：阿明");
    name.maxLength = 20;
    const errorLine = tag("p", "error", error || "");
    const submit = () => { if (name.value.trim()) close(name.value.trim()); else errorLine.textContent = "請輸入名字。"; };
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    sheet.append(tag("h2", "", "你的名字"), tag("p", "hint", hint || "每個名字有自己的存檔，下次用同一個名字進來就能接著玩。"), name, errorLine);
    sheet.append(buttons([["離開", () => close(null)], ["進入", submit, true]]));
  }, (value) => answer(id, value), false, true);
}

function apiKeySheet({ id, reason }) {
  openSheet((sheet, close) => {
    const key = field("password", "key-input", "貼上 API key");
    const submit = () => { if (key.value.trim()) close(key.value.trim()); };
    key.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    const link = tag("p", "hint");
    link.append("可以到 ");
    const a = tag("a", "", "Google AI Studio");
    a.href = "https://aistudio.google.com/apikey";
    a.target = "_blank";
    a.rel = "noopener";
    link.append(a, " 免費申請。key 只用於這次連線，不會存到伺服器上；下次進來要重新輸入。");
    sheet.append(tag("h2", "", reason), link, key, buttons([["離開", () => close(null)], ["確定", submit, true]]));
  }, (value) => answer(id, value), false, true);
}

const GENRE_AUTO = "自動", GENRE_NONE = "不套用";

function premiseSheet({ id, default: initial, timed, genre, genres }) {
  openSheet((sheet, close) => {
    const descriptions = Object.fromEntries(genres);
    let latest = 0, nextReq = 0, current = initial;
    const squash = (text) => text.split(/\s+/).join(" ").trim();

    // 故事前提的文字框一開始就填好預設的開頭；玩家改了才用玩家寫的
    const area = tag("textarea");
    area.id = "premise-input";
    area.placeholder = "例如：你是一名在末日城市送信的郵差……";
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
    timedLabel.append(timedBox, "限時模式：情勢緊迫時，要在時間內做出決定");

    const select = tag("select");
    select.id = "genre-input";
    const genreHint = tag("p", "hint");
    const describe = (value) => {
      genreHint.textContent = value === GENRE_AUTO ? "依故事前提自動挑一個題材包，都不適合就不套用。"
        : value === GENRE_NONE ? "不套用題材，照一般的方式寫。" : descriptions[value] || "";
    };
    if (genres.length) {
      for (const [label, value] of [["題材：自動（依故事前提挑選）", GENRE_AUTO], ["題材：不套用", GENRE_NONE], ...genres.map(([n]) => [`題材：${n}`, n])]) {
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

    const reroll = tag("button", "btn", "換一個");
    reroll.type = "button";
    reroll.onclick = async () => {
      const reply = await request([`/genre ${chosenGenre()}`, "/random"]);
      if (reply && !reply.error) setDefault(reply.default, true); // 按了「換一個」：文字框一定換掉
    };
    const suggest = tag("button", "btn", "幫我想");
    suggest.type = "button";
    suggest.onclick = async () => {
      suggest.disabled = true;
      suggest.textContent = "構思中…";
      const reply = await request([`/genre ${chosenGenre()}`, "/suggest"], false);
      suggest.disabled = false;
      suggest.textContent = "幫我想";
      if (reply.error) toast(reply.error, { error: true, title: "AI 沒有想出開頭" });
      else { setDefault(reply.suggestion, true); if (!TOUCH) area.focus(); }
    };
    const startButton = tag("button", "btn primary", "開始");
    startButton.type = "button";
    const start = () => close([area.value.trim() || current, timedBox.checked, chosenGenre()]);
    startButton.onclick = start;

    const row = tag("div", "buttons");
    reroll.classList.add("spacer");
    row.append(reroll, suggest, startButton);
    // 由上到下：題材、題材介紹、故事前提、限時模式
    sheet.append(tag("h2", "", "新的故事"));
    if (genres.length) sheet.append(select, genreHint);
    sheet.append(tag("p", "hint", "故事前提：可以直接修改，或按「換一個」「幫我想」"), area, timedLabel, row);
  }, (value) => {
    state.premise = null;
    answer(id, value);
  }, false, true);
}

// ---------- 通知 ----------

function toast(text, { error = false, lasting = false, title = "" } = {}) {
  const el = tag("div", "toast" + (error ? " error" : ""));
  if (error) el.append(tag("b", "", title || "出錯了"));
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
