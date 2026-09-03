"""Black-card parsing and JSON pack import/export.

Pure Python, no I/O beyond the explicit read_pack_json/write_pack_json
helpers (which take already-open-able paths, not sockets/DB handles).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

BLANK_RE = re.compile(r"_+")


class InvalidBlackCard(ValueError):
    """Raised when a black card has neither a blank nor a question mark."""


def normalize_text(text: str) -> str:
    """Case-fold + whitespace-collapse, used for the library's duplicate guard (§6.4)."""
    return " ".join(text.strip().casefold().split())


def parse_black_card(text: str) -> int:
    """Validate a black card's text and return its derived `pick` count (§6.2, §5.6).

    - A card with one or more literal `_` blanks: pick = number of blanks.
    - A card with zero blanks that ends in `?` (a question): pick = 1.
    - A card with zero blanks and no `?`: invalid.
    """
    text = text.strip()
    blanks = BLANK_RE.findall(text)
    if blanks:
        return len(blanks)
    if text.endswith("?"):
        return 1
    raise InvalidBlackCard(
        "Black card must contain a blank ('_') or be a question ending in '?'."
    )


def is_question(text: str) -> bool:
    """A question card has zero blanks (§6.2) — its submission renders below the card."""
    return not BLANK_RE.search(text)


@dataclass
class Pack:
    id: str
    name: str
    white: list[str]
    black: list[str]


def read_pack_json(path: str | Path) -> Pack:
    data = json.loads(Path(path).read_text())
    return Pack(
        id=data["id"],
        name=data["name"],
        white=list(data.get("white", [])),
        black=list(data.get("black", [])),
    )


def write_pack_json(path: str | Path, pack: Pack) -> None:
    Path(path).write_text(
        json.dumps(
            {"id": pack.id, "name": pack.name, "white": pack.white, "black": pack.black},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
