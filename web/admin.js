import { esc } from "/static/shared/cardview.js";

let packs = [];
let selectedPack = "house";

async function loadPacks() {
  const res = await fetch("/api/library/packs");
  packs = await res.json();
  renderPacks();
  loadCards();
}

function renderPacks() {
  const el = document.getElementById("pack-list");
  el.innerHTML = "";
  for (const p of packs) {
    const row = document.createElement("div");
    row.className = "lib-row";
    row.innerHTML = `
      <span class="text" style="cursor:pointer;${p.id === selectedPack ? "font-weight:700" : ""}">
        ${p.id === selectedPack ? "▸ " : ""}${esc(p.name)}
        <span class="muted">(${p.white_count}w / ${p.black_count}b)</span>
      </span>
      <a href="/api/library/packs/${p.id}/export"><button class="secondary icon">⇩</button></a>
    `;
    row.querySelector(".text").addEventListener("click", () => {
      selectedPack = p.id;
      renderPacks();
      loadCards();
    });
    el.appendChild(row);
  }
}

async function loadCards() {
  const heading = document.getElementById("cards-heading");
  const pack = packs.find((p) => p.id === selectedPack);
  heading.textContent = pack ? `Cards in ${pack.name}` : "Cards";

  const res = await fetch(`/api/library/packs/${selectedPack}/cards`);
  const cards = await res.json();
  const el = document.getElementById("card-list");
  el.innerHTML = "";
  if (!cards.length) {
    el.innerHTML = '<p class="muted">No cards in this pack yet.</p>';
    return;
  }
  for (const c of cards) {
    const row = document.createElement("div");
    row.className = "lib-row";
    row.innerHTML = `
      <span class="badge">${c.kind === "black" ? "⬛" : "⬜"}</span>
      <span class="text">${esc(c.text)}${c.author ? ` <span class="author">— ${esc(c.author)}</span>` : ""}</span>
      <button class="danger icon" data-del="${c.id}">🗑</button>
    `;
    el.appendChild(row);
  }
  el.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this card? It won't appear in future games (in-flight copies still play out).")) return;
      await fetch(`/api/library/cards/${btn.dataset.del}`, { method: "DELETE" });
      loadPacks();
    });
  });
}

loadPacks();
