import { GameSocket } from "/static/shared/ws.js";
import { esc, hasBlanks, renderBlankTemplate, renderSubmission, composeSentence } from "/static/shared/cardview.js";
import { wireEditor } from "/static/shared/cardeditor.js";

const SESSION_KEY = "cardbox_session";

function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveSession(session) {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* private browsing etc — rejoin just won't survive a refresh */
  }
}

let session = loadSession();
const urlCode = (location.pathname.split("/")[2] || "").toUpperCase();
if (urlCode) document.getElementById("join-code").value = urlCode;

let state = null;
let selected = []; // ordered card ids chosen this round, before confirm
let lastSubmittedCards = []; // remembered locally to grey out after confirm (§5.5)
let pendingWinnerIndex = null;
// Reveal/judge view: which submission is currently slotted into the black
// card at the top of the phone. Follows the newest flip automatically; the
// Czar (or anyone) can tap a revealed submission to slot that one instead.
let focusIndex = null;
let seenRevealedCount = 0;
let pendingAddCard = null; // { kind, text, resolve } while an add_card is in flight

function toast(text) {
  const host = document.getElementById("toast-host");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  host.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

const socket = new GameSocket("/ws/play", {
  onOpen() {
    if (session) socket.send("rejoin", session);
  },
  onMessage(type, data) {
    if (type === "joined") {
      session = { code: data.code, player_id: data.player_id, token: data.token };
      saveSession(session);
      document.getElementById("screen-join").classList.add("hidden");
      document.getElementById("screen-kicked").classList.add("hidden");
      document.getElementById("screen-app").classList.remove("hidden");
      history.replaceState(null, "", `/play/${session.code}`);
    } else if (type === "state") {
      state = data;
      render();
    } else if (type === "toast") {
      toast(data.text);
    } else if (type === "error") {
      handleError(data);
    }
  },
});

function handleError(data) {
  if (pendingAddCard) {
    const pending = pendingAddCard;
    pendingAddCard = null;
    pending.resolve({ ok: false, message: data.message });
    return;
  }
  if (!session) {
    const err = document.getElementById("join-error");
    err.textContent = data.message;
    err.classList.remove("hidden");
    return;
  }
  if (data.code === "REJOIN_FAILED" || data.code === "ROOM_NOT_FOUND") {
    // stale session — fall back to the join form
    try {
      localStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
    session = null;
    document.getElementById("screen-app").classList.add("hidden");
    document.getElementById("screen-join").classList.remove("hidden");
    return;
  }
  toast(`⚠ ${data.message}`);
}

// --------------------------------------------------------------------- join

document.getElementById("btn-join").addEventListener("click", () => {
  const code = document.getElementById("join-code").value.trim().toUpperCase();
  const name = document.getElementById("join-name").value.trim();
  document.getElementById("join-error").classList.add("hidden");
  if (code.length !== 4) {
    const err = document.getElementById("join-error");
    err.textContent = "Room code must be 4 letters.";
    err.classList.remove("hidden");
    return;
  }
  if (!name) {
    const err = document.getElementById("join-error");
    err.textContent = "Enter your name.";
    err.classList.remove("hidden");
    return;
  }
  socket.send("join", { code, name });
});

document.getElementById("join-code").addEventListener("input", (e) => {
  e.target.value = e.target.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 4);
});

// ---------------------------------------------------------------- rendering

function me() {
  if (!state || !session) return null;
  return state.players.find((p) => p.id === session.player_id) || null;
}

function render() {
  const m = me();
  document.getElementById("board-disconnected").classList.toggle("hidden", state.board_connected !== false);

  if (m && m.kicked) {
    document.getElementById("screen-app").classList.add("hidden");
    document.getElementById("screen-kicked").classList.remove("hidden");
    return;
  }
  document.getElementById("screen-kicked").classList.add("hidden");

  const you = state.you || {};
  const phase = state.phase;
  const bc = state.black_card;
  const showingSubmissions = phase === "REVEALING" || phase === "JUDGING";
  if (!showingSubmissions) {
    focusIndex = null;
    seenRevealedCount = 0;
  } else {
    const revealedCount = (state.revealed || []).filter((e) => e.revealed).length;
    if (revealedCount !== seenRevealedCount) {
      seenRevealedCount = revealedCount;
      focusIndex = lastIndex(state.revealed, (e) => e.revealed);
    }
  }
  const focused = showingSubmissions && focusIndex !== null ? state.revealed[focusIndex] : null;
  const headerCard = document.getElementById("header-black-text");
  if (bc && focused?.revealed && hasBlanks(bc.text)) {
    headerCard.innerHTML = composeSentence(bc.text, focused.cards);
  } else {
    headerCard.innerHTML = bc ? renderBlankTemplate(bc.text) : "…";
  }

  document.getElementById("phase-status").textContent = statusText(phase, you);

  renderTimer();

  if (phase !== "SUBMITTING") selected = [];
  if (phase !== "SUBMITTING" || you.has_submitted) {
    // keep lastSubmittedCards until a fresh round starts
  }
  if (phase === "SUBMITTING" && !you.has_submitted) {
    lastSubmittedCards = [];
  }
  if (phase !== "JUDGING") pendingWinnerIndex = null;

  const area = document.getElementById("hand-area");
  const bar = document.getElementById("confirm-bar");
  area.innerHTML = "";
  bar.classList.add("hidden");

  if (phase === "LOBBY") {
    area.innerHTML = `<p class="muted center" style="margin-top:2em">Waiting for the host to start the game…</p>`;
  } else if (phase === "SUBMITTING") {
    renderSubmitting(you, area, bar);
  } else if (phase === "REVEALING" || phase === "JUDGING") {
    renderSubmissions(you, area, bar);
  } else if (phase === "ROUND_END") {
    renderRoundEnd(area);
  } else if (phase === "GAME_OVER") {
    renderGameOver(area);
  }
}

function statusText(phase, you) {
  if (phase === "LOBBY") return "Lobby";
  if (phase === "SUBMITTING") return you.is_czar ? "You're the Czar" : you.has_submitted ? "Submitted" : "Pick your card(s)";
  if (phase === "REVEALING") return you.is_czar ? "Reveal the submissions" : "Czar is revealing…";
  if (phase === "JUDGING") return you.is_czar ? "Pick a winner" : "Czar is choosing…";
  if (phase === "ROUND_END") return "Round over";
  if (phase === "GAME_OVER") return "Game over";
  return "";
}

function renderTimer() {
  const pill = document.getElementById("timer-pill");
  const s = state.settings;
  if (state.phase === "SUBMITTING" && s.submission_timer) {
    pill.textContent = `⏱ up to ${s.submission_timer}s`;
    pill.classList.remove("hidden");
  } else if (state.phase === "JUDGING" && s.czar_pick_timer) {
    pill.textContent = `⏱ ${s.czar_pick_timer}s`;
    pill.classList.remove("hidden");
    pill.classList.add("flash");
  } else {
    pill.classList.add("hidden");
    pill.classList.remove("flash");
  }
}

function renderSubmitting(you, area, bar) {
  if (you.is_czar) {
    const nonCzar = state.players.filter((p) => p.is_playing && !p.kicked && !p.is_czar).length;
    area.innerHTML = `
      <div class="full-screen-msg" style="min-height:40vh">
        <h2>You're the Czar</h2>
        <p class="muted">Sit back — everyone else is picking. (${state.submission_count}/${nonCzar} in)</p>
      </div>`;
    return;
  }

  if (you.has_submitted) {
    area.innerHTML = `<p class="muted center" style="margin-top:1em">Submitted — waiting for others…</p>`;
    const grid = document.createElement("div");
    grid.className = "hand-grid";
    for (const c of lastSubmittedCards) {
      const card = document.createElement("div");
      card.className = "card white submitted";
      card.innerHTML = `<div class="card-text">${esc(c.text)}</div>`;
      grid.appendChild(card);
    }
    area.appendChild(grid);
    return;
  }

  const pick = state.black_card?.pick ?? 1;
  const grid = document.createElement("div");
  grid.className = "hand-grid";
  for (const c of state.hand || []) {
    const card = document.createElement("div");
    const order = selected.indexOf(c.id);
    card.className = "card white" + (order >= 0 ? " selected" : "");
    card.innerHTML = `<div class="card-text">${esc(c.text)}</div>${order >= 0 ? `<span class="pick-order">${order + 1}</span>` : ""}`;
    card.addEventListener("click", () => {
      const i = selected.indexOf(c.id);
      if (i >= 0) {
        selected.splice(i, 1);
      } else if (selected.length < pick) {
        selected.push(c.id);
      }
      render();
    });
    grid.appendChild(card);
  }
  area.appendChild(grid);

  bar.classList.remove("hidden");
  document.getElementById("confirm-hint").textContent = `${selected.length}/${pick} selected`;
  const btn = document.getElementById("btn-confirm");
  btn.disabled = selected.length !== pick;
  btn.textContent = "Confirm";
  btn.onclick = () => {
    const hand = state.hand || [];
    lastSubmittedCards = selected.map((id) => hand.find((c) => c.id === id)).filter(Boolean);
    socket.send("submit", { card_ids: selected });
  };
}

function lastIndex(arr, pred) {
  for (let i = (arr || []).length - 1; i >= 0; i--) if (pred(arr[i])) return i;
  return null;
}

// REVEALING and JUDGING share one layout on the phone: the black card in the
// sticky header shows the focused submission slotted into its blanks, and the
// submissions themselves are listed below as plain white cards (one row per
// submission, `pick` cards wide) — face-down until the Czar flips them.
function renderSubmissions(you, area, bar) {
  const bc = state.black_card;
  const pick = bc?.pick ?? 1;
  const judging = state.phase === "JUDGING";
  const list = document.createElement("div");
  list.className = "sub-list" + (pick === 1 ? " single" : "");
  list.style.setProperty("--pick", pick);

  state.revealed.forEach((entry, i) => {
    const row = document.createElement("div");
    row.className = "sub-row";
    if (entry.revealed) {
      if (i === focusIndex) row.classList.add("focused");
      if (judging && pendingWinnerIndex === i) row.classList.add("selected");
      for (const c of entry.cards) {
        const card = document.createElement("div");
        card.className = "card white";
        card.innerHTML = `<div class="card-text">${esc(c.text)}</div>`;
        row.appendChild(card);
      }
      row.addEventListener("click", () => {
        focusIndex = i;
        if (judging && you.can_judge) pendingWinnerIndex = i;
        render();
      });
    } else {
      for (let k = 0; k < pick; k++) {
        const card = document.createElement("div");
        card.className = "card facedown";
        row.appendChild(card);
      }
      if (you.is_czar && you.reveal_cursor === i) {
        row.classList.add("next");
        row.addEventListener("click", () => socket.send("reveal_next", {}));
      }
    }
    list.appendChild(row);
  });
  area.appendChild(list);

  if (!judging && you.is_czar) {
    bar.classList.remove("hidden");
    document.getElementById("confirm-hint").textContent = "Tap the next face-down card, or:";
    const btn = document.getElementById("btn-confirm");
    btn.disabled = you.reveal_cursor === null || you.reveal_cursor === undefined;
    btn.textContent = "Flip next";
    btn.onclick = () => socket.send("reveal_next", {});
  } else if (judging && you.can_judge) {
    bar.classList.remove("hidden");
    document.getElementById("confirm-hint").textContent =
      pendingWinnerIndex === null ? "Tap the funniest one" : "Confirm this winner?";
    const btn = document.getElementById("btn-confirm");
    btn.disabled = pendingWinnerIndex === null;
    btn.textContent = "Pick winner";
    btn.onclick = () => socket.send("pick_winner", { submission_index: pendingWinnerIndex });
  }
}

function renderRoundEnd(area) {
  const w = state.winner;
  if (!w) {
    area.innerHTML = `<p class="muted center" style="margin-top:2em">Round over.</p>`;
    return;
  }
  area.innerHTML = `<div class="full-screen-msg" style="min-height:30vh"><h2>${esc(w.name)} won with:</h2></div>`;
  const grid = document.createElement("div");
  grid.className = "hand-grid";
  const card = document.createElement("div");
  const { className, html } = renderSubmission(w.black_card_text, w.cards);
  card.className = className;
  card.innerHTML = html;
  grid.appendChild(card);
  area.appendChild(grid);
}

function renderGameOver(area) {
  const sorted = [...state.players].filter((p) => !p.kicked).sort((a, b) => b.score - a.score);
  const winner = sorted[0];
  area.innerHTML = `<div class="full-screen-msg"><h2>🏆 ${winner ? esc(winner.name) + " wins!" : "Game over"}</h2><p class="muted">Ask the host to start a rematch from the Board.</p></div>`;
  const board = document.createElement("div");
  board.className = "scoreboard";
  board.style.maxWidth = "20em";
  board.style.margin = "0 auto";
  for (const p of sorted) {
    const row = document.createElement("div");
    row.className = "entry";
    row.innerHTML = `<span class="name">${esc(p.name)}</span><span class="score">${p.score}</span>`;
    board.appendChild(row);
  }
  area.appendChild(board);
}

// ------------------------------------------------------------------ editor

const sheet = document.getElementById("editor-sheet");
document.getElementById("btn-open-editor").addEventListener("click", () => sheet.classList.remove("hidden"));
document.getElementById("editor-close").addEventListener("click", () => sheet.classList.add("hidden"));

// The server only answers add_card with an error; silence for a beat means
// it landed (§5.6). The shared editor handles tabs, preview and validation.
wireEditor(document.getElementById("editor-root"), {
  onSubmit: (kind, text) =>
    new Promise((resolve) => {
      pendingAddCard = { kind, text, resolve };
      socket.send("add_card", { kind, text });
      setTimeout(() => {
        if (pendingAddCard && pendingAddCard.resolve === resolve) {
          pendingAddCard = null;
          toast("Card added!");
          resolve({ ok: true });
        }
      }, 700);
    }),
});
