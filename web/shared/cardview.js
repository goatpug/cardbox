// Shared rendering helpers for black-card blank-filling (§6.2 rendering rule).

export function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

export function renderBlankTemplate(text) {
  return esc(text).replace(/_+/g, "<blank></blank>");
}

export function hasBlanks(text) {
  return /_+/.test(text ?? "");
}

// Replaces the Nth blank with the Nth card of the submission, styled distinctly.
// Only meaningful when hasBlanks(blackText) — see renderSubmission below.
export function composeSentence(blackText, cards) {
  const parts = blackText.split(/(_+)/g);
  let idx = 0;
  let html = "";
  for (const part of parts) {
    if (/^_+$/.test(part)) {
      const c = cards[idx++];
      html += `<span class="fill">${esc(c ? c.text : "___")}</span>`;
    } else {
      html += esc(part);
    }
  }
  return html;
}

// How to render one revealed submission against its black card (§6.2).
// Fill-in-the-blank prompts compose the full joke sentence — the same white
// card reads completely differently depending on the prompt, which is the
// whole comedic mechanism, so repeating the prompt-with-blank-filled is the
// point. A question prompt is already pinned on screen the whole round, so
// repeating it on every submission is just noise — show the plain answer(s)
// as a white card instead.
export function renderSubmission(blackText, cards) {
  if (hasBlanks(blackText)) {
    return {
      className: "card black",
      html: `<div class="card-text">${composeSentence(blackText, cards)}</div>`,
    };
  }
  const text = cards.map((c) => esc(c.text)).join(" ");
  return { className: "card white", html: `<div class="card-text">${text}</div>` };
}
