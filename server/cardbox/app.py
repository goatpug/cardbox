"""FastAPI app: routes, websockets, static files (§3.1, §7).

Single process, single asyncio event loop. Live room state lives in the
`Hub` below (in-memory); the card library is the persistent SQLite store
(library.py). Run with: `uvicorn cardbox.app:app` from the `server/` dir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .cards import InvalidBlackCard
from .game import (
    BlackCard,
    Decks,
    GameError,
    Phase,
    Player,
    Room,
    Submission,
    WhiteCard,
    random_room_code,
)
from .library import Library

from .serialize import serialize_board, serialize_player

BASE_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = BASE_DIR / "web"
PACKS_DIR = BASE_DIR / "packs"
# Overridable via env for tests, so they never touch the real card library (§9).
DB_PATH = Path(os.environ["CARDBOX_DB_PATH"]) if os.environ.get("CARDBOX_DB_PATH") else BASE_DIR / "cardbox.db"
SNAPSHOT_DIR = (
    Path(os.environ["CARDBOX_SNAPSHOT_DIR"]) if os.environ.get("CARDBOX_SNAPSHOT_DIR") else BASE_DIR / "snapshots"
)

ROOM_IDLE_TIMEOUT = timedelta(minutes=60)
SNAPSHOT_MAX_AGE = timedelta(minutes=30)
GC_INTERVAL_SECONDS = 300
TOAST_DEBOUNCE_SECONDS = 2.0
ROUND_END_AUTOADVANCE_SECONDS = 8

logger = logging.getLogger("cardbox")

CLIENT_ERRORS = (GameError, TypeError, ValueError, KeyError)


# ------------------------------------------------------------------ snapshots

def _card_to_dict(card) -> dict:
    d = {"id": card.id, "text": card.text, "pack_id": card.pack_id}
    if isinstance(card, BlackCard):
        d["kind"] = "black"
        d["pick"] = card.pick
    else:
        d["kind"] = "white"
    return d


def _card_from_dict(d: dict):
    if d["kind"] == "black":
        return BlackCard(id=d["id"], text=d["text"], pick=d["pick"], pack_id=d["pack_id"])
    return WhiteCard(id=d["id"], text=d["text"], pack_id=d["pack_id"])


def room_to_dict(room: Room) -> dict:
    return {
        "code": room.code,
        "phase": room.phase.value,
        "settings": {
            "hand_size": room.settings.hand_size,
            "score_target": room.settings.score_target,
            "czar_pick_timer": room.settings.czar_pick_timer,
            "submission_timer": room.settings.submission_timer,
            "enabled_packs": dict(room.settings.enabled_packs),
        },
        "players": [
            {
                "id": p.id,
                "token": p.token,
                "name": p.name,
                "hand": [_card_to_dict(c) for c in p.hand],
                "score": p.score,
                "is_playing": p.is_playing,
                "kicked": p.kicked,
            }
            for p in room.players
        ],
        "czar_order": list(room.czar_order),
        "czar_index": room.czar_index,
        "round_no": room.round_no,
        "black_card": _card_to_dict(room.black_card) if room.black_card else None,
        "submissions": [
            {
                "player_id": s.player_id,
                "cards": [_card_to_dict(c) for c in s.cards],
                "revealed": s.revealed,
            }
            for s in room.submissions
        ],
        "decks": {
            "white_draw": [_card_to_dict(c) for c in room.decks.white_draw],
            "white_discard": [_card_to_dict(c) for c in room.decks.white_discard],
            "black_draw": [_card_to_dict(c) for c in room.decks.black_draw],
            "black_discard": [_card_to_dict(c) for c in room.decks.black_discard],
        },
        "all_white": [_card_to_dict(c) for c in room._all_white],
        "all_black": [_card_to_dict(c) for c in room._all_black],
        "last_winner": (
            {
                "player_id": room.last_winner["player_id"],
                "name": room.last_winner["name"],
                "cards": [_card_to_dict(c) for c in room.last_winner["cards"]],
            }
            if room.last_winner
            else None
        ),
        "created_at": room.created_at.isoformat(),
        "last_activity": room.last_activity.isoformat(),
    }


def room_from_dict(data: dict) -> Room:
    room = Room(data["code"])
    room.phase = Phase(data["phase"])
    s = data["settings"]
    room.settings.hand_size = s["hand_size"]
    room.settings.score_target = s["score_target"]
    room.settings.czar_pick_timer = s["czar_pick_timer"]
    room.settings.submission_timer = s["submission_timer"]
    room.settings.enabled_packs = dict(s["enabled_packs"])
    room.players = [
        Player(
            id=p["id"],
            token=p["token"],
            name=p["name"],
            hand=[_card_from_dict(c) for c in p["hand"]],
            score=p["score"],
            connected=False,
            is_playing=p["is_playing"],
            kicked=p["kicked"],
        )
        for p in data["players"]
    ]
    room.czar_order = list(data["czar_order"])
    room.czar_index = data["czar_index"]
    room.round_no = data["round_no"]
    room.black_card = _card_from_dict(data["black_card"]) if data["black_card"] else None
    room.submissions = [
        Submission(
            player_id=sd["player_id"],
            cards=[_card_from_dict(c) for c in sd["cards"]],
            revealed=sd["revealed"],
        )
        for sd in data["submissions"]
    ]
    room.decks = Decks(
        white_draw=[_card_from_dict(c) for c in data["decks"]["white_draw"]],
        white_discard=[_card_from_dict(c) for c in data["decks"]["white_discard"]],
        black_draw=[_card_from_dict(c) for c in data["decks"]["black_draw"]],
        black_discard=[_card_from_dict(c) for c in data["decks"]["black_discard"]],
    )
    room._all_white = [_card_from_dict(c) for c in data["all_white"]]
    room._all_black = [_card_from_dict(c) for c in data["all_black"]]
    room.last_winner = (
        {
            "player_id": data["last_winner"]["player_id"],
            "name": data["last_winner"]["name"],
            "cards": [_card_from_dict(c) for c in data["last_winner"]["cards"]],
        }
        if data.get("last_winner")
        else None
    )
    room.created_at = datetime.fromisoformat(data["created_at"])
    room.last_activity = datetime.fromisoformat(data["last_activity"])
    return room


# ------------------------------------------------------------------------ hub

class Hub:
    def __init__(self) -> None:
        self.library = Library(DB_PATH)
        self.rooms: dict[str, Room] = {}
        self.board_sockets: dict[str, WebSocket] = {}
        self.player_sockets: dict[str, dict[str, WebSocket]] = {}
        self._toast_pending: dict[tuple[str, str], int] = {}
        self._toast_tasks: dict[tuple[str, str], asyncio.Task] = {}

    def seed_packs(self) -> None:
        for path in sorted(PACKS_DIR.glob("*.json")):
            try:
                self.library.seed_pack_json(path)
            except Exception:
                logger.exception("Failed to seed pack %s", path)

    def load_snapshots(self) -> None:
        if not SNAPSHOT_DIR.exists():
            return
        cutoff = datetime.now(timezone.utc) - SNAPSHOT_MAX_AGE
        for path in SNAPSHOT_DIR.glob("*.json"):
            try:
                room = room_from_dict(json.loads(path.read_text()))
                if room.last_activity < cutoff:
                    path.unlink(missing_ok=True)
                    continue
                self.rooms[room.code] = room
            except Exception:
                logger.exception("Failed to reload snapshot %s", path)

    def default_enabled_packs(self) -> dict[str, bool]:
        return {p.id: p.on_by_default for p in self.library.list_packs()}

    def _pack_pool(self, enabled_packs: dict[str, bool]) -> tuple[list[WhiteCard], list[BlackCard]]:
        enabled_ids = [pid for pid, on in enabled_packs.items() if on]
        rows = self.library.get_cards_for_packs(enabled_ids)
        white = [WhiteCard(id=r.id, text=r.text, pack_id=r.pack_id) for r in rows if r.kind == "white"]
        black = [BlackCard(id=r.id, text=r.text, pick=r.pick, pack_id=r.pack_id) for r in rows if r.kind == "black"]
        return white, black

    def create_room(self) -> Room:
        code = random_room_code()
        while code in self.rooms:
            code = random_room_code()
        room = Room(code)
        enabled = self.default_enabled_packs()
        white, black = self._pack_pool(enabled)
        room.load_pool(white, black, enabled)
        self.rooms[code] = room
        return room

    def get_room(self, code: str) -> Room | None:
        return self.rooms.get((code or "").upper())

    def refresh_pool(self, room: Room) -> None:
        """Re-derive the room's card pool after settings.enabled_packs changes."""
        white, black = self._pack_pool(room.settings.enabled_packs)
        room.load_pool(white, black, room.settings.enabled_packs)

    async def _safe_send(self, ws: WebSocket, type_: str, data: dict) -> None:
        try:
            await ws.send_json({"type": type_, "data": data})
        except Exception:
            pass

    async def send_error(self, ws: WebSocket, code: str, message: str) -> None:
        await self._safe_send(ws, "error", {"code": code, "message": message})

    async def toast_board(self, code: str, text: str) -> None:
        ws = self.board_sockets.get(code)
        if ws is not None:
            await self._safe_send(ws, "toast", {"text": text})

    async def broadcast(self, room: Room) -> None:
        board_ws = self.board_sockets.get(room.code)
        if board_ws is not None:
            await self._safe_send(board_ws, "state", serialize_board(room))
        for pid, ws in list(self.player_sockets.get(room.code, {}).items()):
            await self._safe_send(ws, "state", serialize_player(room, pid))

    def note_custom_card(self, code: str, author: str) -> None:
        key = (code, author)
        self._toast_pending[key] = self._toast_pending.get(key, 0) + 1
        existing = self._toast_tasks.get(key)
        if existing is None or existing.done():
            self._toast_tasks[key] = asyncio.create_task(self._flush_toast(key))

    async def _flush_toast(self, key: tuple[str, str]) -> None:
        await asyncio.sleep(TOAST_DEBOUNCE_SECONDS)
        count = self._toast_pending.pop(key, 0)
        code, author = key
        if count:
            noun = "card" if count == 1 else "cards"
            await self.toast_board(code, f"{author} added {count} custom {noun}")

    def _schedule_submission_timer(self, room: Room) -> None:
        if room.phase != Phase.SUBMITTING or not room.settings.submission_timer:
            return
        asyncio.create_task(self._submission_timer(room.code, room.round_no, room.settings.submission_timer))

    async def _submission_timer(self, code: str, round_no: int, delay: int) -> None:
        await asyncio.sleep(delay)
        room = self.rooms.get(code)
        if not room or room.phase != Phase.SUBMITTING or room.round_no != round_no:
            return
        try:
            if room.submissions:
                room.close_submissions()
            else:
                room.skip_czar()
        except GameError:
            return
        await self.after_round_change(room)

    def _schedule_round_end_autoadvance(self, room: Room) -> None:
        if room.phase != Phase.ROUND_END:
            return
        asyncio.create_task(
            self._round_end_autoadvance(room.code, room.round_no)
        )

    async def _round_end_autoadvance(self, code: str, round_no: int) -> None:
        await asyncio.sleep(ROUND_END_AUTOADVANCE_SECONDS)
        room = self.rooms.get(code)
        if not room or room.phase != Phase.ROUND_END or room.round_no != round_no:
            return
        try:
            room.next_round()
        except GameError:
            return
        await self.after_round_change(room)

    async def after_round_change(self, room: Room) -> None:
        """Call after every state-mutating action: broadcast + timers + crash-insurance snapshot."""
        await self.broadcast(room)
        self._schedule_submission_timer(room)
        self._schedule_round_end_autoadvance(room)
        self.save_snapshot(room)

    def save_snapshot(self, room: Room) -> None:
        try:
            SNAPSHOT_DIR.mkdir(exist_ok=True)
            (SNAPSHOT_DIR / f"{room.code}.json").write_text(json.dumps(room_to_dict(room)))
        except Exception:
            logger.exception("Failed to snapshot room %s", room.code)

    def delete_snapshot(self, code: str) -> None:
        (SNAPSHOT_DIR / f"{code}.json").unlink(missing_ok=True)

    def gc_rooms(self) -> list[str]:
        now = datetime.now(timezone.utc)
        dead = [
            code
            for code, room in self.rooms.items()
            if room.is_idle() and (now - room.last_activity) > ROOM_IDLE_TIMEOUT
        ]
        for code in dead:
            del self.rooms[code]
            self.board_sockets.pop(code, None)
            self.player_sockets.pop(code, None)
            self.delete_snapshot(code)
        return dead


