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

// White cards are written as standalone sentences ("Bees.", "A haunted
// vibrator.") but get dropped into the middle of a black card's sentence, so
// the text needs fitting: drop the trailing period unless the blank ends the
// sentence, and lowercase the first letter unless the blank starts the
// sentence. Words that carry their own capitals ("DMV", "OnlyFans", "I'm")
// are left alone — a proper noun in first position is the one case this
// heuristic misses, and the deck avoids them.
export function fitFill(text, { atStart, atEnd }) {
  let t = (text ?? "").trim();
  if (!atEnd) t = t.replace(/\.$/, "");
  if (!atStart) {
    const first = t.split(/\s+/)[0] || "";
    const keepsCase = first === "I" || /^I['’]/.test(first) || /[A-Z]/.test(first.slice(1));
    if (!keepsCase) t = t.charAt(0).toLowerCase() + t.slice(1);
  }
  return t;
}

// Replaces the Nth blank with the Nth card of the submission, styled distinctly.
// Only meaningful when hasBlanks(blackText) — see renderSubmission below.
export function composeSentence(blackText, cards) {
  const parts = blackText.split(/(_+)/g);
  let idx = 0;
  let html = "";
  for (let p = 0; p < parts.length; p++) {
    const part = parts[p];
    if (/^_+$/.test(part)) {
      const c = cards[idx++];
      const before = parts.slice(0, p).join("");
      const after = parts.slice(p + 1).join("");
      // "Ends the sentence" means nothing but whitespace follows the blank —
      // a black card that supplies its own period ("…marriage? _.") also
      // wants the white card's period gone.
      const atStart = /(^|[.!?]\s*)$/.test(before);
      const atEnd = after.trim() === "";
      html += `<span class="fill">${c ? esc(fitFill(c.text, { atStart, atEnd })) : "___"}</span>`;
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
