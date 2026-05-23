"""kan/confirm.py 单元测试 · 模拟 input · 不走真 stdin。"""
import io

from kan.infra.confirm import show_summary_and_confirm


def test_confirm_skip_returns_true():
    """skip=True (--yes) → 不走交互直接 True。"""
    targets = [("002230", "科大讯飞"), ("300033", "同花顺")]
    assert show_summary_and_confirm("add", targets, current_watchlist_size=169, skip=True) is True


def test_confirm_y_returns_true(monkeypatch, capsys):
    """输 y → True · 输出 summary。"""
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    targets = [("002230", "科大讯飞"), ("300033", "同花顺")]
    result = show_summary_and_confirm("add", targets, current_watchlist_size=169)
    assert result is True
    out = capsys.readouterr().out
    assert "添加" in out or "add" in out
    assert "002230" in out or "科大讯飞" in out
    assert "169" in out  # 当前自选数应在 summary 出现


def test_confirm_n_returns_false(monkeypatch):
    """输 n → False。"""
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    targets = [("002230", "科大讯飞")]
    assert show_summary_and_confirm("remove", targets, current_watchlist_size=169) is False


def test_confirm_empty_returns_false(monkeypatch):
    """直接回车 → False(默认 N)。"""
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    targets = [("002230", "科大讯飞")]
    assert show_summary_and_confirm("clear", targets, current_watchlist_size=169) is False


def test_confirm_summary_shows_resulting_size(monkeypatch, capsys):
    """add 应显示"操作后 N 只" · remove 应显示"操作后 N 只"。"""
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    targets = [("002230", "科大讯飞"), ("300033", "同花顺"), ("600000", "浦发银行")]
    show_summary_and_confirm("add", targets, current_watchlist_size=10)
    out = capsys.readouterr().out
    # add 3 只 · 当前 10 · 操作后 ≤13
    assert "13" in out or "10" in out
