"""熔断器测试 · CircuitBreaker 持久化 / TTL / fail-open"""

import json
import threading
from datetime import datetime, timedelta

import pytest

from kan.circuit_breaker import DOWN_TTL, CircuitBreaker


@pytest.fixture
def cb_path(tmp_path):
    return tmp_path / "circuit.json"


def test_unknown_source_not_down(cb_path):
    assert not CircuitBreaker(cb_path).is_down("baostock")


def test_record_down_makes_source_down(cb_path):
    cb = CircuitBreaker(cb_path)
    cb.record("eastmoney", ok=False)
    assert cb.is_down("eastmoney")


def test_record_ok_clears_down(cb_path):
    cb = CircuitBreaker(cb_path)
    cb.record("eastmoney", ok=False)
    cb.record("eastmoney", ok=True)
    assert not cb.is_down("eastmoney")


def test_down_state_persists_to_disk(cb_path):
    CircuitBreaker(cb_path).record("sina", ok=False)
    assert cb_path.exists()
    assert "sina" in json.loads(cb_path.read_text())


def test_down_state_persists_across_instances(cb_path):
    """实例 A 记 down → 新实例 B 同路径加载 · 仍 down（跨进程语义）。"""
    CircuitBreaker(cb_path).record("tencent", ok=False)
    assert CircuitBreaker(cb_path).is_down("tencent")


def test_down_ttl_expires(cb_path):
    """down 超过 DOWN_TTL → is_down false（自动重新探测）。"""
    stale = (datetime.now() - DOWN_TTL - timedelta(minutes=1)).isoformat()
    cb_path.write_text(json.dumps({"baostock": stale}))
    assert not CircuitBreaker(cb_path).is_down("baostock")


def test_down_within_ttl_still_down(cb_path):
    fresh = (datetime.now() - timedelta(minutes=1)).isoformat()
    cb_path.write_text(json.dumps({"baostock": fresh}))
    assert CircuitBreaker(cb_path).is_down("baostock")


def test_corrupt_json_fails_open(cb_path):
    """circuit.json 损坏 → 视作空 · 不崩 · 所有源都可试。"""
    cb_path.write_text("{not valid json")
    assert not CircuitBreaker(cb_path).is_down("baostock")


def test_missing_file_fails_open(cb_path):
    cb = CircuitBreaker(cb_path)  # 文件不存在
    assert not cb.is_down("baostock")
    cb.record("baostock", ok=True)  # ok 记录不应崩


def test_bad_entry_skipped_others_kept(cb_path):
    """单条脏数据不废掉整个文件 · 好条目仍生效。"""
    fresh = (datetime.now() - timedelta(minutes=1)).isoformat()
    cb_path.write_text(json.dumps({"baostock": "garbage", "sina": fresh}))
    cb = CircuitBreaker(cb_path)
    assert not cb.is_down("baostock")  # 坏条目被跳过 → 视作未 down
    assert cb.is_down("sina")          # 好条目仍生效


def test_record_ok_when_already_ok_no_write(cb_path):
    """本就 ok 的源记 ok → 不产生 circuit.json（无谓写盘）。"""
    CircuitBreaker(cb_path).record("baostock", ok=True)
    assert not cb_path.exists()


def test_concurrent_records_no_corruption(cb_path):
    """多线程并发 record · 文件始终是合法 json。"""
    cb = CircuitBreaker(cb_path)
    sources = ["baostock", "sina", "eastmoney", "tencent"] * 5
    threads = [threading.Thread(target=cb.record, args=(s, False)) for s in sources]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(json.loads(cb_path.read_text())) == {
        "baostock", "sina", "eastmoney", "tencent",
    }
