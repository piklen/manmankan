from kan.core.models import Board


def test_board_fields():
    b = Board(code="801080", name="半导体", level=2, size=131)
    assert b.code == "801080"
    assert b.level == 2


def test_board_json_roundtrip():
    b = Board(code="801080", name="半导体", level=2, size=131)
    restored = Board(**b.model_dump())
    assert restored == b
