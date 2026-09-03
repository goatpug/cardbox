// Shared rendering helpers for black-card blank-filling (§6.2 rendering rule).

export function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

export function renderBlankTemplate(text) {
  return esc(text).replace(/_+/g, "<blank></blank>");
}

// Replaces the Nth blank with the Nth card of the submission, styled distinctly.
// Question cards (no blanks) render the submission below the card instead.
export function composeSentence(blackText, cards) {
  const parts = blackText.split(/(_+)/g);
  let idx = 0;
  let html = "";
  let anyBlank = false;
  for (const part of parts) {
    if (/^_+$/.test(part)) {
      anyBlank = true;
      const c = cards[idx++];
      html += `<span class="fill">${esc(c ? c.text : "___")}</span>`;
    } else {
      html += esc(part);
    }
  }
  if (!anyBlank && cards.length) {
    html += cards.map((c) => `<div class="fill">${esc(c.text)}</div>`).join("");
  }
  return html;
}
