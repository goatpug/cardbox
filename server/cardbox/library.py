"""The card library: persistent SQLite store for custom + shipped cards (§6.4).

Plain stdlib `sqlite3`, synchronous. Writes are a card at a time and rare, so
no aiosqlite / connection pool is needed — this is called from the async app
via a thread-safe connection (`check_same_thread=False`); callers should
still avoid calling it from more than one place at a time per room action,
which the app's single-event-loop dispatch already guarantees.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import cards as cardsmod

SCHEMA = """
CREATE TABLE IF NOT EXISTS packs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  on_by_default INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('white','black')),
  text TEXT NOT NULL,
  pick INTEGER NOT NULL DEFAULT 1,
  author TEXT,
  pack_id TEXT NOT NULL REFERENCES packs(id),
  created_at TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0
);
"""

WHITE_MAX_LEN = 80
BLACK_MAX_LEN = 140


@dataclass(frozen=True)
class CardRow:
    id: int
    kind: str
    text: str
    pick: int
    author: str | None
    pack_id: str


@dataclass(frozen=True)
class PackRow:
    id: str
    name: str
    on_by_default: bool


class Library:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._ensure_pack("house", "House", True)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ packs

    def _ensure_pack(self, pack_id: str, name: str, on_by_default: bool) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO packs (id, name, on_by_default) VALUES (?,?,?)",
            (pack_id, name, int(on_by_default)),
        )
        self._conn.commit()

    def seed_pack_json(self, path: str | Path) -> None:
        """Load a shipped JSON pack, insert-if-absent by pack id (§6.4)."""
        pack = cardsmod.read_pack_json(path)
        self._ensure_pack(pack.id, pack.name, True)
        for text in pack.white:
            self.add_card("white", text, author=None, pack_id=pack.id)
        for text in pack.black:
            self.add_card("black", text, author=None, pack_id=pack.id)

    def list_packs(self) -> list[PackRow]:
        cur = self._conn.execute("SELECT id, name, on_by_default FROM packs ORDER BY name")
        return [PackRow(id=r[0], name=r[1], on_by_default=bool(r[2])) for r in cur.fetchall()]

    def export_pack(self, pack_id: str) -> cardsmod.Pack:
        row = self._conn.execute("SELECT id, name FROM packs WHERE id=?", (pack_id,)).fetchone()
        if not row:
            raise KeyError(f"No such pack: {pack_id}")
        cards = self.list_pack_cards(pack_id)
        return cardsmod.Pack(
            id=row[0],
            name=row[1],
            white=[c.text for c in cards if c.kind == "white"],
            black=[c.text for c in cards if c.kind == "black"],
        )

    # ------------------------------------------------------------------ cards

    def _find_duplicate(self, kind: str, text: str) -> CardRow | None:
        norm = cardsmod.normalize_text(text)
        cur = self._conn.execute(
            "SELECT id, kind, text, pick, author, pack_id FROM cards WHERE kind=? AND deleted=0", (kind,)
        )
        for row in cur.fetchall():
            if cardsmod.normalize_text(row[2]) == norm:
                return CardRow(*row)
        return None

    def add_card(self, kind: str, text: str, author: str | None, pack_id: str = "house") -> tuple[CardRow, bool]:
        """Insert a card (§5.6). Returns (row, is_new) — duplicate text is a no-op (§6.4)."""
        text = text.strip()
        if kind not in ("white", "black"):
            raise ValueError("kind must be 'white' or 'black'")
        if kind == "white":
            if not (1 <= len(text) <= WHITE_MAX_LEN):
                raise ValueError(f"White card text must be 1-{WHITE_MAX_LEN} chars")
            pick = 1
        else:
            if not (1 <= len(text) <= BLACK_MAX_LEN):
                raise ValueError(f"Black card text must be 1-{BLACK_MAX_LEN} chars")
            pick = cardsmod.parse_black_card(text)

        dup = self._find_duplicate(kind, text)
        if dup:
            return dup, False

        created_at = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO cards (kind, text, pick, author, pack_id, created_at, deleted) VALUES (?,?,?,?,?,?,0)",
            (kind, text, pick, author, pack_id, created_at),
        )
        self._conn.commit()
        return CardRow(id=cur.lastrowid, kind=kind, text=text, pick=pick, author=author, pack_id=pack_id), True

    def get_cards_for_packs(self, pack_ids: list[str]) -> list[CardRow]:
        if not pack_ids:
            return []
        placeholders = ",".join("?" for _ in pack_ids)
        cur = self._conn.execute(
            f"SELECT id, kind, text, pick, author, pack_id FROM cards "
            f"WHERE deleted=0 AND pack_id IN ({placeholders})",
            list(pack_ids),
        )
        return [CardRow(*row) for row in cur.fetchall()]

    def list_pack_cards(self, pack_id: str) -> list[CardRow]:
        cur = self._conn.execute(
            "SELECT id, kind, text, pick, author, pack_id FROM cards "
            "WHERE pack_id=? AND deleted=0 ORDER BY id DESC",
            (pack_id,),
        )
        return [CardRow(*row) for row in cur.fetchall()]

    def soft_delete(self, card_id: int) -> None:
        self._conn.execute("UPDATE cards SET deleted=1 WHERE id=?", (card_id,))
        self._conn.commit()
