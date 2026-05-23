"""manmankan 自动更新 · PyPI 版本查询 + 包管理器派发

设计要点:
- urllib.request 标准库 · 不引新依赖 · 3s timeout 避免 atexit 拖累
- daily cache: 同一天再启动跳过网络请求 (kan.storage.config 持久化 last_check_date)
- 静默 fallback: 网络失败 / PyPI 不可达 / 解析失败 → 返回 None · 不抛异常
- 复用 cli._detect_install_method 的检测模式 · 加 upgrade 命令派发
- caller 调用: cli.py 的 atexit hook (cache 命中默认) + kan update 命令 (force=True 强制查)
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from typing import Literal, NamedTuple

from rich.console import Console

from kan import __version__
from kan.storage import config
from kan.infra.log import debug_log

PYPI_URL = "https://pypi.org/pypi/manmankan/json"
USER_AGENT = f"manmankan/{__version__}"
NETWORK_TIMEOUT = 3.0    # 短 timeout 避免 atexit 拖累命令结束
UPGRADE_TIMEOUT = 120.0  # upgrade 命令本身 2 分钟够用


class UpdateInfo(NamedTuple):
    """check_for_updates 返回结果。"""
    current: str
    latest: str | None    # None = 网络失败 / 没拿到版本号
    has_update: bool
    from_cache: bool      # True = daily cache 命中 · False = 实际发了 PyPI 请求


class DetectedInstall(NamedTuple):
    """detect_install_method 返回结果。"""
    name: str
    upgrade_cmd: list[str]


def fetch_latest_version_from_pypi() -> str | None:
    """查 PyPI JSON API · 任何异常吞掉返回 None。

    保证 atexit hook 在断网 / DNS 故障 / PyPI 维护时不破坏主命令体验。
    """
    try:
        req = urllib.request.Request(
            PYPI_URL,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as resp:
            data = json.load(resp)
    except Exception as e:
        # 合并双层 catch (specific + broad 行为 equivalent · 删 dead defensive code)
        # 网络/解析/任何异常 → 静默返 None · debug log 供排查
        debug_log(__name__, "PyPI version fetch", e)
        return None
    if not isinstance(data, dict):
        return None
    info = data.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return version if isinstance(version, str) else None


def is_newer(latest: str, current: str) -> bool:
    """版本号比较 · packaging.version 优先 · fallback 到字符串元组比较。"""
    try:
        from packaging.version import Version
        return Version(latest) > Version(current)
    except Exception as e:
        # packaging.Version parse 失败 (罕见 · e.g. 非 PEP 440 版本)
        # fallback 到 tuple 比较 · debug log 让 maintainer 知道何时走 fallback
        debug_log(__name__, f"Version parse fallback (latest={latest!r}, current={current!r})", e)
        try:
            a = tuple(int(x) for x in latest.split(".") if x.isdigit())
            b = tuple(int(x) for x in current.split(".") if x.isdigit())
            return a > b
        except (ValueError, AttributeError):
            return False


def check_for_updates(force: bool = False) -> UpdateInfo:
    """主检查入口 · daily cache + 静默 fallback。

    Args:
        force: True = 跳过 cache 强制查 PyPI (kan update 命令用)
               False = 当天命中 cache 跳过网络请求 (atexit hook 默认)
    """
    current = __version__
    cfg = config.load()
    today = date.today().isoformat()

    if not force and cfg.get("last_check_date") == today:
        latest_seen = cfg.get("latest_seen_version")
        if isinstance(latest_seen, str):
            return UpdateInfo(
                current=current,
                latest=latest_seen,
                has_update=is_newer(latest_seen, current),
                from_cache=True,
            )

    latest = fetch_latest_version_from_pypi()
    if latest is None:
        return UpdateInfo(current, None, False, False)

    cfg["last_check_date"] = today
    cfg["latest_seen_version"] = latest
    # cache 写失败不影响检查结果
    with contextlib.suppress(OSError):
        config.save(cfg)

    return UpdateInfo(
        current=current,
        latest=latest,
        has_update=is_newer(latest, current),
        from_cache=False,
    )


def detect_install_method() -> DetectedInstall:
    """检测当前 kan 怎么装的 · 返回 (name, upgrade_argv)。

    通过 sys.executable 路径模式判断:
      - uv tool: ~/.local/share/uv/tools/manmankan/bin/python
      - pipx: ~/.local/pipx/venvs/manmankan/bin/python
      - pip / venv: 含 site-packages 或 .venv
    """
    exe = sys.executable
    # v0.0.4.4: 全部命令改用 force-reinstall 模式 · 避免 partial state 升级
    # 老 .so cache 不重链导致 macOS Gatekeeper 拒载等场景 (v0.0.4.3 ***REMOVED***根因)
    if "uv/tools" in exe and "manmankan" in exe:
        return DetectedInstall("uv tool", ["uv", "tool", "install", "--reinstall", "manmankan"])
    if "pipx/venvs/manmankan" in exe:
        return DetectedInstall("pipx", ["pipx", "install", "--force", "manmankan"])
    if "site-packages" in exe or ".venv" in exe:
        return DetectedInstall(
            "pip / venv",
            [exe, "-m", "pip", "install", "--force-reinstall", "manmankan"],
        )
    return DetectedInstall(
        "uv tool (推测)",
        ["uv", "tool", "install", "--reinstall", "manmankan"],
    )


UpgradeStatus = Literal["success", "failed"]


def run_upgrade(console: Console | None = None) -> tuple[UpgradeStatus, str]:
    """运行升级命令 · 返回 (status, 描述消息)。

    所有异常吞掉 · 不让 caller (atexit hook / kan update 命令) 受影响。

    Args:
        console: 可选 rich Console (TTY 下显示 spinner · 非 TTY 自动退化静默)
                 caller 传入自己的 console 保持输出风格一致 · None 则建 stderr console
                 (注：rich.Console.status 在 is_terminal=False 时不干扰 stdout pipe)
    """
    install = detect_install_method()
    if console is None:
        console = Console(stderr=True)

    try:
        # spinner 在 TTY 下转、非 TTY 下退化为单行打印 · 不破坏 pipe / CI
        with console.status(
            f"[cyan]下载并安装中...[/cyan] [dim]({install.name})[/dim]",
            spinner="dots",
        ):
            result = subprocess.run(
                install.upgrade_cmd,
                capture_output=True,
                text=True,
                timeout=UPGRADE_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        return "failed", f"{install.name} upgrade 超时 (>{int(UPGRADE_TIMEOUT)}s) · 请手动重试"
    except FileNotFoundError:
        return "failed", f"{install.name} 命令未找到 · 请检查 PATH"
    except Exception as e:
        return "failed", f"{install.name} upgrade 异常: {type(e).__name__}"

    if result.returncode == 0:
        # v0.0.4.4: 升级文件下载成功 ≠ 装得起来 · 跑 import smoke 验证
        # 防 v0.0.4.3 类***REMOVED*** (deps partial state · old .so cache 不重链)
        try:
            with console.status("[cyan]验证安装...[/cyan]", spinner="dots"):
                smoke = subprocess.run(
                    [sys.executable, "-c",
                     "import kan; from kan import scanner, fetcher, watchlist"],
                    capture_output=True, text=True, timeout=10,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return "success", install.name  # smoke 自身失败不阻塞 · 信任 returncode
        if smoke.returncode != 0:
            smoke_err = (smoke.stderr.strip() or smoke.stdout.strip())[:300]
            return "failed", (
                f"{install.name} 升级文件已下载但导入失败 · 建议手动 reinstall:\n"
                f"  uv tool install manmankan --reinstall\n"
                f"  或 pipx install manmankan --force\n"
                f"详情: {smoke_err}"
            )
        return "success", install.name

    err = (result.stderr.strip() or result.stdout.strip())[:500]
    return "failed", f"{install.name} upgrade 退出码 {result.returncode}\n{err}"
