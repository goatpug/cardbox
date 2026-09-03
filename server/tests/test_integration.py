"""Thin integration test: a board + three fake WebSocket clients through one
full round, over the real FastAPI/WebSocket transport (§9). Uses a temp
SQLite DB and snapshot dir so it never touches the real card library.
"""
import contextlib
import os
import signal
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.TemporaryDirectory()
os.environ["CARDBOX_DB_PATH"] = str(Path(_tmp.name) / "test-cardbox.db")
os.environ["CARDBOX_SNAPSHOT_DIR"] = str(Path(_tmp.name) / "snapshots")

from fastapi.testclient import TestClient  # noqa: E402

from cardbox.app import app  # noqa: E402


@contextlib.contextmanager
def guard(seconds=15):
    """Fail loudly instead of hanging forever if a message never arrives."""
    def _raise(signum, frame):
        raise TimeoutError(f"Integration test exceeded {seconds}s — a websocket message never arrived")

    old = signal.signal(signal.SIGALRM, _raise)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def expect(ws, type_):
    msg = ws.receive_json()
    assert msg["type"] == type_, msg
    return msg["data"]


def drain_state(sockets: dict):
    return {name: expect(ws, "state") for name, ws in sockets.items()}


def test_full_round_over_the_wire():
    with guard(15), TestClient(app) as client:
        with client.websocket_connect("/ws/board/NEW") as board:
            board.send_json({"type": "claim_board", "data": {"code": ""}})
            joined = expect(board, "joined")
            code = joined["code"]
            assert len(code) == 4
            lobby = expect(board, "state")
            assert lobby["phase"] == "LOBBY"

            with client.websocket_connect("/ws/play") as p1, client.websocket_connect(
                "/ws/play"
            ) as p2, client.websocket_connect("/ws/play") as p3:
                sockets = {"board": board}

                p1.send_json({"type": "join", "data": {"code": code, "name": "Alice"}})
                j1 = expect(p1, "joined")
                sockets["p1"] = p1
                drain_state(sockets)

                p2.send_json({"type": "join", "data": {"code": code, "name": "Bob"}})
                j2 = expect(p2, "joined")
                sockets["p2"] = p2
                drain_state(sockets)

                p3.send_json({"type": "join", "data": {"code": code, "name": "Carol"}})
                j3 = expect(p3, "joined")
                sockets["p3"] = p3
                states = drain_state(sockets)
                assert [p["name"] for p in states["board"]["players"]] == ["Alice", "Bob", "Carol"]

                board.send_json({"type": "start_game", "data": {}})
                states = drain_state(sockets)
                assert all(s["phase"] == "SUBMITTING" for s in states.values())
                assert "hand" not in states["board"]  # board never gets hands (§7.3)

                board_players = {p["id"]: p for p in states["board"]["players"]}
                czar_id = next(pid for pid, p in board_players.items() if p["is_czar"])
                by_id = {j1["player_id"]: p1, j2["player_id"]: p2, j3["player_id"]: p3}
                names_by_id = {j1["player_id"]: "p1", j2["player_id"]: "p2", j3["player_id"]: "p3"}
                non_czar_ids = [pid for pid in by_id if pid != czar_id]
                assert len(non_czar_ids) == 2

                for pid in non_czar_ids:
                    ws = by_id[pid]
                    # each non-czar player only ever sees their own hand
                    my_state = states[names_by_id[pid]]
                    hand_ids = [c["id"] for c in my_state["hand"]]
                    ws.send_json({"type": "submit", "data": {"card_ids": [hand_ids[0]]}})
                    states = drain_state(sockets)

                assert all(s["phase"] == "REVEALING" for s in states.values())
                # anonymity: the submission list itself must never carry a player_id (§4.4, §7.3)
                # ("you.player_id" is a client's own self-identification and is expected)
                import json as _json

                for s in states.values():
                    assert "player_id" not in _json.dumps(s["revealed"])
                    assert "player_id" not in _json.dumps(s["players"])

                czar_ws = by_id[czar_id]
                czar_ws.send_json({"type": "reveal_next", "data": {}})
                states = drain_state(sockets)
                czar_ws.send_json({"type": "reveal_next", "data": {}})
                states = drain_state(sockets)
                assert all(s["phase"] == "JUDGING" for s in states.values())

                czar_ws.send_json({"type": "pick_winner", "data": {"submission_index": 0}})
                states = drain_state(sockets)
                assert all(s["phase"] == "ROUND_END" for s in states.values())
                winner_name = states["board"]["winner"]["name"]
                assert winner_name in ("Alice", "Bob", "Carol")

                board.send_json({"type": "next_round", "data": {}})
                states = drain_state(sockets)
                assert all(s["phase"] == "SUBMITTING" for s in states.values())
                assert states["board"]["round_no"] == 2

                # custom card: written to the library immediately (§5.6)
                p1.send_json({"type": "add_card", "data": {"kind": "white", "text": "A haunted Roomba."}})
                drain_state(sockets)

        resp = client.get("/api/library/packs/house/cards")
        assert resp.status_code == 200
        texts = [c["text"] for c in resp.json()]
        assert "A haunted Roomba." in texts


def test_room_not_found_error():
    with guard(10), TestClient(app) as client:
        with client.websocket_connect("/ws/play") as p1:
            p1.send_json({"type": "join", "data": {"code": "ZZZZ", "name": "Nobody"}})
            err = expect(p1, "error")
            assert err["code"] == "ROOM_NOT_FOUND"


def test_board_takeover_closes_old_socket():
    with guard(10), TestClient(app) as client:
        with client.websocket_connect("/ws/board/NEW") as board1:
            board1.send_json({"type": "claim_board", "data": {"code": ""}})
            joined = expect(board1, "joined")
            code = joined["code"]
            expect(board1, "state")

            with client.websocket_connect("/ws/board/NEW") as board2:
                board2.send_json({"type": "claim_board", "data": {"code": code}})
                err = expect(board1, "error")
                assert err["code"] == "BOARD_TAKEN_OVER"
                expect(board2, "joined")
                expect(board2, "state")
