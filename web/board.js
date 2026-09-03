import { GameSocket } from "/static/shared/ws.js";
import { esc, renderBlankTemplate, renderSubmission } from "/static/shared/cardview.js";

const HAND_SIZE_OPTIONS = [5, 6, 7, 8, 9, 10];
const SCORE_TARGET_OPTIONS = [3, 5, 7, 10, 15, 20, "endless"];
const TIMER_OPTIONS = [
  [null, "Off"],
  [60, "60s"],
  [90, "90s"],
  [120, "120s"],
];

let boardCode = (location.pathname.split("/")[2] || "").toUpperCase();
if (boardCode === "NEW") boardCode = "";

let state = null;
let packsMeta = [];

function toast(text) {
  const host = document.getElementById("toast-host");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  host.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

const socket = new GameSocket(`/ws/board/${boardCode || "new"}`, {
  onOpen() {
    socket.send("claim_board", { code: boardCode });
  },
  onMessage(type, data) {
    if (type === "joined") {
      boardCode = data.code;
      history.replaceState(null, "", `/board/${boardCode}`);
      document.getElementById("room-code").textContent = boardCode;
      const url = `${location.origin}/play/${boardCode}`;
      document.getElementById("join-url").textContent = url;
      renderQr(url);
      loadLibrary();
    } else if (type === "state") {
      state = data;
      render();
    } else if (type === "toast") {
      toast(data.text);
    } else if (type === "error") {
      if (data.code === "BOARD_TAKEN_OVER") {
        document.getElementById("board").classList.add("hidden");
        document.getElementById("taken-over").classList.remove("hidden");
        socket.close();
      } else {
        toast(`⚠ ${data.message}`);
      }
    }
  },
});

function renderQr(url) {
  const qr = window.qrcode(0, "M");
  qr.addData(url);
  qr.make();
  document.getElementById("qr").innerHTML = qr.createSvgTag(4, 4);
}

// ------------------------------------------------------------------ render

function render() {
  document.getElementById("board").classList.remove("hidden");
  const phase = state.phase;
  for (const id of ["view-lobby", "view-round", "view-round-end", "view-game-over"]) {
    document.getElementById(id).classList.add("hidden");
  }
  const roundBadge = document.getElementById("round-badge");
  if (phase === "LOBBY") {
    roundBadge.classList.add("hidden");
  } else {
    roundBadge.classList.remove("hidden");
    document.getElementById("round-no").textContent = state.round_no;
  }

  if (phase === "LOBBY") {
    document.getElementById("view-lobby").classList.remove("hidden");
    renderLobby();
  } else if (phase === "SUBMITTING" || phase === "REVEALING" || phase === "JUDGING") {
    document.getElementById("view-round").classList.remove("hidden");
    renderRound();
  } else if (phase === "ROUND_END") {
    document.getElementById("view-round-end").classList.remove("hidden");
    renderRoundEnd();
  } else if (phase === "GAME_OVER") {
    document.getElementById("view-game-over").classList.remove("hidden");
    renderGameOver();
  }

  renderScoreboard();
  renderCzarPreview();
}

function renderScoreboard() {
  const el = document.getElementById("scoreboard");
  el.innerHTML = "";
  const sorted = [...state.players].sort((a, b) => b.score - a.score);
  for (const p of sorted) {
    const row = document.createElement("div");
    row.className = "entry" + (p.kicked ? " kicked" : "");
    row.innerHTML = `
      <span class="dot ${p.connected ? "on" : "off"}"></span>
      <span class="name">${esc(p.name)}${p.is_czar ? ' <span class="crown">♛</span>' : ""}</span>
      <span class="score">${p.score}</span>
    `;
    el.appendChild(row);
  }
}

function renderCzarPreview() {
  const panel = document.getElementById("czar-preview-panel");
  if (state.phase === "LOBBY" || !state.czar_order.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const byId = Object.fromEntries(state.players.map((p) => [p.id, p]));
  const idx = state.czar_order.indexOf(state.players.find((p) => p.is_czar)?.id);
  const order = state.czar_order;
  const cur = state.players.find((p) => p.is_czar);
  const upcoming = [];
  if (idx >= 0) {
    for (let i = 1; i <= 3 && i < order.length; i++) {
      const p = byId[order[(idx + i) % order.length]];
      if (p) upcoming.push(p.name);
    }
  }
  document.getElementById("czar-preview").textContent = cur
    ? `${cur.name}${upcoming.length ? " — next: " + upcoming.join(", ") : ""}`
    : "—";
}

// --------------------------------------------------------------------- lobby

function renderLobby() {
  const list = document.getElementById("lobby-players");
  list.innerHTML = "";
  const active = state.players.filter((p) => !p.kicked);
  document.getElementById("player-count").textContent = `${active.length} joined`;
  for (const p of state.players) {
    const row = document.createElement("div");
    row.className = "entry" + (p.kicked ? " kicked" : "");
    row.innerHTML = `
      <span class="dot ${p.connected ? "on" : "off"}"></span>
      <span class="name">${esc(p.name)}</span>
      ${p.kicked ? "" : '<button class="ghost icon" data-kick="' + p.id + '">✕</button>'}
    `;
    list.appendChild(row);
  }
  list.querySelectorAll("[data-kick]").forEach((btn) => {
    btn.addEventListener("click", () => socket.send("kick_player", { player_id: btn.dataset.kick }));
  });

  document.getElementById("btn-start-game").disabled = active.length < 3;
  document.getElementById("btn-start-game").textContent =
    active.length < 3 ? `Start game (need 3+ players, have ${active.length})` : "Start game";

  renderCzarOrderEditor();
  renderSettingsForm();
  renderPackToggles();
}

function renderCzarOrderEditor() {
  const el = document.getElementById("czar-order-editor");
  el.innerHTML = "";
  const byId = Object.fromEntries(state.players.map((p) => [p.id, p]));
  const order = state.czar_order.length
    ? state.czar_order
    : state.players.filter((p) => !p.kicked).map((p) => p.id);

  order.forEach((pid, i) => {
    const p = byId[pid];
    if (!p) return;
    const row = document.createElement("div");
    row.className = "row-item";
    row.draggable = true;
    row.dataset.pid = pid;
    row.innerHTML = `
      <span class="grow">${esc(p.name)}</span>
      <span class="arrows">
        <button class="ghost icon" data-up="${pid}" ${i === 0 ? "disabled" : ""}>↑</button>
        <button class="ghost icon" data-down="${pid}" ${i === order.length - 1 ? "disabled" : ""}>↓</button>
      </span>
    `;
    el.appendChild(row);
  });

  el.querySelectorAll("[data-up]").forEach((btn) =>
    btn.addEventListener("click", () => moveCzar(btn.dataset.up, -1))
  );
  el.querySelectorAll("[data-down]").forEach((btn) =>
    btn.addEventListener("click", () => moveCzar(btn.dataset.down, 1))
  );

  let dragPid = null;
  el.querySelectorAll(".row-item").forEach((row) => {
    row.addEventListener("dragstart", () => (dragPid = row.dataset.pid));
    row.addEventListener("dragover", (e) => e.preventDefault());
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      if (!dragPid || dragPid === row.dataset.pid) return;
      const cur = state.czar_order.length
        ? [...state.czar_order]
        : state.players.filter((p) => !p.kicked).map((p) => p.id);
      const from = cur.indexOf(dragPid);
      const to = cur.indexOf(row.dataset.pid);
      cur.splice(to, 0, cur.splice(from, 1)[0]);
      socket.send("update_settings", { czar_order: cur });
    });
  });
}