hub = Hub()


async def _gc_loop() -> None:
    while True:
        await asyncio.sleep(GC_INTERVAL_SECONDS)
        try:
            hub.gc_rooms()
        except Exception:
            logger.exception("Room GC failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.seed_packs()
    hub.load_snapshots()
    task = asyncio.create_task(_gc_loop())
    yield
    task.cancel()


app = FastAPI(title="Cardbox", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# --------------------------------------------------------------------- pages

@app.get("/")
async def index_page():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/board/{code}")
async def board_page(code: str):
    return FileResponse(WEB_DIR / "board.html")


@app.get("/play")
async def play_page():
    return FileResponse(WEB_DIR / "play.html")


@app.get("/play/{code}")
async def play_page_with_code(code: str):
    return FileResponse(WEB_DIR / "play.html")


# ----------------------------------------------------------- library REST API
# (Board-only, lobby-only per §5.6; not part of the §7.4 realtime protocol.)

@app.get("/api/library/packs")
async def api_list_packs():
    out = []
    for p in hub.library.list_packs():
        cards = hub.library.list_pack_cards(p.id)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "on_by_default": p.on_by_default,
                "white_count": sum(1 for c in cards if c.kind == "white"),
                "black_count": sum(1 for c in cards if c.kind == "black"),
            }
        )
    return out


