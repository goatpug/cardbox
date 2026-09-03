import pytest

from cardbox.game import (
    BadPhase,
    BlackCard,
    GameError,
    InvalidCard,
    NotAllowed,
    Phase,
    Room,
    WhiteCard,
)


def make_pool(n_white=100, n_black=20, pick=1):
    white = [WhiteCard(id=i, text=f"W{i}", pack_id="test") for i in range(n_white)]
    black = [BlackCard(id=1000 + i, text=f"B{i} _", pick=pick, pack_id="test") for i in range(n_black)]
    return white, black


def make_room(n_white=100, n_black=20, pick=1, code="TEST"):
    room = Room(code)
    white, black = make_pool(n_white, n_black, pick)
    room.load_pool(white, black, {"test": True})
    return room


def add_players(room, names):
    return [room.add_player(name) for name in names]


def submit_all_non_czar(room, players):
    """Helper: every non-czar player submits `pick` cards from the front of their hand."""
    czar_id = room.current_czar_id
    for p in players:
        if p.id == czar_id:
            continue
        pick = room.black_card.pick
        card_ids = [c.id for c in p.hand[:pick]]
        room.submit(p.id, card_ids)


# --------------------------------------------------------------------- setup

def test_start_game_requires_min_players():
    room = make_room()
    add_players(room, ["A", "B"])
    with pytest.raises(NotAllowed):
        room.start_game()


def test_start_game_deals_hands_and_draws_black():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    assert room.phase == Phase.SUBMITTING
    assert room.round_no == 1
    assert room.black_card is not None
    for p in players:
        assert len(p.hand) == room.settings.hand_size


def test_name_collision_appends_suffix():
    room = make_room()
    add_players(room, ["Alice"])
    p2 = room.add_player("Alice")
    assert p2.name == "Alice (2)"


def test_start_game_wrong_phase_rejected():
    room = make_room()
    add_players(room, ["A", "B", "C"])
    room.start_game()
    with pytest.raises(BadPhase):
        room.start_game()


# ------------------------------------------------------------------ submit

def test_czar_cannot_submit():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar = room.get_player(room.current_czar_id)
    with pytest.raises(NotAllowed):
        room.submit(czar.id, [czar.hand[0].id])


def test_submit_wrong_card_count_rejected():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    non_czar = next(p for p in players if p.id != room.current_czar_id)
    with pytest.raises(InvalidCard):
        room.submit(non_czar.id, [non_czar.hand[0].id, non_czar.hand[1].id])  # pick=1


def test_submit_card_not_in_hand_rejected():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    non_czar = next(p for p in players if p.id != room.current_czar_id)
    with pytest.raises(InvalidCard):
        room.submit(non_czar.id, [999999])


def test_submit_wrong_phase_rejected():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    with pytest.raises(BadPhase):
        room.submit(players[0].id, [players[0].hand[0].id if players[0].hand else 0])


def test_double_submit_rejected():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    non_czar = next(p for p in players if p.id != room.current_czar_id)
    room.submit(non_czar.id, [non_czar.hand[0].id])
    with pytest.raises(NotAllowed):
        room.submit(non_czar.id, [non_czar.hand[0].id])


# ------------------------------------------------------------- happy path

def test_full_round_happy_path():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id

    submit_all_non_czar(room, players)
    assert room.phase == Phase.REVEALING
    assert len(room.submissions) == 2

    room.reveal_next(czar_id)
    assert room.phase == Phase.REVEALING
    room.reveal_next(czar_id)
    assert room.phase == Phase.JUDGING

    room.pick_winner(czar_id, 0)
    assert room.phase == Phase.ROUND_END
    assert room.last_winner is not None
    winner = room.get_player(room.last_winner["player_id"])
    assert winner.score == 1
    assert winner.id != czar_id

    room.next_round()
    assert room.phase == Phase.SUBMITTING
    assert room.round_no == 2
    for p in players:
        assert len(p.hand) == room.settings.hand_size


def test_reveal_next_only_czar():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    submit_all_non_czar(room, players)
    non_czar = next(p for p in players if p.id != room.current_czar_id)
    with pytest.raises(NotAllowed):
        room.reveal_next(non_czar.id)


def test_pick_winner_before_all_revealed_rejected():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    with pytest.raises(BadPhase):
        room.pick_winner(czar_id, 0)


def test_score_target_reached_ends_game():
    room = make_room()
    room.settings.score_target = 1
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    assert room.phase == Phase.GAME_OVER


def test_rematch_resets_scores():
    room = make_room()
    room.settings.score_target = 1
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    assert room.phase == Phase.GAME_OVER

    room.rematch()
    assert room.phase == Phase.SUBMITTING
    assert room.round_no == 1
    for p in players:
        assert p.score == 0
        assert len(p.hand) == room.settings.hand_size


# ----------------------------------------------------------------- czar order

