# Cardbox — Design Specification

A browser-based Cards Against Humanity–style party game played "Jackbox style":
one shared **Board** screen that everyone watches (via Discord screen share),
and each player's **phone** as their private hand controller, joined with a
short room code.

This document is a build-ready spec. It defines the product behavior, the
architecture, the data model, the client/server protocol, and the edge cases.
It deliberately avoids prescribing visual design beyond layout requirements.

---

## 1. Overview

### 1.1 How a game night works

1. The group is already on a Discord voice/video call. One person (the
   **host**) opens the Board page in a laptop browser and shares that window
   over Discord.
2. The Board displays a **room code** (e.g. `GOAT`). Each player opens the
   game URL on their phone, enters the room code and their **name**, and lands
   in their private hand view.
3. On the Board, the host arranges the **Card Czar rotation order** and starts
   the game.
4. Each round: the Board shows a black card; every non-Czar player picks white
   card(s) from their phone; submissions appear face-down on the Board; the
   Czar flips them one at a time (from their phone), then picks a winner; the
   winner scores a point.
5. The scoreboard is always visible on the Board. Play continues until a
   configurable score target is reached, or forever if the target is "endless".

### 1.2 Core requirements (from the product owner)

- Web browser only — no installs. Board on a laptop, players on phones.
- Join a game with a shared code + player name.
- Players can add **custom cards** of both types at any time:
  - **White cards**: a noun or gerund — single words ("Bees") or phrase
    constructions ("Slapping a biscuit out of a toddler's hand").
  - **Black cards**: fill-in-the-blank statements ("_ is the leading cause of
    divorce.") or questions ("What's my secret power?").
- Scoreboard (points per player) lives on the shared Board.
- Card Czar rotation order is settable on the Board.
- **Python** for the game logic. UI language is builder's choice — this spec
  recommends plain HTML/CSS/JavaScript (see §3).

### 1.3 Non-goals (v1)

- No accounts, no persistence between game nights beyond saved card packs.
- No matchmaking, no multiple simultaneous public games discovery (the server
  *does* support multiple concurrent rooms, but they're joined by code only).
- No in-app audio/video chat — Discord handles all voice.
- No moderation/filtering of card text. This is a private game among friends.
- No native apps. Mobile browser only.

---

## 2. Roles, screens, and devices

| Screen | Device | Audience | Purpose |
|---|---|---|---|
| **Board** | Host's laptop, screen-shared | Everyone | Public game state: room code, black card, face-down/revealed submissions, scoreboard, Czar order, round status |
| **Player** | Each player's phone | That player only | Join form, private hand, card submission, Czar controls, custom card editor |

Notes:

- The **host** is whoever opens the Board. The Board is not a player; the host
  also joins from their own phone to play.
- There is exactly one Board per room. If a second Board connects to the same
  room, it takes over (the old one shows "Board opened elsewhere"). This makes
  recovery trivial if the host's browser crashes.
- The Board is the only place game **settings** can be changed (Czar order,
  score target, hand size, etc.). Rationale: settings changes are public acts
  and the Board is the shared, visible surface.

---

## 3. Technology choices

### 3.1 Backend — Python

- **Python 3.12+**, **FastAPI** + **uvicorn**, using FastAPI's native
  WebSocket support. Single process, single event loop (asyncio).
- All game state is **in-memory** (a dict of `Room` objects). No database.
  A crashed server means a lost game night in the worst case; see §8.6 for a
  cheap snapshot mitigation.
- Card packs (base deck + saved custom packs) are **JSON files on disk**
  loaded at startup (§6.4).
- The same FastAPI app serves the static frontend files, so the whole game is
  one process: `uvicorn cardbox.app:app`.

Why: a party game for ~4–10 friends needs no horizontal scaling, no job
queues, and no ORM. One asyncio process comfortably handles dozens of rooms.
The game logic (deck, rounds, scoring, state machine) must be written as a
**pure-Python module with no I/O or FastAPI imports**, so it can be unit
tested without a server (§9).

### 3.2 Frontend — vanilla HTML/CSS/JS

- Plain **HTML + CSS + JavaScript (ES modules)**. No framework, no build
  step, no bundler. Two entry pages:
  - `/` — landing page → "Open a Board" / "Join a game".
  - `/board/{code}` — the Board app.
  - `/play` and `/play/{code}` — the player app (code pre-filled if present).
- Native `WebSocket` API for realtime. One small shared JS module implements
  the message envelope, heartbeats, and auto-reconnect (§7.1).
- Rationale: the UI is ~6 screens with modest interactivity. A framework adds
  a toolchain for the builder and nothing for the players. If the builder
  strongly prefers a framework, **Svelte or Vue via CDN** are acceptable
  substitutions; the protocol in §7 is the contract that must not change.

### 3.3 Deployment reality check

Players' phones must reach the server, so `localhost` is not enough.
Acceptable options (builder should document at least one in the README):

1. Host on a cheap VPS / free-tier PaaS with HTTPS (simplest for players).
2. Run locally + a tunnel (cloudflared / tailscale funnel / ngrok) — fine for
   game night, zero hosting cost.

HTTPS matters: phone browsers throttle/kill background tabs aggressively, and
some WebSocket + wake-lock behaviors are HTTPS-only. Assume **wss://** in
production.

---

## 4. Game rules

### 4.1 Parameters (settable on the Board, lobby or between rounds)

| Setting | Default | Range | Notes |
|---|---|---|---|
| Hand size | 7 | 5–10 | White cards per player, refilled after each round |
| Score target | 7 | 3–20 or **Endless** | First to target wins; Endless never ends the game |
| Czar order | Join order | any permutation | Drag-to-reorder list on the Board (§5.2) |
| Czar pick timer | Off | Off / 60s / 90s / 120s | Optional pressure timer; expiry does **not** auto-pick (§8.4) |
| Submission timer | Off | Off / 60s / 90s / 120s | Expiry moves round on without stragglers (§8.4) |
| Base deck | On | on/off per pack | Toggle which card packs are in play |

### 4.2 Round flow (happy path)

1. **Draw**: the round's Czar is the next player in the configured rotation.
   A black card is drawn and shown on the Board and on all phones.
2. **Submit**: every connected non-Czar player picks `pick` white cards from
   their hand (`pick` is a property of the black card, §6.2). Multi-pick
   submissions are ordered — the phone UI must let players arrange the order
   before confirming. Submissions are final once confirmed.
   The Board shows one face-down card back per received submission (no names).
3. **Reveal**: when all eligible players have submitted (or the timer fires),
   submissions are **shuffled server-side**, then the Czar taps through them
   on their phone, flipping each face-up on the Board one at a time. For
   multi-pick black cards, a submission's cards are revealed together, slotted
   into the blanks. The Czar's phone mirrors the reveal list.
4. **Judge**: after all are revealed, the Czar selects a winner on their
   phone. The Board highlights the winning submission and **only now** shows
   the winner's name. Scoreboard increments.
5. **Cleanup**: played white cards go to the white discard pile; the black
   card goes to the black discard pile; players draw back up to hand size;
   Czar advances to the next player in rotation. If the score target is
   reached → **Game over** screen (Board shows final standings; host can
   start a rematch with the same players, decks and settings, scores reset).
   Otherwise → next round.

### 4.3 Player counts

- **Minimum to start: 3** (1 Czar + 2 submitters). The classic game says 4+,
  but 3 must work.
- Maximum: 12 (soft cap; protects Board layout, not the server).
- Late joiners are dealt a full hand and appended to the *end* of the Czar
  rotation, entering play at the start of the next round (§8.2).

### 4.4 Anonymity rule

The mapping submission → player is never sent to the Board or to any player
client (including the Czar) until the winner is chosen. Only after the
winner is picked does the server broadcast the winner's identity. Losing
submissions stay anonymous forever (server knows; clients are never told).
This is a server-side guarantee, not a UI courtesy — the data must not be in
the payloads (see `reveal_ready` in §7.4).

---

## 5. Screen-by-screen requirements

### 5.1 Board — Lobby

- Big room code + the join URL (and a QR code encoding the join URL — a tiny
  self-hosted JS QR lib is worth the dependency; phones join in one scan).
- Player list as they join: name + connection indicator.
- Settings panel (§4.1), including the Czar order editor (§5.2).
- "Start game" button — enabled at ≥3 players. The Board is a mouse/touch
  surface for the *host*, so buttons on the Board are fine.

### 5.2 Board — Czar order editor

- A vertical list of joined players, drag-to-reorder (fallback: up/down
  arrows per row — required anyway for accessibility).
- Visible in the lobby and between rounds (not mid-round). Reordering
  mid-game takes effect from the next Czar assignment; it never changes the
  current round's Czar.
- The next three upcoming Czars are always visible on the Board during play
  ("Czar: Alice — next: Bob, Carol").

### 5.3 Board — In round

- The black card, large and legible from a screen-shared window (test at
  720p — Discord compresses; minimum ~28px effective font for card text).
- Submission area: face-down card backs appear as submissions land
  (order-shuffled), flipping face-up during reveal.
- Persistent sidebar: scoreboard (name, points, connected/disconnected dot,
  crown on current Czar) and round number.
- Status line: "Waiting for 2 players…" / "Czar is revealing…" /
  "Czar is choosing…" with the optional countdown timer.

### 5.4 Phone — Join

- Fields: room code (auto-uppercased, 4 letters) + name (1–20 chars,
  uniqueness enforced per room — server appends "(2)" on collision rather
  than rejecting).
- Rejoin shortcut: if the browser has a session token for a live room
  (§7.2), skip the form and reconnect straight into the hand.

### 5.5 Phone — Hand / round play

- The current black card pinned at the top (small), hand below as a
  scrollable/fannable list of white cards.
- Submission flow: tap to select (shows 1/2 progress for multi-pick),
  reorder if `pick > 1`, then an explicit **Confirm** — no accidental
  submissions. After confirming: "Submitted — waiting for others", with own
  submitted cards shown grayed.
- When this player is Czar: no hand interaction; a "You're the Czar" screen
  that becomes the reveal-and-judge controller (tap to flip next card; after
  all flipped, tap a submission → confirm → winner).
- Between rounds: transient result ("Bob won with …"), then auto-advance.

### 5.6 Phone — Custom card editor

Reachable any time from a persistent "＋ Cards" button in the player UI.

- **White card form**: single text field, 1–80 chars.
  Guidance text (enforced socially, not programmatically): *"Write a noun or
  gerund — a thing or a doing. 'A disappointing salad.' 'Crying at the
  gym.'"* The server performs no part-of-speech validation; the guidance
  line and a live preview are the enforcement mechanism.
- **Black card form**: single text field, 1–140 chars. Must be either a
  **question** or contain **one or more blanks** written as `_` (validated:
  server rejects a black card with no `_` and no `?`). `pick` is derived:
  number of `_` occurrences, or 1 for a question card (§6.2). Live preview
  renders blanks as the styled underline players will see.
- On submit: card is added to the room's active deck. New white cards go
  into the draw pile (shuffled in); new black cards likewise. The Board
  briefly toasts "Dana added 2 custom cards" — count only, never the text,
  so custom cards stay surprising.
- Cards added mid-round join the piles immediately but naturally can't
  appear until drawn.
- **Pack saving**: the room's custom cards are exportable from the Board
  ("Save custom pack" → server writes a JSON pack file, §6.4) so a group's
  house deck accumulates across game nights and appears as a toggleable pack
  in the next lobby.

---

## 6. Data model

All state lives server-side in plain Python objects (dataclasses). Clients
are dumb terminals rendering server snapshots.

### 6.1 Room

```
Room
  code: str            # 4 uppercase letters, unambiguous alphabet (no O/I)
  phase: Phase         # LOBBY | SUBMITTING | REVEALING | JUDGING |
                       # ROUND_END | GAME_OVER
  settings: Settings   # §4.1 values
  players: list[Player]        # insertion order = join order
  czar_order: list[player_id]  # the settable rotation (§5.2)
  czar_index: int              # position in czar_order of current Czar
  round_no: int
  black_card: BlackCard | None         # current round's card
  submissions: list[Submission]        # this round, server-shuffled
  decks: Decks                         # draw + discard piles, both colors
  board_connected: bool
  created_at / last_activity: datetime # for idle room GC (§8.7)
```

### 6.2 Cards

```
WhiteCard:  id, text, pack_id
BlackCard:  id, text, pick, pack_id
```

- Black card `text` stores blanks as a literal underscore `_` token
  (word-boundary-delimited). `pick = max(1, count of blank tokens)`.
  A question card ("Why am I sticky?") has zero blanks → `pick = 1`, and the
  submission is displayed *below* the question rather than inline.
- Rendering rule for reveals: replace the Nth blank with the Nth card of the
  submission, styled distinctly (e.g. underlined/bold) on Board and phones.

### 6.3 Player and Submission

```
Player
  id: str              # server-generated, stable for the room's lifetime
  token: str           # secret; proves identity on reconnect (§7.2)
  name: str
  hand: list[WhiteCard]
  score: int
  connected: bool
  is_playing: bool     # false while sitting out (late join / left)

Submission
  player_id: str       # NEVER serialized to clients before winner reveal
  cards: list[WhiteCard]   # ordered
  revealed: bool
```

### 6.4 Card packs (on disk)

```json
{
  "name": "Base deck",
  "id": "base",
  "white": ["Bees.", "Slapping a biscuit out of a toddler's hand."],
  "black": ["_ is the leading cause of divorce.", "What's my secret power?"]
}
```

- `packs/` directory, one JSON file per pack, loaded at startup; the lobby
  lists all packs with toggles. "Save custom pack" (§5.6) writes
  `packs/custom-<date>.json`.
- Ship a small original starter pack (~150 white / ~40 black). **Do not copy
  official CAH card text** — CAH is CC BY-NC-SA, which is incompatible with
  redistribution here without matching license care; original cards written
  for this project avoid the question entirely.

### 6.5 Deck mechanics

- Draw piles are shuffled queues. Drawing from an empty white pile reshuffles
  the white discard (minus cards currently in hands); an empty black pile
  reshuffles the black discard. If the white pile *and* discard can't refill
  hands (extreme custom-only setup), the game continues with short hands and
  a Board warning rather than crashing.

---

## 7. Client–server protocol

### 7.1 Transport

- WebSocket per client: `wss://…/ws/board/{code}` and `wss://…/ws/play`.
- JSON message envelope both directions:
  `{"type": "<message_type>", "data": {…}}`.
- Heartbeat: client sends `ping` every 20s; server closes sockets silent
  for 60s and marks that player disconnected (§8.1).
- Reconnect policy (client): exponential backoff 1s → 2s → 4s → … capped at
  10s, forever. Phones *will* drop (screen lock, app switch); reconnection
  is the normal case, not the exception (§8.1).

### 7.2 Identity & reconnection

- On first join the server responds with `{player_id, token}`; the phone
  stores both (plus room code) in `localStorage`.
- Reconnecting clients open the socket and send `rejoin` with the token; the
  server re-binds the socket to the existing `Player`, marks them connected,
  and sends a full state snapshot. Tokens are room-scoped and die with the
  room.
- The Board needs no token (it holds no secrets); opening `/board/{code}`
  claims the Board slot (§2).

### 7.3 State synchronization model

**Server-authoritative, full-snapshot broadcasts.** Every state change makes
the server push each client a fresh, **role-filtered** `state` message.
No diffing, no client-side game logic. At this scale (≤13 clients, state
< 10 KB) snapshots are simpler and eliminate a whole class of desync bugs.

Filtering rules (the security model of the game — enforce in one serializer
function, unit-tested, §9):

- Board snapshot: no hands, no submission→player mapping, no tokens.
- Player snapshot: own hand only; submission texts only during/after reveal
  (shuffled order, no player ids); everyone's scores/names/connected flags.
- Czar's snapshot additionally: reveal cursor + judging affordance flags.

### 7.4 Message catalog

Client → server (player phone):

| type | data | valid in phase |
|---|---|---|
| `join` | `{code, name}` | any (LOBBY for new players; else joins as late-joiner §8.2) |
| `rejoin` | `{code, player_id, token}` | any |
| `submit` | `{card_ids: […ordered]}` | SUBMITTING |
| `reveal_next` | `{}` (Czar only) | REVEALING |
| `pick_winner` | `{submission_index}` (Czar only) | JUDGING |
| `add_card` | `{kind: "white"\|"black", text}` | any |
| `ping` | `{}` | any |

Client → server (Board):

| type | data | valid in phase |
|---|---|---|
| `claim_board` | `{code}` (creates room if absent → new code) | any |
| `update_settings` | partial Settings (incl. `czar_order`) | LOBBY, ROUND_END |
| `start_game` | `{}` | LOBBY |
| `next_round` | `{}` | ROUND_END (also auto-fires after 8s) |
| `rematch` | `{}` | GAME_OVER |
| `kick_player` | `{player_id}` | LOBBY, ROUND_END |

Server → client:

| type | data |
|---|---|
| `joined` | `{player_id, token, code}` (join/rejoin ack) |
| `state` | full role-filtered snapshot: `{phase, round_no, black_card, players: [{name, score, connected, is_czar}], czar_order, submission_count, revealed: […], hand: […](players only), you: {…}, settings, winner: {name, cards}?}` |
| `toast` | `{text}` transient notices ("Dana added 2 custom cards") |
| `error` | `{code, message}` e.g. `ROOM_NOT_FOUND`, `NAME_TAKEN` → resolved server-side, `BAD_PHASE`, `INVALID_CARD` |

Every client-originated action is validated against the current phase and
the sender's role; invalid actions get an `error` and change nothing. The
server is the only referee.

---

## 8. Edge cases & failure handling

These are the cases that make or break a phone-based party game. Each is a
requirement, not a suggestion.

### 8.1 Player disconnects (the common case: phone locks)

- Mark disconnected (grey dot on Board), keep all state (hand, score,
  pending submission). Nothing is forfeited by a dropped socket.
- SUBMITTING: round proceeds when all *connected* eligible players have
  submitted; a player who reconnects before that closes is still allowed to
  submit. If every non-Czar player disconnects, the round pauses
  ("Waiting for players…").
- A disconnected player's already-made submission stays in play — they can
  win a round while their phone is locked.

### 8.2 Czar disconnects

- REVEALING/JUDGING: Board shows "Czar's phone lost — waiting…" and pauses.
  If not reconnected after 60s, the Board gets a host-facing **"Skip Czar"**
  button: the round is abandoned — submitted cards are *returned to their
  players' hands* (not discarded — losing cards to a dead phone feels
  terrible), the black card is discarded, no score, Czar advances, next
  round starts.
- SUBMITTING with Czar gone: submissions continue; pause only if the Czar is
  still gone when reveal should start (then as above).
- The same "Skip Czar" mechanism covers a Czar who wandered off (host
  discretion) — it's a host tool, not only a timeout.

### 8.3 Late join / leave / kick

- Late join (mid-round): player gets a hand immediately, `is_playing=false`
  for the current round, appended to end of Czar rotation, auto-enters next
  round. Board toasts the arrival.
- There is no player-initiated "leave"; abandoning is just disconnecting
  (state kept until room GC). The host can **kick** (lobby/between rounds):
  hand goes to white discard, removed from rotation, score history stays on
  the board (greyed) so the scoreboard still tells the night's story.
- If a kick/leave drops eligible submitters below 2 mid-round, the round is
  abandoned as in §8.2 (cards returned).

### 8.4 Timers

- Timers are OFF by default (friends heckle stragglers over Discord — that's
  the fun). When on: submission timer expiry closes submissions with
  whoever's in (minimum 1 submission, else round abandons); Czar timer
  expiry just flashes the Board and keeps waiting — auto-picking a "winner"
  randomly is worse than social pressure. Czar inactivity is ultimately
  resolved by "Skip Czar" (§8.2).

### 8.5 Board disconnects

- The game **pauses at phase boundaries** but sockets/phones stay live;
  phones show "Board disconnected". Reopening `/board/{code}` restores
  everything from server state (the Board is stateless).

### 8.6 Server crash (cheap insurance)

- Optional but recommended: after each phase transition, serialize each room
  to `snapshots/{code}.json`. On startup, reload snapshots newer than
  30 minutes. Players' stored tokens then survive a server restart
  mid-game. ~40 lines of code for "the night isn't ruined".

### 8.7 Room lifecycle

- Codes: 4 letters from a 24-letter alphabet (no O/I) → ~330k combinations;
  collision-checked at creation. Rooms are garbage-collected after 60
  minutes with no connected clients. GC writes nothing; saved packs (§6.4)
  are the only persistence that outlives a room.

---

## 9. Testing requirements

The game logic module (no I/O, §3.1) must have unit tests covering at least:

- Round state machine: every legal phase transition; every illegal
  action/phase combination rejected.
- Czar rotation: respects configured order, reorder-mid-game semantics
  (§5.2), late-joiner appending, kicked-player removal.
- Deck: multi-pick draw/refill, discard reshuffle, empty-deck degradation
  (§6.5).
- Black card parsing: blank counting → `pick`, question detection,
  rejection of blank-less non-questions (§5.6).
- **Serializer filtering (§7.3): board/player/czar snapshots must never
  contain another player's hand, any token, or a submission→player mapping
  pre-winner.** Treat a leak here as a broken build.
- Disconnect flows of §8.1–8.3 at the logic level (connected flags in, phase
  transitions out).

A thin integration test driving two fake WebSocket clients + a board through
one full round is strongly recommended; Playwright is available if the
builder wants a browser-level smoke test, but it is not required for v1.

---

## 10. Suggested repository layout

```
cardbox/
  server/
    cardbox/
      app.py          # FastAPI app: routes, websockets, static files
      game.py         # pure game logic: Room, phases, decks, rules
      serialize.py    # role-filtered snapshot builders (§7.3)
      cards.py        # pack loading/saving, black-card parsing
    tests/
  web/
    index.html        # landing
    board.html + board.js
    play.html + play.js
    shared/ws.js      # envelope + heartbeat + reconnect
    style.css
  packs/
    base.json
  DESIGN_SPEC.md      # this file
```

## 11. Build order (suggested milestones)

1. **Logic core**: `game.py` + `cards.py` + tests. A full round playable
   from a Python REPL/pytest with fake players.
2. **Transport**: FastAPI app, sockets, join/rejoin, snapshots, serializer +
   its filtering tests.
3. **Playable vertical slice**: minimal Board + phone UI, happy-path round,
   hardcoded base pack. *(First real game night possible here.)*
4. **The full loop**: scores/game over/rematch, Czar order editor, settings,
   late join, disconnect handling (§8.1–8.5).
5. **Custom cards**: editor, validation, mid-game insertion, pack save/load.
6. **Polish**: QR join, reveal animations, timers, room GC, snapshots (§8.6),
   720p legibility pass on the Board.
