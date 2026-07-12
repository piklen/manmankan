"""DoH DNS 解析器单元测试 · bypass Clash fake-ip DNS 劫持。"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from kan.infra import doh_dns

# ── 测试前保存原始状态 · 测试后恢复 ───────────────────────────────────────

@pytest.fixture(autouse=True)
def _restore_doh_state():
    """每个测试后恢复 doh_dns 模块的全局状态，防止测试间互相污染。"""
    original_getaddrinfo = socket.getaddrinfo
    original_patched = doh_dns._PATCHED
    original_session = doh_dns._session
    original_cache = dict(doh_dns._cache)
    yield
    socket.getaddrinfo = original_getaddrinfo
    doh_dns._PATCHED = original_patched
    doh_dns._session = original_session
    doh_dns._cache.clear()
    doh_dns._cache.update(original_cache)


# ── _resolve_via_doh ────────────────────────────────────────────────────

class TestResolveViaDoh:
    """DoH 解析：成功 / CNAME 递归 / 全部失败。"""

    def test_resolve_returns_a_record_ip(self):
        """A 记录 → 直接返回 IP。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "Answer": [{"type": 1, "data": "10.0.0.1"}],
        }
        mock_session.get.return_value = mock_resp

        with patch.object(doh_dns, "_get_session", return_value=mock_session):
            result = doh_dns._resolve_via_doh("q.10jqka.com.cn")
            assert result == "10.0.0.1"

    def test_resolve_follows_cname_then_returns_ip(self):
        """CNAME 记录 → 递归解析目标域名 → 返回 IP。"""
        mock_session = MagicMock()
        mock_resp1 = MagicMock()
        mock_resp1.raise_for_status = MagicMock()
        mock_resp1.json.return_value = {
            "Answer": [{"type": 5, "data": "cdn.example.com."}],
        }
        mock_resp2 = MagicMock()
        mock_resp2.raise_for_status = MagicMock()
        mock_resp2.json.return_value = {
            "Answer": [{"type": 1, "data": "10.0.0.2"}],
        }
        mock_session.get.side_effect = [mock_resp1, mock_resp2]

        with patch.object(doh_dns, "_get_session", return_value=mock_session):
            result = doh_dns._resolve_via_doh("origin.example.com")
            assert result == "10.0.0.2"
            assert mock_session.get.call_count == 2

    def test_cname_loop_returns_none(self):
        """CNAME 指向自身 → 防死循环返回 None。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "Answer": [{"type": 5, "data": "loop.example.com."}],
        }
        mock_session.get.return_value = mock_resp

        with patch.object(doh_dns, "_get_session", return_value=mock_session):
            result = doh_dns._resolve_via_doh("loop.example.com")
            assert result is None

    def test_all_endpoints_fail_returns_none(self):
        """所有 DoH 端点都抛异常 → 返回 None。"""
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("connection refused")

        with patch.object(doh_dns, "_get_session", return_value=mock_session):
            result = doh_dns._resolve_via_doh("fail.example.com")
            assert result is None

    def test_no_a_record_in_answer_returns_none(self):
        """Answer 数组中没有 A 记录也没有 CNAME → 返回 None。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "Answer": [{"type": 28, "data": "::1"}],  # AAAA only
        }
        mock_session.get.return_value = mock_resp

        with patch.object(doh_dns, "_get_session", return_value=mock_session):
            result = doh_dns._resolve_via_doh("no-a.example.com")
            assert result is None

    def test_first_endpoint_fails_second_succeeds(self):
        """第一个 DoH 端点失败 → fallback 第二个成功。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "Answer": [{"type": 1, "data": "10.0.0.3"}],
        }
        # 第一个失败，第二个成功
        mock_session.get.side_effect = [Exception("timeout"), mock_resp]

        with patch.object(doh_dns, "_get_session", return_value=mock_session):
            result = doh_dns._resolve_via_doh("fallback.example.com")
            assert result == "10.0.0.3"
            assert mock_session.get.call_count == 2


# ── _cached_resolve ─────────────────────────────────────────────────────

class TestCachedResolve:
    """带 TTL 缓存的 DoH 解析。"""

    def test_cache_hit_returns_cached_ip(self):
        """缓存命中 → 直接返回缓存 IP，不调 DoH。"""
        with patch.object(doh_dns, "_resolve_via_doh") as mock_resolve:
            doh_dns._cache["cached.example.com"] = ("1.2.3.4", float("inf"))
            result = doh_dns._cached_resolve("cached.example.com")
            assert result == "1.2.3.4"
            mock_resolve.assert_not_called()

    def test_cache_expired_calls_doh_again(self):
        """缓存过期 → 重新调用 DoH 解析。"""
        with patch.object(doh_dns, "_resolve_via_doh", return_value="5.6.7.8") as mock_resolve:
            doh_dns._cache["old.example.com"] = ("0.0.0.0", 0)  # TTL=0 已过期
            result = doh_dns._cached_resolve("old.example.com")
            assert result == "5.6.7.8"
            mock_resolve.assert_called_once_with("old.example.com")

    def test_cache_miss_calls_doh_and_stores(self):
        """缓存未命中 → 调 DoH 并写入缓存。"""
        with patch.object(doh_dns, "_resolve_via_doh", return_value="9.9.9.9") as mock_resolve:
            result = doh_dns._cached_resolve("new.example.com")
            assert result == "9.9.9.9"
            mock_resolve.assert_called_once_with("new.example.com")
            # 缓存已写入
            cached = doh_dns._cache.get("new.example.com")
            assert cached is not None
            assert cached[0] == "9.9.9.9"

    def test_cache_miss_doh_returns_none_not_stored(self):
        """DoH 返回 None 时不写入缓存。"""
        doh_dns._cache.clear()
        with patch.object(doh_dns, "_resolve_via_doh", return_value=None):
            result = doh_dns._cached_resolve("dead.example.com")
            assert result is None
            assert "dead.example.com" not in doh_dns._cache


# ── _patched_getaddrinfo ────────────────────────────────────────────────

class TestPatchedGetaddrinfo:
    """socket.getaddrinfo monkeypatch 行为。"""

    def test_non_bypass_domain_uses_original(self):
        """不在白名单的域名 → 直接调原始 getaddrinfo。"""
        with patch.object(doh_dns, "_original_getaddrinfo") as mock_orig:
            doh_dns._patched_getaddrinfo("example.com", 443)
            mock_orig.assert_called_once_with("example.com", 443, 0, 0, 0, 0)

    def test_bypass_domain_with_cached_ip_substitutes_host(self):
        """白名单域名 + 缓存命中 → 用真实 IP 替换 host。"""
        with patch.object(doh_dns, "_original_getaddrinfo") as mock_orig, \
             patch.object(doh_dns, "_cached_resolve", return_value="1.2.3.4"):
            doh_dns._patched_getaddrinfo("q.10jqka.com.cn", 443)
            mock_orig.assert_called_once_with("1.2.3.4", 443, 0, 0, 0, 0)

    def test_bypass_domain_cache_miss_falls_back(self):
        """白名单域名但缓存未命中 → 原始 host 传给 getaddrinfo。"""
        with patch.object(doh_dns, "_original_getaddrinfo") as mock_orig, \
             patch.object(doh_dns, "_cached_resolve", return_value=None):
            doh_dns._patched_getaddrinfo("www.swsresearch.com", 80)
            mock_orig.assert_called_once_with("www.swsresearch.com", 80, 0, 0, 0, 0)

    def test_non_string_host_passed_through(self):
        """host 不是字符串（可能是 IP 或 bytes）→ 原样透传。"""
        with patch.object(doh_dns, "_original_getaddrinfo") as mock_orig:
            doh_dns._patched_getaddrinfo("1.1.1.1", 53)
            mock_orig.assert_called_once_with("1.1.1.1", 53, 0, 0, 0, 0)

    def test_full_flags_passed_through(self):
        """额外参数 family/type/proto/flags 原样透传。"""
        with patch.object(doh_dns, "_original_getaddrinfo") as mock_orig:
            doh_dns._patched_getaddrinfo(
                "example.com", 443,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_PASSIVE,
            )
            mock_orig.assert_called_once_with(
                "example.com", 443,
                socket.AF_INET, socket.SOCK_STREAM,
                socket.IPPROTO_TCP, socket.AI_PASSIVE,
            )


# ── install / is_installed ──────────────────────────────────────────────

class TestInstall:
    """安装与状态查询。"""

    def test_install_patches_socket_getaddrinfo(self):
        """install 激活 monkeypatch · socket.getaddrinfo 指向实现。"""
        try:
            doh_dns.install()
            assert doh_dns.is_installed()
            assert socket.getaddrinfo is doh_dns._patched_getaddrinfo
        finally:
            socket.getaddrinfo = doh_dns._original_getaddrinfo
            doh_dns._PATCHED = False

    def test_install_is_idempotent(self):
        """多次 install 不会重复 patch。"""
        try:
            doh_dns.install()
            patched = socket.getaddrinfo
            doh_dns.install()
            assert socket.getaddrinfo is patched
        finally:
            socket.getaddrinfo = doh_dns._original_getaddrinfo
            doh_dns._PATCHED = False

    def test_is_installed_false_before_install(self):
        """未 install 时 is_installed 返回 False。"""
        doh_dns._PATCHED = False
        assert not doh_dns.is_installed()

    def test_is_installed_true_after_install(self):
        """install 后 is_installed 返回 True。"""
        try:
            doh_dns.install()
            assert doh_dns.is_installed()
        finally:
            socket.getaddrinfo = doh_dns._original_getaddrinfo
            doh_dns._PATCHED = False


# ── warmup ──────────────────────────────────────────────────────────────

class TestWarmup:
    """预热 DNS 缓存。"""

    def test_warmup_resolves_all_bypass_domains(self):
        """预热解析所有白名单域名。"""
        with patch.object(doh_dns, "_cached_resolve", return_value="1.1.1.1") as mock_resolve:
            results = doh_dns.warmup()
            assert len(results) == len(doh_dns._BYPASS_DOMAINS)
            for domain in doh_dns._BYPASS_DOMAINS:
                assert results[domain] == "1.1.1.1"
            assert mock_resolve.call_count == len(doh_dns._BYPASS_DOMAINS)

    def test_warmup_handles_failures(self):
        """预热中部分域名解析失败不影响其他。"""
        def _fail_some(domain):
            return None if "push2" in domain else "1.1.1.1"

        with patch.object(doh_dns, "_cached_resolve", side_effect=_fail_some):
            results = doh_dns.warmup()
            assert len(results) == len(doh_dns._BYPASS_DOMAINS)
            for domain in doh_dns._BYPASS_DOMAINS:
                if "push2" in domain:
                    assert results[domain] is None
                else:
                    assert results[domain] == "1.1.1.1"


# ── 并发安全 ────────────────────────────────────────────────────────────

class TestThreadSafety:
    """补丁本身的线程安全（锁保护）。"""

    def test_install_is_thread_safe(self):
        """install 的 _LOCK 确保只 patch 一次即使多线程并发调用。"""
        import threading

        errors = []

        def _try_install():
            try:
                doh_dns.install()
                assert socket.getaddrinfo is doh_dns._patched_getaddrinfo
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_try_install) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        try:
            assert doh_dns.is_installed()
            assert socket.getaddrinfo is doh_dns._patched_getaddrinfo
        finally:
            socket.getaddrinfo = doh_dns._original_getaddrinfo
            doh_dns._PATCHED = False


# ── _get_session ────────────────────────────────────────────────────────

class TestGetSession:
    """HTTP session 工厂。"""

    def test_get_session_creates_and_reuses(self):
        """_get_session 懒加载并复用 session 实例。"""
        doh_dns._session = None
        s1 = doh_dns._get_session()
        s2 = doh_dns._get_session()
        assert s1 is s2
        assert s1.trust_env is False