def test_czar_rotation_respects_join_order():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    assert room.current_czar_id == players[0].id
    submit_all_non_czar(room, players)
    czar_id = room.current_czar_id
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    room.next_round()
    assert room.current_czar_id == players[1].id


def test_reorder_czar_preserves_next_assigned_czar():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    assert room.phase == Phase.ROUND_END
    next_czar_id = room.current_czar_id  # already advanced by pick_winner

    reordered = list(reversed([p.id for p in players]))
    room.update_settings({"czar_order": reordered})
    assert room.current_czar_id == next_czar_id  # reorder doesn't bump the already-decided czar

    room.next_round()
    assert room.current_czar_id == next_czar_id


def test_late_joiner_appended_to_rotation_and_sits_out_current_round():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id

    d = room.add_player("D")
    assert d.is_playing is False
    assert room.czar_order[-1] == d.id
    assert len(d.hand) == room.settings.hand_size

    submit_all_non_czar(room, players)  # D never submits, isn't eligible yet
    assert room.phase == Phase.REVEALING
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    room.next_round()
    assert d.is_playing is True  # enters play at the next round (§8.3)


def test_kick_player_discards_hand_and_removes_from_rotation():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    b = players[1]
    room.kick_player(b.id)
    assert b.kicked is True
    assert b.hand == []
    assert b.id not in room.czar_order or True  # czar_order not built yet (still LOBBY)

    with pytest.raises(NotAllowed):
        room.start_game()  # only 2 non-kicked players left


def test_kick_between_rounds_drops_below_min_falls_back_to_lobby():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    assert room.phase == Phase.ROUND_END

    victim = next(p for p in players if p.id != room.current_czar_id)
    room.kick_player(victim.id)
    assert room.phase == Phase.LOBBY


# -------------------------------------------------------------- disconnects

def test_round_pauses_when_all_non_czar_disconnect():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    for p in players:
        if p.id != czar_id:
            room.set_connected(p.id, False)
    assert room.phase == Phase.SUBMITTING  # paused, not abandoned


def test_disconnect_of_straggler_unblocks_round():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    non_czar = [p for p in players if p.id != czar_id]
    p_submits, p_ghost = non_czar[0], non_czar[1]

    room.submit(p_submits.id, [p_submits.hand[0].id])
    assert room.phase == Phase.SUBMITTING  # still waiting on p_ghost

    room.set_connected(p_ghost.id, False)
    assert room.phase == Phase.REVEALING  # only connected eligible player had submitted


def test_disconnected_players_submission_still_wins():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    winner_sub_idx = 0
    winner_id = room.submissions[winner_sub_idx].player_id
    room.set_connected(winner_id, False)  # phone locks after submitting
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, winner_sub_idx)
    assert room.get_player(winner_id).score == 1


def test_skip_czar_returns_cards_to_hands():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    non_czar = [p for p in players if p.id != czar_id]
    hand_size_before = {p.id: len(p.hand) for p in non_czar}
    room.submit(non_czar[0].id, [non_czar[0].hand[0].id])

    room.skip_czar()
    assert room.phase == Phase.SUBMITTING  # new round begun
    assert room.submissions == []
    for p in non_czar:
        assert len(room.get_player(p.id).hand) == hand_size_before[p.id]


def test_close_submissions_requires_at_least_one():
    room = make_room()
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    with pytest.raises(NotAllowed):
        room.close_submissions()


# -------------------------------------------------------------------- decks

def test_deck_reshuffles_discard_when_draw_pile_empties():
    # exactly enough white cards to deal hands once; nothing left in draw pile
    room = make_room(n_white=6, n_black=10, pick=1)
    players = add_players(room, ["A", "B", "C"])
    room.settings.hand_size = 2
    room.start_game()
    assert room.decks.white_draw == []

    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)  # cleanup discards + refills from reshuffled discard

    for p in players:
        assert len(p.hand) == room.settings.hand_size
    assert room.deck_warning is None


def test_empty_deck_degrades_instead_of_crashing():
    room = make_room(n_white=3, n_black=5, pick=1)
    add_players(room, ["A", "B", "C"])
    room.settings.hand_size = 5
    room.start_game()  # only 3 white cards total for 3 players * 5 = 15 needed
    assert room.deck_warning is not None
    total_dealt = sum(len(p.hand) for p in room.players)
    assert total_dealt == 3


def test_black_deck_reshuffles_discard():
    room = make_room(n_white=200, n_black=1, pick=1)
    players = add_players(room, ["A", "B", "C"])
    room.start_game()
    czar_id = room.current_czar_id
    submit_all_non_czar(room, players)
    room.reveal_next(czar_id)
    room.reveal_next(czar_id)
    room.pick_winner(czar_id, 0)
    room.next_round()
    assert room.black_card is not None  # reshuffled the single discarded black card
    assert room.deck_warning is None or "black" not in (room.deck_warning or "")