@app.get("/api/library/packs/{pack_id}/cards")
async def api_pack_cards(pack_id: str):
    return [
        {"id": c.id, "kind": c.kind, "text": c.text, "author": c.author}
        for c in hub.library.list_pack_cards(pack_id)
    ]


@app.delete("/api/library/cards/{card_id}")
async def api_delete_card(card_id: int):
    hub.library.soft_delete(card_id)
    return {"ok": True}


@app.get("/api/library/packs/{pack_id}/export")
async def api_export_pack(pack_id: str):
    try:
        pack = hub.library.export_pack(pack_id)
    except KeyError:
        return JSONResponse({"error": "not found"}, status_code=404)
    payload = {"id": pack.id, "name": pack.name, "white": pack.white, "black": pack.black}
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{pack.id}.json"'},
    )


# ------------------------------------------------------------------ websockets

@app.websocket("/ws/board/{code}")
async def ws_board(websocket: WebSocket, code: str):
    await websocket.accept()
    room: Room | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mtype = msg.get("type")
            data = msg.get("data") or {}

            if mtype == "claim_board":
                requested = (data.get("code") or "").upper()
                target = hub.get_room(requested) if requested else None
                room = target or hub.create_room()
                old_ws = hub.board_sockets.get(room.code)
                if old_ws is not None and old_ws is not websocket:
                    await hub.send_error(old_ws, "BOARD_TAKEN_OVER", "Board opened elsewhere")
                    try:
                        await old_ws.close()
                    except Exception:
                        pass
                hub.board_sockets[room.code] = websocket
                room.board_connected = True
                await hub._safe_send(websocket, "joined", {"code": room.code})
                await hub.after_round_change(room)
                continue

            if room is None:
                await hub.send_error(websocket, "NO_ROOM", "Claim a board first")
                continue

            try:
                if mtype == "update_settings":
                    changed_packs = "enabled_packs" in data
                    room.update_settings(data)
                    if changed_packs:
                        hub.refresh_pool(room)
                elif mtype == "start_game":
                    room.start_game()
                elif mtype == "next_round":
                    room.next_round()
                elif mtype == "rematch":
                    room.rematch()
                elif mtype == "kick_player":
                    pid = data.get("player_id")
                    room.kick_player(pid)
                    hub.player_sockets.get(room.code, {}).pop(pid, None)
                elif mtype == "skip_czar":
                    room.skip_czar()
                elif mtype == "ping":
                    room.last_activity = datetime.now(timezone.utc)
                    continue
                else:
                    await hub.send_error(websocket, "UNKNOWN_TYPE", f"Unknown message type {mtype}")
                    continue
            except CLIENT_ERRORS as e:
                await hub.send_error(websocket, getattr(e, "code", "BAD_REQUEST"), str(e))
                continue

            await hub.after_round_change(room)
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None and hub.board_sockets.get(room.code) is websocket:
            del hub.board_sockets[room.code]
            room.board_connected = False
            hub.save_snapshot(room)


