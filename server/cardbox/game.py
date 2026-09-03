"""Pure game logic: Room, phases, decks, rules (§3.1, §4, §6, §8).

No I/O, no FastAPI imports. Persistence (SQLite) and transport (WebSocket)
live in library.py and app.py; this module is unit-testable from a plain
pytest process (§9).
"""
from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Union

MIN_PLAYERS = 3
MAX_PLAYERS = 12
NAME_MAX_LEN = 20
ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no O/I (§8.7)
ROOM_CODE_LEN = 4

TIMER_CHOICES = (None, 60, 90, 120)
HAND_SIZE_RANGE = range(5, 11)
SCORE_TARGET_RANGE = range(3, 21)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def random_room_code() -> str:
    return "".join(random.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LEN))


class GameError(Exception):
    """Base for all illegal-action errors; app.py maps `.code` to an `error` message (§7.4)."""

    code = "BAD_REQUEST"


class BadPhase(GameError):
    code = "BAD_PHASE"


class NotAllowed(GameError):
    code = "NOT_ALLOWED"


class InvalidCard(GameError):
    code = "INVALID_CARD"


class Phase(str, Enum):
    LOBBY = "LOBBY"
    SUBMITTING = "SUBMITTING"
    REVEALING = "REVEALING"
    JUDGING = "JUDGING"
    ROUND_END = "ROUND_END"
    GAME_OVER = "GAME_OVER"


@dataclass(frozen=True)
class WhiteCard:
    id: int
    text: str
    pack_id: str


@dataclass(frozen=True)
class BlackCard:
    id: int
    text: str
    pick: int
    pack_id: str


AnyCard = Union[WhiteCard, BlackCard]


@dataclass
class Player:
    id: str
    token: str
    name: str
    hand: list[WhiteCard] = field(default_factory=list)
    score: int = 0
    connected: bool = True
    is_playing: bool = True
    kicked: bool = False


@dataclass
class Submission:
    player_id: str
    cards: list[WhiteCard]
    revealed: bool = False


@dataclass
class Settings:
    hand_size: int = 7
    score_target: int | Literal["endless"] = 7
    czar_pick_timer: int | None = None
    submission_timer: int | None = None
    enabled_packs: dict[str, bool] = field(default_factory=dict)


@dataclass
class Decks:
    white_draw: list[WhiteCard] = field(default_factory=list)
    white_discard: list[WhiteCard] = field(default_factory=list)
    black_draw: list[BlackCard] = field(default_factory=list)
    black_discard: list[BlackCard] = field(default_factory=list)


def _validate_settings_patch(data: dict) -> None:
    if "hand_size" in data and data["hand_size"] not in HAND_SIZE_RANGE:
        raise NotAllowed("hand_size must be 5-10")
    if "score_target" in data:
        st = data["score_target"]
        if st != "endless" and st not in SCORE_TARGET_RANGE:
            raise NotAllowed("score_target must be 3-20 or 'endless'")
    for key in ("czar_pick_timer", "submission_timer"):
        if key in data and data[key] not in TIMER_CHOICES:
            raise NotAllowed(f"{key} must be one of {TIMER_CHOICES}")


