// The custom-card editor, shared by the in-game phone sheet (play.js) and the
// standalone /cards page (cards.js). Tabs, live preview, character counts and
// the client-side sanity checks live here; the caller decides where a card
// goes (game socket vs. library HTTP API) via `onSubmit`.
import { renderBlankTemplate } from "/static/shared/cardview.js";

const TEXTAREA_STYLE =
  "width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:0.7em;";

export function editorMarkup() {
  return `
    <div class="editor-tabs">
      <button id="tab-white" class="active">White card</button>
      <button id="tab-black">Black card</button>
    </div>

    <div id="editor-white">
      <p class="muted">Write a noun or gerund — a thing or a doing. "A disappointing salad." "Crying at the gym."</p>
      <textarea id="white-text" maxlength="80" rows="2" style="${TEXTAREA_STYLE}"></textarea>
      <div class="char-count"><span id="white-count">0</span>/80</div>
      <div class="preview-card"><div class="card white"><div class="card-text" id="white-preview">…</div></div></div>
      <button id="btn-add-white" class="big">Add white card</button>
    </div>

    <div id="editor-black" class="hidden">
      <p class="muted">Fill-in-the-blank ("_ ruined Thanksgiving.") or a question ("What's my secret power?"). It needs to make sense with a thing ("Bees") OR an action ("Crying at the gym") in the blank.</p>
      <textarea id="black-text" maxlength="140" rows="2" style="${TEXTAREA_STYLE}"></textarea>
      <div class="char-count"><span id="black-count">0</span>/140</div>
      <div class="preview-card"><div class="card black"><div class="card-text" id="black-preview">…</div></div></div>
      <button id="btn-add-black" class="big">Add black card</button>
    </div>

    <div id="editor-error" class="hidden" style="color:var(--danger)"></div>`;
}

// `onSubmit(kind, text)` must return a Promise of `{ ok, message? }`. On ok
// the textarea is cleared; otherwise `message` is shown under the editor.
export function wireEditor(root, { onSubmit }) {
  root.innerHTML = editorMarkup();
  const $ = (id) => root.querySelector(`#${id}`);
  const err = $("editor-error");

  const showError = (msg) => {
    err.textContent = msg;
    err.classList.remove("hidden");
  };

  function switchTab(kind) {
    $("tab-white").classList.toggle("active", kind === "white");
    $("tab-black").classList.toggle("active", kind === "black");
    $("editor-white").classList.toggle("hidden", kind !== "white");
    $("editor-black").classList.toggle("hidden", kind !== "black");
    err.classList.add("hidden");
  }
  $("tab-white").addEventListener("click", () => switchTab("white"));
  $("tab-black").addEventListener("click", () => switchTab("black"));

  const whiteText = $("white-text");
  whiteText.addEventListener("input", () => {
    $("white-count").textContent = whiteText.value.length;
    $("white-preview").textContent = whiteText.value || "…";
  });
  const blackText = $("black-text");
  blackText.addEventListener("input", () => {
    $("black-count").textContent = blackText.value.length;
    $("black-preview").innerHTML = renderBlankTemplate(blackText.value || "…");
  });

  let busy = false;
  async function submit(kind, textEl, btn) {
    if (busy) return;
    const text = textEl.value.trim();
    err.classList.add("hidden");
    if (!text) return showError("Write something first.");
    if (kind === "black" && !text.includes("_") && !text.endsWith("?")) {
      return showError("Needs a blank ('_') or must end with '?'.");
    }
    busy = true;
    btn.disabled = true;
    try {
      const result = await onSubmit(kind, text);
      if (result.ok) {
        textEl.value = "";
        textEl.dispatchEvent(new Event("input"));
      } else {
        showError(result.message || "Couldn't add that card.");
      }
    } finally {
      busy = false;
      btn.disabled = false;
    }
  }
  $("btn-add-white").addEventListener("click", () => submit("white", whiteText, $("btn-add-white")));
  $("btn-add-black").addEventListener("click", () => submit("black", blackText, $("btn-add-black")));

  return { switchTab, showError };
}