function moveCzar(pid, delta) {
  const cur = state.czar_order.length
    ? [...state.czar_order]
    : state.players.filter((p) => !p.kicked).map((p) => p.id);
  const i = cur.indexOf(pid);
  const j = i + delta;
  if (j < 0 || j >= cur.length) return;
  [cur[i], cur[j]] = [cur[j], cur[i]];
  socket.send("update_settings", { czar_order: cur });
}

function fillSelectOnce(select, options, toLabel) {
  if (select.dataset.filled) return;
  select.dataset.filled = "1";
  for (const opt of options) {
    const o = document.createElement("option");
    o.value = String(opt);
    o.textContent = toLabel ? toLabel(opt) : String(opt);
    select.appendChild(o);
  }
}

function renderSettingsForm() {
  const s = state.settings;
  const handSel = document.getElementById("setting-hand-size");
  const scoreSel = document.getElementById("setting-score-target");
  const czarTimerSel = document.getElementById("setting-czar-timer");
  const subTimerSel = document.getElementById("setting-submission-timer");

  fillSelectOnce(handSel, HAND_SIZE_OPTIONS);
  fillSelectOnce(scoreSel, SCORE_TARGET_OPTIONS, (v) => (v === "endless" ? "Endless" : String(v)));
  fillSelectOnce(czarTimerSel, TIMER_OPTIONS.map((t) => t[0]), (v) => TIMER_OPTIONS.find((t) => t[0] === v)[1]);
  fillSelectOnce(subTimerSel, TIMER_OPTIONS.map((t) => t[0]), (v) => TIMER_OPTIONS.find((t) => t[0] === v)[1]);

  handSel.value = String(s.hand_size);
  scoreSel.value = String(s.score_target);
  czarTimerSel.value = String(s.czar_pick_timer);
  subTimerSel.value = String(s.submission_timer);

  handSel.onchange = () => socket.send("update_settings", { hand_size: Number(handSel.value) });
  scoreSel.onchange = () =>
    socket.send("update_settings", {
      score_target: scoreSel.value === "endless" ? "endless" : Number(scoreSel.value),
    });
  czarTimerSel.onchange = () =>
    socket.send("update_settings", {
      czar_pick_timer: czarTimerSel.value === "null" ? null : Number(czarTimerSel.value),
    });
  subTimerSel.onchange = () =>
    socket.send("update_settings", {
      submission_timer: subTimerSel.value === "null" ? null : Number(subTimerSel.value),
    });
}

