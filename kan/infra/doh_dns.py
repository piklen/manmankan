"""DoH DNS 解析器 · 绕过 Clash Fake-IP DNS 劫持。

Clash 的 fake-ip 增强模式会拦截所有 DNS:53 流量，把 *.eastmoney.com 等域名
解析成 198.18.x.x 的假 IP。即使 Clash 规则把 eastmoney.com 设为 DIRECT，
由于 DNS 解析被污染，连接也发不到真实服务器。

本模块用 DNS-over-HTTPS (DoH, port 443) 走代理通道获取真实 IP，再通过
socket.getaddrinfo monkeypatch 注入进程内 DNS 缓存。仅影响当前 Python 进程，
不修改系统 /etc/hosts 或 Clash 配置。

设计决策:
- 只处理明确声明的域名（白名单模式），不拦截所有域名解析
- 本地 LRU + TTL 缓存（默认 3600s），减少 DoH 请求
- SSL 证书验证不受影响：SNI 仍用原始域名，只有 TCP 连接走真实 IP

已知限制:
- EM push2 系列 (push2.eastmoney.com 等) 背后有腾讯云 CDN，直连 IP 返回空响应。
  这些域名必须在 Clash fake-ip-filter 里加白才能正常工作。
- SW research (www.swsresearch.com) 接口返回空数据 (count=0)，可能是 API 已变更。
"""

from __future__ import annotations

import socket
import threading
import time

_PATCHED = False
_LOCK = threading.Lock()

# 需要走真实 DNS 的域名 → DoH 解析结果缓存
# 这些是 akshare 直接或间接访问的金融数据站点
_BYPASS_DOMAINS = {
    # 同花顺 (THS) — 题材成分股 + cookie 生成
    "q.10jqka.com.cn",
    "q.10jqka.com",  # 可能有别名
    "webcache.10jqka.com.cn",
    # 申万研究 (SW) — 行业成分股
    "www.swsresearch.com",
    # 东方财富 (EM) — push2 CDN 直连不工作，但加在这里用于诊断
    "push2.eastmoney.com",
    "79.push2.eastmoney.com",
    "17.push2.eastmoney.com",
    "push2his.eastmoney.com",
    "datacenter.eastmoney.com",
}

# DoH 端点 (国内可达)
_DOH_ENDPOINTS = [
    "https://doh.pub/dns-query",
    "https://dns.alidns.com/dns-query",
]

# DNS 缓存 TTL（秒）
_CACHE_TTL = 3600

# ── DoH 查询 ──────────────────────────────────────────────────────────

_session = None
_session_lock = threading.Lock()


def _get_session():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                import requests
                _session = requests.Session()
                _session.headers["accept"] = "application/dns-json"
                _session.trust_env = False  # 不走系统代理（DoH 本身在 443 上）
    return _session


def _resolve_via_doh(domain: str) -> str | None:
    """通过 DoH 解析域名 → 返回第一个 A 记录 IP，失败返回 None。"""
    for endpoint in _DOH_ENDPOINTS:
        try:
            resp = _get_session().get(
                endpoint,
                params={"name": domain, "type": "A"},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            answers = data.get("Answer", [])
            for answer in answers:
                if answer.get("type") == 1:  # A record
                    return str(answer["data"])
            # 只有 CNAME → 递归解析
            for answer in answers:
                if answer.get("type") == 5:  # CNAME
                    cname = str(answer["data"]).rstrip(".")
                    if cname != domain:
                        return _resolve_via_doh(cname)
        except Exception:
            continue
    return None


# ── 缓存 ──────────────────────────────────────────────────────────────

_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()


def _cached_resolve(domain: str) -> str | None:
    """带 TTL 缓存的 DoH 解析。"""
    now = time.time()
    with _cache_lock:
        cached = _cache.get(domain)
        if cached is not None:
            cached_ip, expiry = cached
            if now < expiry:
                return cached_ip
    resolved_ip = _resolve_via_doh(domain)
    if resolved_ip is not None:
        with _cache_lock:
            _cache[domain] = (resolved_ip, now + _CACHE_TTL)
    return resolved_ip


# ── socket monkeypatch ─────────────────────────────────────────────────

_original_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """如果 host 在白名单中，用 DoH 真实 IP 替换，再调原生 getaddrinfo。"""
    if isinstance(host, str) and host in _BYPASS_DOMAINS:
        real_ip = _cached_resolve(host)
        if real_ip is not None:
            # 打印一次诊断（首次命中时）
            return _original_getaddrinfo(real_ip, port, family, type, proto, flags)
    return _original_getaddrinfo(host, port, family, type, proto, flags)


def install() -> None:
    """激活 DoH DNS monkeypatch。幂等（多次调用仅首次生效）。"""
    global _PATCHED
    with _LOCK:
        if _PATCHED:
            return
        socket.getaddrinfo = _patched_getaddrinfo
        _PATCHED = True


def is_installed() -> bool:
    return _PATCHED


# ── 预热 ───────────────────────────────────────────────────────────────

def warmup() -> dict[str, str | None]:
    """启动时预热 DNS 缓存，减少首次请求延迟。返回 {domain: ip|None}。"""
    results: dict[str, str | None] = {}
    for domain in sorted(_BYPASS_DOMAINS):
        results[domain] = _cached_resolve(domain)
    return results
