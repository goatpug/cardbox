import json

from cardbox.game import Room
from cardbox.serialize import serialize_board, serialize_player
from tests.test_game import add_players, make_room, submit_all_non_czar


def _blob(snapshot: dict) -> str:
    return json.dumps(snapshot)


def test_board_snapshot_has_no_hands_or_tokens():
    room = make_room()
    players = add_players(room, ["Alice", "Bob", "Carol"])
    room.start_game()

    snap = serialize_board(room)
    assert "hand" not in snap
    assert "you" not in snap
    blob = _blob(snap)
    for p in players:
        assert p.token not in blob
        for c in p.hand:
            assert c.text not in blob  # hands are never on the board


def test_board_snapshot_never_reveals_submission_owner():
    room = make_room()
    players = add_players(room, ["Alice", "Bob", "Carol"])
    room.start_game()
    submit_all_non_czar(room, players)  # -> REVEALING

    snap = serialize_board(room)
    blob = _blob(snap)
    assert "player_id" not in blob  # the submission -> player mapping itself never appears
    assert len(snap["revealed"]) == len(room.submissions)
    assert all(entry["cards"] is None for entry in snap["revealed"])  # nothing flipped yet


def test_player_snapshot_only_shows_own_hand():
    room = make_room()
    players = add_players(room, ["Alice", "Bob", "Carol"])
    room.start_game()
    alice, bob, carol = players

    snap = serialize_player(room, alice.id)
    own_ids = {c.id for c in alice.hand}
    assert {c["id"] for c in snap["hand"]} == own_ids

    other_ids = {c.id for c in bob.hand} | {c.id for c in carol.hand}
    assert own_ids.isdisjoint(other_ids)  # sanity: hands don't share cards
    assert {c["id"] for c in snap["hand"]}.isdisjoint(other_ids)

    blob = _blob(snap)
    for p in players:
        assert p.token not in blob


def test_player_snapshot_hides_submission_owner_until_revealed():
    room = make_room()
    players = add_players(room, ["Alice", "Bob", "Carol"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)  # -> REVEALING, shuffled, unrevealed

    for p in players:
        snap = serialize_player(room, p.id)
        assert "player_id" not in _blob(snap["revealed"])
        assert all(entry["cards"] is None for entry in snap["revealed"])

    room.reveal_next(czar_id)
    czar_snap = serialize_player(room, czar_id)
    revealed_entries = [e for e in czar_snap["revealed"] if e["revealed"]]
    assert len(revealed_entries) == 1
    assert "player_id" not in _blob(czar_snap["revealed"])


def test_winner_identity_only_appears_after_pick_winner():
    room = make_room()
    players = add_players(room, ["Alice", "Bob", "Carol"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)

    board_before = serialize_board(room)
    assert board_before["winner"] is None

    room.pick_winner(czar_id, 0)
    board_after = serialize_board(room)
    assert board_after["winner"]["name"] == room.get_player(room.last_winner["player_id"]).name


def test_czar_gets_reveal_cursor_and_judge_flag():
    room = make_room()
    players = add_players(room, ["Alice", "Bob", "Carol"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)

    czar_snap = serialize_player(room, czar_id)
    assert czar_snap["you"]["is_czar"] is True
    assert czar_snap["you"]["reveal_cursor"] == 0

    non_czar = next(p for p in players if p.id != czar_id)
    non_czar_snap = serialize_player(room, non_czar.id)
    assert "reveal_cursor" not in non_czar_snap["you"]

    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    czar_snap = serialize_player(room, czar_id)
    assert czar_snap["you"]["can_judge"] is True
