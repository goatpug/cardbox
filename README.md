# Cardbox

A browser-based, Jackbox-style Cards Against Humanity party game. One shared
**Board** (laptop, screen-shared over Discord) plus each player's **phone**
as a private hand controller, joined with a short room code.

See [`DESIGN_SPEC.md`](./DESIGN_SPEC.md) for the full product/architecture
spec this implementation follows.

## Quickstart (local game night)

Requires Python 3.11+.

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn cardbox.app:app --host 0.0.0.0 --port 8420
```

Then:

1. On the host's laptop, open `http://localhost:8420/`, click **Open a
   Board**, and screen-share that browser window/tab over Discord.
2. Each player opens `http://<host-ip>:8420/play` on their phone (or scans
   the QR code shown on the Board), enters the room code + their name.
3. Arrange the Card Czar order and hit **Start game** from the Board.

`cardbox.db` (the persistent card library — starter packs + everyone's
custom cards) and `snapshots/` (crash-recovery snapshots, §8.6) are created
automatically on first run in the repo root, and are gitignored.

### Getting phones onto the server

Phones need to reach the server, so `localhost` alone isn't enough once you
leave the host's own machine. Two options:

1. **Same Wi-Fi**: run with `--host 0.0.0.0` as above, then have players
   browse to `http://<your-laptop-LAN-IP>:8420/play`. Good enough for one
   room, but phone browsers can be picky about `ws://` (non-TLS) sockets in
   the background — keep the play tab in the foreground if reconnects seem
   flaky.
2. **A tunnel** (recommended — gives you real `https://`/`wss://`, works
   across networks, zero hosting cost): e.g.
   `cloudflared tunnel --url http://localhost:8420` or `ngrok http 8420`,
   then share the printed `https://` URL instead of your LAN IP.

For a standing/dedicated deployment, run this the same way on a cheap VPS or
PaaS with HTTPS in front of it (reverse proxy or platform-provided TLS).

**Persistence caveat**: `cardbox.db` holds your group's accumulated card
library across game nights — it must live on a disk that survives restarts
and redeploys. A free-tier platform with an ephemeral filesystem will
silently wipe it. The Board's lobby has an **Export pack → JSON** button
under "Card library" for the House pack (and the `/api/library/packs/{id}/export`
endpoint for any pack) — use it as a backup before redeploying somewhere
without persistent storage.

## Running with Docker

A `Dockerfile` is included; it needs no code changes and works the same
locally or on a host. The card library and crash snapshots are read from
`/data` inside the container (via `CARDBOX_DB_PATH`/`CARDBOX_SNAPSHOT_DIR`),
so persistence is just "mount a volume at `/data`":

```bash
docker build -t cardbox .
docker volume create cardbox_data
docker run -d --name cardbox -p 8420:8420 -v cardbox_data:/data cardbox
```

Then open `http://localhost:8420/` same as the Quickstart above. The named
volume (`cardbox_data`) is what makes `cardbox.db` survive
`docker rm`/rebuild/redeploy — without `-v ...:/data` the library resets
every time the container restarts.

This works fine on a Chromebook's Linux (Crostini) container — if Docker
isn't installed yet: `sudo apt install docker.io`, then
`sudo usermod -aG docker $USER` and restart the Linux VM (or just prefix
commands with `sudo`, as above) so you don't need `sudo` for every command.

## Deploying with a fixed URL (Northflank)

A tunnel (`cloudflared`/`ngrok`) is fine for one-off game nights, but the
URL is different every time you start it — annoying to re-share with the
same group repeatedly. For a stable link (closer to how `jackbox.tv`
behaves), deploy the container to a host that keeps it running continuously
with a fixed address. [Northflank](https://northflank.com) works well for
this and its free tier supports both persistent volumes and long-lived
WebSocket connections (many serverless/functions-style free tiers support
neither, which is why they don't work for Cardbox):

1. Push this repo to GitHub (if it isn't already) and connect it as a
   Northflank service — it will build straight from the root `Dockerfile`.
2. Set the service's port to `8420`.
3. Add a **persistent volume** mounted at `/data` (matches the Dockerfile's
   `CARDBOX_DB_PATH`/`CARDBOX_SNAPSHOT_DIR`) — without this the card library
   resets on every redeploy.
4. Northflank gives the service a stable `https://...northflank.app` URL
   (or attach your own domain) — that's what you share with your group once,
   and it stays the same for every future game night.

## Running the tests

```bash
cd server
source .venv/bin/activate
python -m pytest -q
```

Covers the pure game-logic state machine, Czar rotation, deck mechanics,
black-card parsing, the SQLite card library, the role-filtered snapshot
serializer (the anonymity/security boundary — see §7.3/§9 of the spec), and
a full round driven over the real WebSocket transport.

## Repository layout

```
Dockerfile
.dockerignore
server/
  cardbox/
    app.py          # FastAPI app: routes, websockets, static files
    game.py          # pure game logic: Room, phases, decks, rules — no I/O
    serialize.py      # role-filtered snapshot builders (board/player/czar)
    cards.py          # black-card parsing, JSON pack import/export
    library.py        # SQLite card library: schema, inserts, soft delete
  tests/
web/
  index.html, board.html/.js, play.html/.js, shared/, style.css
packs/
  base.json           # original starter pack, seeded into the DB at startup
cardbox.db            # created at first run — the persistent card library
snapshots/             # created at first run — crash-recovery snapshots
```

## Notes

- The starter pack (`packs/base.json`) is original, adults-only material
  written for this project — no official Cards Against Humanity text is
  reproduced (CAH's CC BY-NC-SA license is incompatible with redistribution
  here).
- There's no content moderation — this is meant for a private game among
  friends.
