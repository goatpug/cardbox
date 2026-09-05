import json

import pytest

from cardbox.library import Library


@pytest.fixture()
def lib(tmp_path):
    return Library(tmp_path / "cardbox.db")


def test_house_pack_exists_by_default(lib):
    packs = {p.id: p for p in lib.list_packs()}
    assert "house" in packs
    assert packs["house"].on_by_default is True


def test_add_card_persists_and_derives_pick(lib):
    row, is_new = lib.add_card("black", "_ is the leading cause of divorce.", author="Sharon")
    assert is_new is True
    assert row.pick == 1
    assert row.author == "Sharon"
    cards = lib.list_pack_cards("house")
    assert any(c.id == row.id for c in cards)


def test_duplicate_text_is_noop(lib):
    row1, is_new1 = lib.add_card("white", "A haunted vibrator.", author="A")
    row2, is_new2 = lib.add_card("white", "  a haunted   vibrator.  ", author="B")
    assert is_new1 is True
    assert is_new2 is False
    assert row1.id == row2.id
    # duplicate insert is a no-op: still only one row in the library
    assert len([c for c in lib.list_pack_cards("house") if c.text == row1.text]) == 1


def test_soft_delete_excludes_from_future_rooms_not_in_flight(lib):
    row, _ = lib.add_card("white", "A dud joke.", author="A")
    assert any(c.id == row.id for c in lib.get_cards_for_packs(["house"]))
    lib.soft_delete(row.id)
    assert not any(c.id == row.id for c in lib.get_cards_for_packs(["house"]))
    # an in-flight copy is a plain WhiteCard object elsewhere in memory — deleting
    # the library row cannot reach into a room's decks, so nothing to assert here
    # beyond: the library itself no longer offers it to new rooms (checked above).


def test_invalid_black_card_rejected(lib):
    with pytest.raises(ValueError):
        lib.add_card("black", "no blank and no question mark", author="A")


def test_white_card_length_limits(lib):
    with pytest.raises(ValueError):
        lib.add_card("white", "", author="A")
    with pytest.raises(ValueError):
        lib.add_card("white", "x" * 81, author="A")


def test_json_pack_import_export_roundtrip(lib, tmp_path):
    pack_path = tmp_path / "mini.json"
    pack_path.write_text(
        json.dumps(
            {
                "id": "mini",
                "name": "Mini Pack",
                "white": ["Bees.", "A rogue toaster."],
                "black": ["_ ruined Thanksgiving.", "What's in the box?"],
            }
        )
    )
    lib.seed_pack_json(pack_path)
    exported = lib.export_pack("mini")
    assert exported.id == "mini"
    assert exported.name == "Mini Pack"
    assert set(exported.white) == {"Bees.", "A rogue toaster."}
    assert set(exported.black) == {"_ ruined Thanksgiving.", "What's in the box?"}

    # re-seeding the same file is insert-if-absent: no duplicate rows
    lib.seed_pack_json(pack_path)
    assert len(lib.list_pack_cards("mini")) == 4


def test_reseeding_edited_pack_retires_removed_shipped_cards(lib, tmp_path):
    pack_path = tmp_path / "mini.json"
    pack_path.write_text(
        json.dumps({"id": "mini", "name": "Mini", "white": ["Bees.", "Old wording."], "black": ["_ ruined it."]})
    )
    lib.seed_pack_json(pack_path)
    # a player-authored card in the same pack must survive a re-seed
    lib.add_card("white", "Player card.", author="Sharon", pack_id="mini")

    pack_path.write_text(
        json.dumps({"id": "mini", "name": "Mini", "white": ["Bees.", "New wording."], "black": ["_ ruined it."]})
    )
    lib.seed_pack_json(pack_path)
    texts = {c.text for c in lib.list_pack_cards("mini")}
    assert texts == {"Bees.", "New wording.", "_ ruined it.", "Player card."}