@app.websocket("/ws/play")
async def ws_play(websocket: WebSocket):
    await websocket.accept()
    room: Room | None = None
    player_id: str | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mtype = msg.get("type")
            data = msg.get("data") or {}

            if mtype == "join":
                code = (data.get("code") or "").upper()
                target = hub.get_room(code)
                if target is None:
                    await hub.send_error(websocket, "ROOM_NOT_FOUND", "No game with that code")
                    continue
                try:
                    player = target.add_player(data.get("name") or "")
                except CLIENT_ERRORS as e:
                    await hub.send_error(websocket, getattr(e, "code", "BAD_REQUEST"), str(e))
                    continue
                room, player_id = target, player.id
                hub.player_sockets.setdefault(room.code, {})[player_id] = websocket
                await hub._safe_send(
                    websocket, "joined", {"player_id": player.id, "token": player.token, "code": room.code}
                )
                if room.phase != Phase.LOBBY:
                    await hub.toast_board(room.code, f"{player.name} joined")
                await hub.after_round_change(room)
                continue

            if mtype == "rejoin":
                code = (data.get("code") or "").upper()
                target = hub.get_room(code)
                if target is None:
                    await hub.send_error(websocket, "ROOM_NOT_FOUND", "No game with that code")
                    continue
                player = target.find_by_token(data.get("player_id"), data.get("token") or "")
                if player is None:
                    await hub.send_error(websocket, "REJOIN_FAILED", "That session is no longer valid")
                    continue
                room, player_id = target, player.id
                hub.player_sockets.setdefault(room.code, {})[player_id] = websocket
                room.set_connected(player_id, True)
                await hub._safe_send(
                    websocket, "joined", {"player_id": player.id, "token": player.token, "code": room.code}
                )
                await hub.after_round_change(room)
                continue

            if room is None or player_id is None:
                await hub.send_error(websocket, "NOT_JOINED", "Join a room first")
                continue

            try:
                if mtype == "submit":
                    room.submit(player_id, list(data.get("card_ids") or []))
                elif mtype == "reveal_next":
                    room.reveal_next(player_id)
                elif mtype == "pick_winner":
                    idx = data.get("submission_index")
                    if not isinstance(idx, int):
                        raise ValueError("submission_index must be an integer")
                    room.pick_winner(player_id, idx)
                elif mtype == "add_card":
                    kind = data.get("kind")
                    text = data.get("text") or ""
                    author = room.get_player(player_id).name
                    try:
                        row, _is_new = hub.library.add_card(kind, text, author=author, pack_id="house")
                    except (ValueError, InvalidBlackCard) as e:
                        await hub.send_error(websocket, "INVALID_CARD", str(e))
                        continue
                    card = (
                        BlackCard(id=row.id, text=row.text, pick=row.pick, pack_id=row.pack_id)
                        if kind == "black"
                        else WhiteCard(id=row.id, text=row.text, pack_id=row.pack_id)
                    )
                    room.add_custom_card(card)
                    hub.note_custom_card(room.code, author)
                elif mtype == "ping":
                    room.last_activity = datetime.now(timezone.utc)
                    continue
                else:
                    await hub.send_error(websocket, "UNKNOWN_TYPE", f"Unknown message type {mtype}")
                    continue
            except CLIENT_ERRORS as e:
                await hub.send_error(websocket, getattr(e, "code", "BAD_REQUEST"), str(e))
                continue

            await hub.after_round_change(room)
    except WebSocketDisconnect:
        pass
    finally:
        if room is not None and player_id is not None:
            sockets = hub.player_sockets.get(room.code, {})
            if sockets.get(player_id) is websocket:
                del sockets[player_id]
                try:
                    room.set_connected(player_id, False)
                except GameError:
                    pass
                asyncio.create_task(hub.after_round_change(room))