async function loadLibrary() {
  try {
    const res = await fetch("/api/library/packs");
    packsMeta = await res.json();
    renderPackToggles();
  } catch {
    /* offline-ish; ignore */
  }
}

function renderPackToggles() {
  if (!state) return;
  const el = document.getElementById("pack-toggles");
  el.innerHTML = "";
  for (const pack of packsMeta) {
    const on = state.settings.enabled_packs[pack.id] ?? pack.on_by_default;
    const label = document.createElement("label");
    label.innerHTML = `
      <input type="checkbox" ${on ? "checked" : ""} data-pack="${pack.id}" />
      ${esc(pack.name)} <span class="muted">(${pack.white_count}w / ${pack.black_count}b)</span>
    `;
    el.appendChild(label);
  }
  el.querySelectorAll("input[data-pack]").forEach((input) => {
    input.addEventListener("change", () => {
      const enabled = { ...state.settings.enabled_packs };
      enabled[input.dataset.pack] = input.checked;
      socket.send("update_settings", { enabled_packs: enabled });
    });
  });
}

document.getElementById("btn-start-game").addEventListener("click", () => socket.send("start_game", {}));

// --------------------------------------------------------------------- round

function renderRound() {
  const bc = state.black_card;
  document.getElementById("black-card-text").innerHTML = bc ? renderBlankTemplate(bc.text) : "";
  document.getElementById("black-card-pick").textContent = bc ? bc.pick : "1";

  const dw = document.getElementById("deck-warning");
  if (state.deck_warning) {
    dw.textContent = "⚠ " + state.deck_warning;
    dw.classList.remove("hidden");
  } else {
    dw.classList.add("hidden");
  }

  const nonCzarCount = state.players.filter((p) => p.is_playing && !p.kicked && !p.is_czar).length;
  const statusEl = document.getElementById("status-line");
  if (state.phase === "SUBMITTING") {
    statusEl.textContent = `Waiting for submissions… (${state.submission_count}/${nonCzarCount})`;
  } else if (state.phase === "REVEALING") {
    statusEl.textContent = "Czar is revealing from their phone…";
  } else if (state.phase === "JUDGING") {
    statusEl.textContent = "Czar is choosing a winner on their phone…";
  }

  const grid = document.getElementById("submission-grid");
  grid.innerHTML = "";
  if (state.phase === "SUBMITTING") {
    for (let i = 0; i < state.submission_count; i++) {
      const card = document.createElement("div");
      card.className = "card facedown";
      grid.appendChild(card);
    }
  } else {
    for (const entry of state.revealed) {
      const card = document.createElement("div");
      if (entry.revealed) {
        const { className, html } = renderSubmission(bc.text, entry.cards);
        card.className = className;
        card.innerHTML = html;
      } else {
        card.className = "card facedown";
      }
      grid.appendChild(card);
    }
  }

  const skipBtn = document.getElementById("btn-skip-czar");
  const czarConnected = state.players.find((p) => p.is_czar)?.connected;
  skipBtn.classList.toggle("hidden", czarConnected !== false);
}

document.getElementById("btn-skip-czar").addEventListener("click", () => socket.send("skip_czar", {}));

function renderRoundEnd() {
  const w = state.winner;
  document.getElementById("winner-heading").textContent = w ? `${w.name} won the round!` : "Round over";
  const grid = document.getElementById("winner-card-grid");
  grid.innerHTML = "";
  if (w) {
    const card = document.createElement("div");
    const { className, html } = renderSubmission(w.black_card_text, w.cards);
    card.className = className;
    card.innerHTML = html;
    grid.appendChild(card);
  }
}

document.getElementById("btn-next-round").addEventListener("click", () => socket.send("next_round", {}));

function renderGameOver() {
  const el = document.getElementById("final-standings");
  el.innerHTML = "";
  const sorted = [...state.players].filter((p) => !p.kicked).sort((a, b) => b.score - a.score);
  sorted.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "entry";
    row.innerHTML = `<span class="name">${i === 0 ? "🏆 " : ""}${esc(p.name)}</span><span class="score">${p.score}</span>`;
    el.appendChild(row);
  });
}

document.getElementById("btn-rematch").addEventListener("click", () => socket.send("rematch", {}));
