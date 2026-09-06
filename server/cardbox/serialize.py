"""Role-filtered snapshot builders (§7.3).

This is the game's security boundary: it must never leak another player's
hand, any token, or a submission→player mapping before the winner is
revealed. Every rule here is covered by tests/test_serialize.py — treat a
leak here as a broken build (§9).
"""
from __future__ import annotations

from .game import AnyCard, BlackCard, Phase, Room, Settings


def _card_dict(card: AnyCard | None) -> dict | None:
    if card is None:
        return None
    d = {"id": card.id, "text": card.text}
    if isinstance(card, BlackCard):
        d["pick"] = card.pick
    return d


def _settings_dict(settings: Settings) -> dict:
    return {
        "hand_size": settings.hand_size,
        "score_target": settings.score_target,
        "czar_pick_timer": settings.czar_pick_timer,
        "submission_timer": settings.submission_timer,
        "enabled_packs": dict(settings.enabled_packs),
    }


def _players_public(room: Room) -> list[dict]:
    czar_id = room.current_czar_id
    return [
        {
            "id": p.id,
            "name": p.name,
            "score": p.score,
            "connected": p.connected,
            "is_czar": p.id == czar_id,
            "is_playing": p.is_playing,
            "kicked": p.kicked,
        }
        for p in room.players
    ]


def _revealed_list(room: Room) -> list[dict]:
    # Shuffled submission order; never a player id (§4.4, §6.3).
    return [
        {
            "revealed": s.revealed,
            "cards": [_card_dict(c) for c in s.cards] if s.revealed else None,
        }
        for s in room.submissions
    ]


def _base_snapshot(room: Room) -> dict:
    winner = None
    if room.last_winner and room.phase in (Phase.ROUND_END, Phase.GAME_OVER):
        winner = {
            "name": room.last_winner["name"],
            "cards": [_card_dict(c) for c in room.last_winner["cards"]],
            "black_card_text": room.last_winner["black_card_text"],
        }
    return {
        "code": room.code,
        "phase": room.phase.value,
        "round_no": room.round_no,
        "black_card": _card_dict(room.black_card),
        "players": _players_public(room),
        "czar_order": list(room.czar_order),
        "submission_count": len(room.submissions),
        "revealed": _revealed_list(room),
        "focused_index": room.focused_index,
        "settings": _settings_dict(room.settings),
        "deck_warning": room.deck_warning,
        "winner": winner,
        "board_connected": room.board_connected,
    }


def serialize_board(room: Room) -> dict:
    """Board snapshot: no hands, no submission→player mapping, no tokens (§7.3)."""
    return _base_snapshot(room)


def serialize_player(room: Room, player_id: str) -> dict:
    """Player snapshot: own hand only, plus Czar reveal/judge affordances (§7.3)."""
    snap = _base_snapshot(room)
    player = room.get_player(player_id)
    is_czar = player.id == room.current_czar_id
    has_submitted = any(s.player_id == player_id for s in room.submissions)

    snap["hand"] = [_card_dict(c) for c in player.hand]
    you = {
        "player_id": player.id,
        "name": player.name,
        "is_czar": is_czar,
        "has_submitted": has_submitted,
    }
    if is_czar and room.phase == Phase.REVEALING:
        you["reveal_cursor"] = next(
            (i for i, s in enumerate(room.submissions) if not s.revealed), None
        )
    if is_czar and room.phase == Phase.JUDGING:
        you["can_judge"] = True
    snap["you"] = you
    return snap
