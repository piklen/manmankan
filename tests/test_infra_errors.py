from __future__ import annotations

from pathlib import Path

from kan.infra.errors import network_error_msg, safe_error_msg


def test_safe_error_msg_redacts_paths_and_truncates_home_path():
    home_file = Path.home() / "secret" / "token.txt"
    msg = safe_error_msg(
        RuntimeError(f"failed at {home_file} and /tmp/cache/raw.csv because payload is too long"),
        max_len=55,
    )

    assert str(Path.home()) not in msg
    assert "~" in msg
    assert "<...>/raw.csv" in msg
    assert msg.endswith("...")
    assert len(msg) == 55


def test_network_error_msg_simplifies_common_network_errors():
    assert network_error_msg("HTTPSConnectionPool Max retries exceeded") == (
        "网络异常 · 请检查连接或稍后重试"
    )


def test_network_error_msg_simplifies_no_data_errors():
    assert network_error_msg("无效股票代码或无数据: 999999") == "无数据（可能停牌 / 退市）"


def test_network_error_msg_falls_back_to_safe_short_message():
    msg = network_error_msg("/tmp/cache/raw.csv failed with non-network validation error")

    assert msg.startswith("<...>/raw.csv failed")
    assert len(msg) <= 60
