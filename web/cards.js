// Standalone card editor (/cards): add House cards to the library with no
// game running. Talks to the library HTTP API rather than a game socket.
import { esc } from "/static/shared/cardview.js";
import { wireEditor } from "/static/shared/cardeditor.js";

const AUTHOR_KEY = "cardbox_author";
const authorEl = document.getElementById("author");
try {
  authorEl.value = localStorage.getItem(AUTHOR_KEY) || "";
} catch {
  /* fine */
}
authorEl.addEventListener("input", () => {
  try {
    localStorage.setItem(AUTHOR_KEY, authorEl.value);
  } catch {
    /* fine */
  }
});

function toast(text) {
  const host = document.getElementById("toast-host");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  host.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}

const added = [];
function renderAdded() {
  const panel = document.getElementById("added-panel");
  const list = document.getElementById("added-list");
  panel.classList.toggle("hidden", added.length === 0);
  list.innerHTML = added
    .map(
      (c) =>
        `<div class="lib-row"><span class="badge">${c.kind}</span><span class="text">${esc(c.text)}</span></div>`
    )
    .join("");
}

wireEditor(document.getElementById("editor-root"), {
  onSubmit: async (kind, text) => {
    const author = authorEl.value.trim();
    if (!author) {
      authorEl.focus();
      return { ok: false, message: "Put your name in first so we know who to blame." };
    }
    let res;
    try {
      res = await fetch("/api/library/cards", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, text, author }),
      });
    } catch {
      return { ok: false, message: "Couldn't reach the server." };
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, message: data.error || "Couldn't add that card." };
    if (data.is_new) {
      added.unshift(data);
      renderAdded();
      toast("Card added!");
    } else {
      toast("That one's already in the deck.");
    }
    return { ok: true };
  },
});