class Room:
    def __init__(self, code: str):
        self.code = code
        self.phase = Phase.LOBBY
        self.settings = Settings()
        self.players: list[Player] = []
        self.czar_order: list[str] = []
        self.czar_index: int = 0
        self.round_no: int = 0
        self.black_card: BlackCard | None = None
        self.submissions: list[Submission] = []
        self.decks = Decks()
        self.board_connected: bool = False
        self.created_at = _now()
        self.last_activity = _now()
        self.deck_warning: str | None = None
        self.last_winner: dict | None = None
        self._all_white: list[WhiteCard] = []
        self._all_black: list[BlackCard] = []

    # ------------------------------------------------------------------ setup

    def load_pool(self, white: list[WhiteCard], black: list[BlackCard], enabled_packs: dict[str, bool]) -> None:
        """Populate this room's card pool and draw piles at creation time (§6.4)."""
        self._all_white = list(white)
        self._all_black = list(black)
        self.settings.enabled_packs = dict(enabled_packs)
        self._rebuild_draw_piles()

    def _rebuild_draw_piles(self) -> None:
        self.decks = Decks(
            white_draw=list(self._all_white),
            black_draw=list(self._all_black),
        )
        random.shuffle(self.decks.white_draw)
        random.shuffle(self.decks.black_draw)
        self.deck_warning = None

    def add_custom_card(self, card: AnyCard) -> None:
        """New custom card: shuffled into the room's current draw pile immediately (§5.6)."""
        if isinstance(card, WhiteCard):
            self._all_white.append(card)
            pos = random.randrange(len(self.decks.white_draw) + 1)
            self.decks.white_draw.insert(pos, card)
        else:
            self._all_black.append(card)
            pos = random.randrange(len(self.decks.black_draw) + 1)
            self.decks.black_draw.insert(pos, card)

    # ---------------------------------------------------------------- lookup

    def get_player(self, player_id: str) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise NotAllowed(f"Unknown player {player_id}")

    def find_by_token(self, player_id: str, token: str) -> Player | None:
        p = next((p for p in self.players if p.id == player_id), None)
        if p and secrets.compare_digest(p.token, token):
            return p
        return None

    @property
    def current_czar_id(self) -> str | None:
        if not self.czar_order:
            return None
        return self.czar_order[self.czar_index % len(self.czar_order)]

    def _require_phase(self, *phases: Phase) -> None:
        if self.phase not in phases:
            raise BadPhase(f"Not valid in phase {self.phase}")

    def _require_czar(self, player_id: str) -> None:
        if player_id != self.current_czar_id:
            raise NotAllowed("Only the Card Czar may do that")

    def _eligible_submitters(self) -> list[Player]:
        czar_id = self.current_czar_id
        return [p for p in self.players if p.is_playing and not p.kicked and p.id != czar_id]

    def _active_players(self) -> list[Player]:
        return [p for p in self.players if p.is_playing and not p.kicked]

    # ----------------------------------------------------------------- join

    def _dedupe_name(self, name: str) -> str:
        existing = {p.name for p in self.players}
        if name not in existing:
            return name
        n = 2
        while f"{name} ({n})" in existing:
            n += 1
        return f"{name} ({n})"

    def add_player(self, name: str) -> Player:
        if len([p for p in self.players if not p.kicked]) >= MAX_PLAYERS:
            raise NotAllowed("Room is full")
        clean = (name or "").strip()[:NAME_MAX_LEN] or "Player"
        clean = self._dedupe_name(clean)
        player = Player(id=secrets.token_hex(8), token=secrets.token_urlsafe(24), name=clean)
        mid_game = self.phase != Phase.LOBBY
        if mid_game:
            player.hand = self._draw_white(self.settings.hand_size)
            player.is_playing = False  # sits out the current round (§8.3)
            self.czar_order.append(player.id)
        self.players.append(player)
        self.last_activity = _now()
        return player

    def kick_player(self, player_id: str) -> None:
        self._require_phase(Phase.LOBBY, Phase.ROUND_END, Phase.GAME_OVER)
        player = self.get_player(player_id)
        player.kicked = True
        player.is_playing = False
        self.decks.white_discard.extend(player.hand)
        player.hand = []
        if player.id in self.czar_order:
            current_czar_id = self.current_czar_id
            self.czar_order.remove(player.id)
            if self.czar_order:
                if current_czar_id in self.czar_order:
                    self.czar_index = self.czar_order.index(current_czar_id)
                else:
                    self.czar_index = self.czar_index % len(self.czar_order)
            else:
                self.czar_index = 0
        if self.phase == Phase.ROUND_END and len(self._active_players()) < MIN_PLAYERS:
            self.phase = Phase.LOBBY

    def set_connected(self, player_id: str, connected: bool) -> None:
        player = self.get_player(player_id)
        player.connected = connected
        self.last_activity = _now()
        if not connected and self.phase == Phase.SUBMITTING and self._ready_to_reveal():
            self._start_reveal()

    # --------------------------------------------------------------- decks

    def _draw_white(self, n: int) -> list[WhiteCard]:
        drawn: list[WhiteCard] = []
        for _ in range(n):
            if not self.decks.white_draw:
                if self.decks.white_discard:
                    self.decks.white_draw = self.decks.white_discard
                    self.decks.white_discard = []
                    random.shuffle(self.decks.white_draw)
                else:
                    self.deck_warning = "Ran out of white cards — hands may be short."
                    break
            drawn.append(self.decks.white_draw.pop())
        return drawn

    def _draw_black(self) -> BlackCard | None:
        if not self.decks.black_draw:
            if self.decks.black_discard:
                self.decks.black_draw = self.decks.black_discard
                self.decks.black_discard = []
                random.shuffle(self.decks.black_draw)
            else:
                self.deck_warning = "Ran out of black cards."
                return None
        return self.decks.black_draw.pop()

    def _deal_full_hands(self) -> None:
        for p in self.players:
            if not p.kicked:
                p.hand = self._draw_white(self.settings.hand_size)

    def _refill_hands(self) -> None:
        for p in self._active_players():
            need = self.settings.hand_size - len(p.hand)
            if need > 0:
                p.hand.extend(self._draw_white(need))

    # --------------------------------------------------------------- settings

    def update_settings(self, data: dict) -> None:
        self._require_phase(Phase.LOBBY, Phase.ROUND_END)
        _validate_settings_patch(data)
        if "czar_order" in data:
            self._reorder_czar(data["czar_order"])
        for key in ("hand_size", "score_target", "czar_pick_timer", "submission_timer", "enabled_packs"):
            if key in data:
                setattr(self.settings, key, data[key])
        self.last_activity = _now()

    def _reorder_czar(self, new_order: list[str]) -> None:
        current = self.current_czar_id if self.round_no > 0 else None
        if self.czar_order and set(new_order) != set(self.czar_order):
            raise NotAllowed("czar_order must contain exactly the current rotation's players")
        self.czar_order = list(new_order)
        if current is not None and current in self.czar_order:
            self.czar_index = self.czar_order.index(current)
        else:
            self.czar_index = 0

    # ------------------------------------------------------------ round flow

    def start_game(self) -> None:
        self._require_phase(Phase.LOBBY)
        if len(self._active_players()) < MIN_PLAYERS:
            raise NotAllowed(f"Need at least {MIN_PLAYERS} players")
        if not self.czar_order:
            self.czar_order = [p.id for p in self.players if not p.kicked]
        self.czar_index = 0
        self.round_no = 0
        self._deal_full_hands()
        self._begin_round()

    def _begin_round(self) -> None:
        self.black_card = self._draw_black()
        self.submissions = []
        self.last_winner = None
        self.phase = Phase.SUBMITTING
        self.round_no += 1
        self.last_activity = _now()

    def submit(self, player_id: str, card_ids: list[int]) -> None:
        self._require_phase(Phase.SUBMITTING)
        player = self.get_player(player_id)
        if player.id == self.current_czar_id:
            raise NotAllowed("The Czar does not submit cards")
        if not player.is_playing or player.kicked:
            raise NotAllowed("Not currently playing")
        if any(s.player_id == player_id for s in self.submissions):
            raise NotAllowed("Already submitted this round")
        assert self.black_card is not None
        if len(card_ids) != self.black_card.pick:
            raise InvalidCard(f"Must submit exactly {self.black_card.pick} card(s)")
        if len(set(card_ids)) != len(card_ids):
            raise InvalidCard("Duplicate cards in submission")
        hand_by_id = {c.id: c for c in player.hand}
        if any(cid not in hand_by_id for cid in card_ids):
            raise InvalidCard("Card not in hand")
        cards = [hand_by_id[cid] for cid in card_ids]
        for c in cards:
            player.hand.remove(c)
        self.submissions.append(Submission(player_id=player_id, cards=cards))
        self.last_activity = _now()
        if self._ready_to_reveal():
            self._start_reveal()

    def _ready_to_reveal(self) -> bool:
        if not self.submissions:
            return False
        connected_eligible = [p for p in self._eligible_submitters() if p.connected]
        if not connected_eligible:
            return False
        submitted_ids = {s.player_id for s in self.submissions}
        return all(p.id in submitted_ids for p in connected_eligible)

    def close_submissions(self) -> None:
        """Force-close SUBMITTING (submission timer expiry, §8.4). Needs >=1 submission."""
        self._require_phase(Phase.SUBMITTING)
        if not self.submissions:
            raise NotAllowed("No submissions yet — round would abandon, not close")
        self._start_reveal()

    def _start_reveal(self) -> None:
        random.shuffle(self.submissions)
        self.phase = Phase.REVEALING

    def reveal_next(self, czar_id: str) -> None:
        self._require_phase(Phase.REVEALING)
        self._require_czar(czar_id)
        idx = next((i for i, s in enumerate(self.submissions) if not s.revealed), None)
        if idx is None:
            raise NotAllowed("All submissions already revealed")
        self.submissions[idx].revealed = True
        if all(s.revealed for s in self.submissions):
            self.phase = Phase.JUDGING
        self.last_activity = _now()

    def pick_winner(self, czar_id: str, submission_index: int) -> None:
        self._require_phase(Phase.JUDGING)
        self._require_czar(czar_id)
        if not (0 <= submission_index < len(self.submissions)):
            raise InvalidCard("Bad submission index")
        sub = self.submissions[submission_index]
        winner = self.get_player(sub.player_id)
        winner.score += 1
        self.last_winner = {"player_id": winner.id, "name": winner.name, "cards": sub.cards}
        for s in self.submissions:
            self.decks.white_discard.extend(s.cards)
        if self.black_card is not None:
            self.decks.black_discard.append(self.black_card)
        self.black_card = None
        self.submissions = []
        self._refill_hands()
        self._advance_czar()
        self.last_activity = _now()
        target = self.settings.score_target
        if target != "endless" and winner.score >= target:
            self.phase = Phase.GAME_OVER
        else:
            self.phase = Phase.ROUND_END

    def _advance_czar(self) -> None:
        if self.czar_order:
            self.czar_index = (self.czar_index + 1) % len(self.czar_order)
        else:
            self.czar_index = 0

    def next_round(self) -> None:
        self._require_phase(Phase.ROUND_END)
        for p in self.players:
            if not p.kicked:
                p.is_playing = True
        if len(self._active_players()) < MIN_PLAYERS:
            self.phase = Phase.LOBBY
            return
        self._begin_round()

    def rematch(self) -> None:
        self._require_phase(Phase.GAME_OVER)
        for p in self.players:
            p.score = 0
            if not p.kicked:
                p.is_playing = True
        self._rebuild_draw_piles()
        self.czar_index = 0
        self.round_no = 0
        self._deal_full_hands()
        self._begin_round()

    def skip_czar(self) -> None:
        """Host tool (timeout or discretion) abandoning a round the Czar can't finish (§8.2)."""
        self._require_phase(Phase.SUBMITTING, Phase.REVEALING, Phase.JUDGING)
        for s in self.submissions:
            owner = self.get_player(s.player_id)
            owner.hand.extend(s.cards)  # returned, never discarded (§8.2)
        self.submissions = []
        if self.black_card is not None:
            self.decks.black_discard.append(self.black_card)
            self.black_card = None
        self._advance_czar()
        self.last_activity = _now()
        if len(self._active_players()) < MIN_PLAYERS:
            self.phase = Phase.LOBBY
        else:
            self._begin_round()

    # -------------------------------------------------------------- cleanup

    def is_idle(self) -> bool:
        return not self.board_connected and not any(p.connected for p in self.players)
