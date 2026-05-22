# 热榜扫描功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `kan` 新增 `--hot rank|surge` 参数,把东方财富人气榜/飙升榜当作"临时自选股"来源,套用现有多周期位置 / 连续涨跌扫描。

**Architecture:** 镜像已有的 `--industry` 模式。新建 `kan/hot.py` 数据子系统(对标 `boards.py`),在 `_scan_targets.py` 的 `resolve_scan_targets()` 加第三个分支(industry / hot / 自选),`scan` / `low` / `high` / `trend` / `fetch` 五个命令各加一个 `--hot` 选项透传。热榜模式下渲染层多一列"榜"(名次)。

**Tech Stack:** Python 3.10+ · typer(CLI)· akshare(数据源)· pandas · rich(渲染)· pytest(测试)· ruff(lint)。

**前置:** 工作分支 `feat/v0.0.5.0`(已在该分支)。设计依据 `docs/design-hot-list.md`。所有 `pytest` / `ruff` 命令在仓库根目录运行。

---

## Task 1: `paths.py` 新增 `HOT_DIR`

**Files:**
- Modify: `kan/paths.py:30` 和 `kan/paths.py:49-57`

- [ ] **Step 1: 新增 HOT_DIR 常量**

在 `kan/paths.py` 找到这一行:

```python
BOARDS_DIR = BASE_DIR / "boards"
```

在它下面加一行:

```python
BOARDS_DIR = BASE_DIR / "boards"
HOT_DIR = BASE_DIR / "hot"
```

- [ ] **Step 2: 在 `ensure_dirs()` 里创建 HOT_DIR**

找到 `ensure_dirs()` 函数体:

```python
def ensure_dirs() -> None:
    """确保数据目录存在。

    v0.0.4.4: mode=0o700 保护用户金融持仓画像（防同机其他用户/容器逃逸/SSH 多用户跳板机）。
    """
    BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    BOARDS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
```

在最后一行后加一行:

```python
    BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    BOARDS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    HOT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
```

- [ ] **Step 3: 跑现有 paths 测试确认无回归**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: PASS(全部通过 · 新常量不影响现有断言)

- [ ] **Step 4: Commit**

```bash
git add kan/paths.py
git commit -m "feat(paths): add HOT_DIR for hot-list cache"
```

---

## Task 2: 新建 `kan/hot.py` 数据模块

**Files:**
- Create: `kan/hot.py`
- Test: `tests/test_hot.py`

- [ ] **Step 1: 写失败测试 `tests/test_hot.py`**

创建 `tests/test_hot.py`,完整内容:

```python
"""kan/hot.py 单元测试 · mock akshare · 不走真网络。"""
import json

import pandas as pd
import pytest

from kan import hot
from kan.hot import HotEntry, HotList, HotListUnavailableError


@pytest.fixture(autouse=True)
def _isolate_hot_dir(tmp_path, monkeypatch):
    """hot cache 指向 tmp · 杜绝读写真实 ~/.local/share/kan/hot/。"""
    hdir = tmp_path / "hot"
    hdir.mkdir()
    monkeypatch.setattr(hot, "HOT_DIR", hdir)
    return hdir


def _fake_rank_df(rows):
    """rows: list of [当前排名, 代码, 股票名称]。"""
    return pd.DataFrame(rows, columns=["当前排名", "代码", "股票名称"])


def test_fetch_hot_list_normalizes_codes(monkeypatch):
    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([
            [1, "SZ000725", "京东方Ａ"],
            [2, "SH600519", "贵州茅台"],
        ]),
    )
    entries = hot.fetch_hot_list(HotList.RANK, force=True)
    assert entries == [
        HotEntry(rank=1, symbol="000725", name="京东方Ａ"),
        HotEntry(rank=2, symbol="600519", name="贵州茅台"),
    ]


def test_fetch_hot_list_skips_bad_codes(monkeypatch):
    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([
            [1, "SZ000725", "京东方Ａ"],
            [2, "HK00700", "腾讯控股"],   # 港股 · 归一化后非 6 位数字 → 跳过
        ]),
    )
    entries = hot.fetch_hot_list(HotList.RANK, force=True)
    assert len(entries) == 1
    assert entries[0].symbol == "000725"


def test_fetch_hot_list_uses_cache(monkeypatch, _isolate_hot_dir):
    cache = _isolate_hot_dir / "hot_rank.json"
    cache.write_text(
        json.dumps([{"rank": 1, "symbol": "600519", "name": "贵州茅台"}]),
        encoding="utf-8",
    )

    def _boom():
        raise AssertionError("不应调用 akshare · 应命中 cache")

    monkeypatch.setattr("akshare.stock_hot_rank_em", _boom)
    entries = hot.fetch_hot_list(HotList.RANK)
    assert entries[0].name == "贵州茅台"


def test_fetch_hot_list_empty_raises(monkeypatch):
    monkeypatch.setattr("akshare.stock_hot_rank_em", lambda: pd.DataFrame())
    with pytest.raises(HotListUnavailableError):
        hot.fetch_hot_list(HotList.RANK, force=True)


def test_fetch_hot_list_akshare_error_raises(monkeypatch):
    def _raise():
        raise ConnectionError("network down")

    monkeypatch.setattr("akshare.stock_hot_rank_em", _raise)
    with pytest.raises(HotListUnavailableError):
        hot.fetch_hot_list(HotList.RANK, force=True)


def test_fetch_hot_list_all_bad_codes_raises(monkeypatch):
    monkeypatch.setattr(
        "akshare.stock_hot_rank_em",
        lambda: _fake_rank_df([[1, "HK00700", "腾讯控股"]]),
    )
    with pytest.raises(HotListUnavailableError):
        hot.fetch_hot_list(HotList.RANK, force=True)


def test_surge_uses_stock_hot_up_em(monkeypatch):
    called = []
    monkeypatch.setattr(
        "akshare.stock_hot_up_em",
        lambda: called.append("up") or _fake_rank_df([[5, "SH603759", "海天股份"]]),
    )
    entries = hot.fetch_hot_list(HotList.SURGE, force=True)
    assert called == ["up"]
    assert entries[0].symbol == "603759"


def test_hot_list_name():
    assert hot.hot_list_name(HotList.RANK) == "东财人气榜"
    assert hot.hot_list_name(HotList.SURGE) == "东财飙升榜"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_hot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kan.hot'`(模块还没建)

- [ ] **Step 3: 写 `kan/hot.py`**

创建 `kan/hot.py`,完整内容:

```python
"""东方财富热榜数据子系统 · 人气榜 / 飙升榜拉取 + 缓存 + 代码归一化。

数据源:东方财富(akshare)单源。同花顺无人气热榜接口 —— 不建假 fallback,
东财失败直接抛 HotListUnavailableError(沿用 boards.py 单源原则)。
冷启动规则:akshare 一律函数内延迟 import。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum

from kan._log import debug_log
from kan.paths import HOT_DIR, ensure_dirs

_CACHE_TTL = 3600  # 1h · 热榜实时榜 · 盘后工具 1h 内重复跑结果稳定 · 不反复打源

_PREFIX_RE = re.compile(r"^[A-Za-z]{2}")
_CODE_RE = re.compile(r"\d{6}")


class HotList(str, Enum):
    """支持的东财热榜 · 同时作 typer 选项枚举(值 = CLI 输入)。"""

    RANK = "rank"     # 东财人气榜
    SURGE = "surge"   # 东财飙升榜


# 榜单元信息:akshare 函数名 + 展示名
_HOT_SPEC: dict[HotList, tuple[str, str]] = {
    HotList.RANK: ("stock_hot_rank_em", "东财人气榜"),
    HotList.SURGE: ("stock_hot_up_em", "东财飙升榜"),
}


@dataclass
class HotEntry:
    """热榜单条目。"""

    rank: int
    symbol: str   # 6 位裸代码
    name: str


class HotListUnavailableError(Exception):
    """东财热榜数据源不可用(网络 / 接口失败 / 空数据)。"""


def hot_list_name(which: HotList) -> str:
    """榜单展示名 · 如 '东财人气榜'。"""
    return _HOT_SPEC[which][1]


def _cache_fresh(path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def _normalize_code(raw: str) -> str | None:
    """东财代码(SZ000725 / SH603759)→ 6 位裸代码。无法归一化返回 None。"""
    cleaned = _PREFIX_RE.sub("", str(raw).strip())
    if _CODE_RE.fullmatch(cleaned):
        return cleaned
    return None


def fetch_hot_list(which: HotList, force: bool = False) -> list[HotEntry]:
    """拉取指定东财热榜 · (名次, 代码, 名称) 列表 · JSON cache 1h TTL。

    akshare: stock_hot_rank_em(人气榜) / stock_hot_up_em(飙升榜)。
    无法归一化的代码跳过 · 经 debug_log 记数。
    数据源失败 / 空 / 无有效条目 → 抛 HotListUnavailableError。
    """
    ensure_dirs()
    cache = HOT_DIR / f"hot_{which.value}.json"
    if not force and _cache_fresh(cache, _CACHE_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [HotEntry(**e) for e in data]
        except Exception:
            pass  # cache 损坏 → 重新拉

    fn_name, _label = _HOT_SPEC[which]
    import akshare as ak

    try:
        df = getattr(ak, fn_name)()
    except Exception as e:
        raise HotListUnavailableError(f"东财热榜拉取失败 {fn_name}: {e}") from e
    if df is None or df.empty:
        raise HotListUnavailableError(f"东财热榜为空: {fn_name}")

    entries: list[HotEntry] = []
    skipped = 0
    for _, row in df.iterrows():
        code = _normalize_code(row["代码"])
        if code is None:
            skipped += 1
            continue
        entries.append(HotEntry(
            rank=int(row["当前排名"]),
            symbol=code,
            name=str(row["股票名称"]).strip(),
        ))
    if skipped:
        debug_log(
            __name__,
            f"hot list {which.value} skipped {skipped} non-A-share codes",
            ValueError("codes outside 6-digit A-share range"),
        )
    if not entries:
        raise HotListUnavailableError(f"东财热榜无有效条目: {fn_name}")

    cache.write_text(
        json.dumps([asdict(e) for e in entries], ensure_ascii=False),
        encoding="utf-8",
    )
    return entries
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_hot.py -v`
Expected: PASS(8 个用例全过)

- [ ] **Step 5: ruff 检查**

Run: `.venv/bin/ruff check kan/hot.py tests/test_hot.py`
Expected: 无 lint 错误。若有,修复后重跑。

- [ ] **Step 6: Commit**

```bash
git add kan/hot.py tests/test_hot.py
git commit -m "feat(hot): add eastmoney hot-list data module"
```

---

## Task 3: `_scan_targets.py` 加 `HotMeta` + `hot` 分支

**Files:**
- Modify: `kan/_scan_targets.py`(整文件替换)

- [ ] **Step 1: 整文件替换 `kan/_scan_targets.py`**

把 `kan/_scan_targets.py` 全文替换为:

```python
"""扫描目标解析 · scan/low/high/trend/fetch 共享。

industry 给定 → 拉行业成分股;hot 给定 → 拉东财热榜;否则用自选股。
三种来源的差异收敛进 resolve_scan_targets 一个函数,各命令只需"换数据来源
+ 多收一个 meta"。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kan.models import Board

if TYPE_CHECKING:
    import pandas as pd

    from kan.hot import HotList


@dataclass
class BoardMeta:
    """resolve_scan_targets 在 industry 模式下的附加产物。"""

    board: Board
    index_kline: pd.DataFrame          # 板块指数 K(已归一化)
    constituents: list[tuple[str, str]]  # 全成分股 (代码, 名称)
    highlight: set[str]                  # 成分股代码 ∩ 自选股代码


@dataclass
class HotMeta:
    """resolve_scan_targets 在 hot 模式下的附加产物。"""

    list_name: str                # "东财人气榜" / "东财飙升榜"
    rank_map: dict[str, int]      # {代码: 热榜名次}
    highlight: set[str]           # 热榜代码 ∩ 自选股代码


def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    hot: HotList | None = None,
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | None]:
    """解析扫描目标。

    - industry / hot 都为 None → (watchlist_pairs, None) · 现有行为完全不变
    - industry 给定 → 拉成分股 + 板块指数 K,组 BoardMeta
    - hot 给定 → 拉东财热榜,组 HotMeta
        - only_watchlist=True → targets 取 (成分股 | 热榜) ∩ 自选
    - industry 与 hot 同时给定 → raise ValueError
    - 行业未找到 → 透传 boards.BoardNotFoundError
    - 行业数据源失败 → 透传 boards.BoardDataUnavailableError
    - 热榜数据源失败 → 透传 hot.HotListUnavailableError
    """
    if industry is not None and hot is not None:
        raise ValueError("industry 与 hot 不能同时指定")

    if industry is not None:
        from kan import boards

        board = boards.search_industry(industry)            # raises BoardNotFoundError
        constituents = boards.get_industry_constituents(board)
        index_kline = boards.fetch_industry_kline(board)
        watch_codes = {code for code, _ in watchlist_pairs}
        highlight = {code for code, _ in constituents} & watch_codes
        board_meta = BoardMeta(
            board=board,
            index_kline=index_kline,
            constituents=constituents,
            highlight=highlight,
        )
        targets = constituents
        if only_watchlist:
            targets = [(c, n) for c, n in constituents if c in highlight]
        return targets, board_meta

    if hot is not None:
        from kan import hot as hot_mod

        entries = hot_mod.fetch_hot_list(hot)               # raises HotListUnavailableError
        watch_codes = {code for code, _ in watchlist_pairs}
        highlight = {e.symbol for e in entries} & watch_codes
        hot_meta = HotMeta(
            list_name=hot_mod.hot_list_name(hot),
            rank_map={e.symbol: e.rank for e in entries},
            highlight=highlight,
        )
        targets = [(e.symbol, e.name) for e in entries]
        if only_watchlist:
            targets = [(c, n) for c, n in targets if c in highlight]
        return targets, hot_meta

    return watchlist_pairs, None
```

- [ ] **Step 2: 跑 industry 回归测试确认没破坏现有行为**

Run: `.venv/bin/python -m pytest tests/test_industry_cli.py tests/test_scan_targets.py -v`
Expected: PASS(`_info_industry` 的旧调用 `resolve_scan_targets(industry, only_watchlist=False, watchlist_pairs=[])` 因 `hot` 有默认值 `None` 仍兼容)

- [ ] **Step 3: ruff 检查**

Run: `.venv/bin/ruff check kan/_scan_targets.py`
Expected: 无错误。

- [ ] **Step 4: Commit**

```bash
git add kan/_scan_targets.py
git commit -m "feat(scan-targets): add hot branch + HotMeta to resolve_scan_targets"
```

---

## Task 4: `scan --hot` + 名次列 + CLI 测试

**Files:**
- Modify: `kan/cli_scan_cmds.py`(顶部加 import · 替换 `scan` 函数)
- Test: `tests/test_hot_cli.py`(新建)

> 注:设计文档 §9 原写"扩展 test_scan_cli.py",但 `--industry` 的先例是独立的
> `test_industry_cli.py`。为与先例对称,改用独立 `tests/test_hot_cli.py`(带共享
> `hot_runner` fixture),后续 Task 5/6/7 往此文件追加。

- [ ] **Step 1: 写失败测试 `tests/test_hot_cli.py`**

创建 `tests/test_hot_cli.py`,完整内容:

```python
"""scan/low/high/trend/fetch --hot 集成测试 · mock hot 层 · 不走真网络。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from typer.testing import CliRunner

from kan import hot
from kan.hot import HotEntry, HotListUnavailableError
from kan.models import PeriodResult, StockScanResult


def _fake_scan_result(symbol: str, name: str) -> StockScanResult:
    return StockScanResult(
        symbol=symbol, name=name, current_price=100.0,
        scan_date=date(2026, 5, 21),
        periods=[PeriodResult(
            period=3, n_low=90.0, n_high=110.0, position_pct=50.0,
            at_low=False, at_high=False,
        )],
        low_resonance=0, high_resonance=0,
    )


@pytest.fixture
def hot_runner(monkeypatch):
    """mock hot 层 + watchlist + fetch + scan_batch。"""
    entries = [
        HotEntry(rank=1, symbol="000725", name="京东方Ａ"),
        HotEntry(rank=2, symbol="600519", name="贵州茅台"),
    ]
    monkeypatch.setattr(hot, "fetch_hot_list", lambda which, force=False: entries)
    monkeypatch.setattr(
        "kan.cli_scan_cmds._get_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli_scan_cmds._auto_fetch_stale", lambda _p: None)
    monkeypatch.setattr(
        "kan.cli_scan_cmds._load_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.cli_trend_cmds._get_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr("kan.cli_trend_cmds._auto_fetch_stale", lambda _p: None)
    monkeypatch.setattr(
        "kan.cli_trend_cmds._load_watchlist_pairs", lambda: [("600519", "贵州茅台")]
    )
    monkeypatch.setattr(
        "kan.scanner.scan_batch",
        lambda pairs, mode="low": [_fake_scan_result(s, n) for s, n in pairs],
    )
    monkeypatch.setattr("kan.fetcher.cache_age", lambda _s: "2026-05-21 12:00")
    monkeypatch.setattr(
        "kan.fetcher.data_cutoff_date", lambda _s: date(2026, 5, 21)
    )
    monkeypatch.setattr(
        "kan.trading_calendar.latest_trade_date", lambda: date(2026, 5, 21)
    )
    monkeypatch.setattr("kan.trading_calendar.market_phase", lambda: "pre")
    return CliRunner()


def test_scan_hot_rank_runs(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(app, ["scan", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert "京东方" in result.output         # 热榜成员
    assert "东财人气榜" in result.output      # 标题
    assert "⭐" in result.output             # 茅台在自选 · 高亮


def test_scan_hot_conflicts_with_industry(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(
        app, ["scan", "--hot", "rank", "--industry=半导体"]
    )
    assert result.exit_code == 2
    assert "不能同时使用" in result.output


def test_scan_hot_data_unavailable(hot_runner, monkeypatch):
    from kan.app import app

    def _raise(which, force=False):
        raise HotListUnavailableError("network down")

    monkeypatch.setattr(hot, "fetch_hot_list", _raise)
    result = hot_runner.invoke(app, ["scan", "--hot", "rank"])
    assert result.exit_code == 1
    assert "热榜数据源暂时不可用" in result.output


def test_scan_hot_only_watchlist_intersects(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(
        app, ["scan", "--hot", "rank", "--only-watchlist"]
    )
    assert result.exit_code == 0, result.output
    assert "贵州茅台" in result.output       # 茅台在自选 ∩ 热榜
    assert "京东方" not in result.output     # 京东方不在自选


def test_only_watchlist_needs_source(hot_runner):
    from kan.app import app
    result = hot_runner.invoke(app, ["scan", "--only-watchlist"])
    assert result.exit_code == 1
    assert "--only-watchlist" in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py -v`
Expected: FAIL — `scan` 还不认识 `--hot` 选项(typer 报 "No such option: --hot",exit 2),`test_scan_hot_rank_runs` 等失败。

- [ ] **Step 3: `cli_scan_cmds.py` 顶部加 import**

找到 `kan/cli_scan_cmds.py` 顶部的 import 段:

```python
from kan import export
from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _safe_error_msg,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
```

在 `from kan.cli_helpers import (...)` 之后加一行:

```python
from kan import export
from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _safe_error_msg,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
from kan.hot import HotList
```

> `kan.hot` 顶层只 import 轻量 stdlib(akshare 在 `fetch_hot_list` 内 lazy),不影响冷启动。

- [ ] **Step 4: 整函数替换 `scan`**

把 `kan/cli_scan_cmds.py` 里的整个 `scan` 函数(从 `@app.command()` 到函数末尾 `console.print(DISCLAIMER, style="dim")`)替换为:

```python
@app.command()
def scan(
    high: Annotated[bool, typer.Option("--high", help="高点模式（默认低点模式）")] = False,
    signal: Annotated[bool, typer.Option("--signal", "-S", "-s", help="仅显示有共振信号的股票")] = False,
    diff: Annotated[bool, typer.Option("--diff", "-d", help="增量模式：显示与上次扫描的变化")] = False,
    exclude_st: Annotated[bool, typer.Option("--exclude-st", help="排除 ST/*ST 股票")] = False,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="扫指定申万行业全部成分股 · 自选股 ⭐ 高亮"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="扫东财热榜 · rank=人气榜 / surge=飙升榜 · 自选股 ⭐ 高亮"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜(需配合 --industry 或 --hot)"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """扫描自选股多周期位置（10 周期全景模式）"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age, data_cutoff_date
        from kan.render import DISCLAIMER, format_pct, responsive_periods
        from kan.scanner import (
            PERIODS,
            compute_diff,
            load_snapshot,
            save_snapshot,
            scan_batch,
        )
        from kan.trading_calendar import (
            PHASE_INTRADAY,
            latest_trade_date,
            market_phase,
        )

    console = Console()
    if industry is not None and hot is not None:
        _print_err("❌ --industry 与 --hot 不能同时使用")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None
    watchlist_pairs = (
        _load_watchlist_pairs() if source_mode else _get_watchlist_pairs()
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry 或 --hot 使用")
        raise typer.Exit(1)
    from kan._scan_targets import BoardMeta, HotMeta, resolve_scan_targets
    from kan.boards import BoardDataUnavailableError, BoardNotFoundError
    from kan.hot import HotListUnavailableError
    try:
        targets, board_meta = resolve_scan_targets(
            industry, only_watchlist, watchlist_pairs, hot=hot,
        )
    except BoardNotFoundError:
        _print_err(
            f"❌ 未找到行业「{industry}」· 可试更短关键词(如「半导体」「白酒」)"
        )
        raise typer.Exit(1) from None
    except BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except HotListUnavailableError:
        _print_err("❌ 热榜数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    _auto_fetch_stale(targets)
    mode = "high" if high else "low"

    prev_snapshot = load_snapshot() if (diff and board_meta is None) else None

    # P1-8: 单次 scan_batch · 后续 filter / diff / snapshot 都用 all_results · 避免重复调用
    all_results = scan_batch(targets, mode=mode)

    board_index_result = None
    if isinstance(board_meta, BoardMeta):
        from kan.scanner import scan_stock
        board_index_result = scan_stock(
            board_meta.index_kline, board_meta.board.code, board_meta.board.name,
        )

    if not all_results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    results = all_results
    if exclude_st:
        results = [r for r in results if not r.is_st]

    if signal:
        if mode == "high":
            results = [r for r in results if r.high_resonance > 0]
        else:
            results = [r for r in results if r.low_resonance > 0]
        if not results and fmt is export.OutputFormat.terminal:
            console.print("没有股票触及极值区 · 无共振信号")
            if board_meta is None:
                save_snapshot(all_results)
            return

    # v0.0.4.5: 数据截止日 (K 线 date 列) 与 拉取时间 (文件 mtime) 严格分离展示
    data_cutoff = None
    fetched_at = None
    for r in results:
        d = data_cutoff_date(r.symbol)
        if d is not None and (data_cutoff is None or d > data_cutoff):
            data_cutoff = d
        t = cache_age(r.symbol)
        if t and (fetched_at is None or t > fetched_at):
            fetched_at = t

    expected_cutoff = latest_trade_date()
    is_stale = data_cutoff is None or data_cutoff < expected_cutoff
    phase = market_phase()

    title = f"慢慢看 · 自选股位置扫描 · {'高点' if high else '低点'}模式"
    if signal:
        title += " · 仅信号"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    if isinstance(board_meta, BoardMeta):
        title = (
            f"慢慢看 · {board_meta.board.name} 行业位置扫描"
            f" · {'高点' if high else '低点'}模式"
        )
    elif isinstance(board_meta, HotMeta):
        title = (
            f"慢慢看 · {board_meta.list_name} 位置扫描"
            f" · {'高点' if high else '低点'}模式"
        )

    if fmt is export.OutputFormat.json:
        typer.echo(export.to_json(export.scan_payload(
            results, mode=mode, data_cutoff=data_cutoff,
            fetched_at=fetched_at, stale=is_stale,
        )))
        if board_meta is None:
            save_snapshot(all_results)
        return
    if fmt is export.OutputFormat.md:
        typer.echo(export.scan_markdown(
            results, periods=list(PERIODS), mode=mode, title=title,
        ))
        if board_meta is None:
            save_snapshot(all_results)
        return

    display_periods = responsive_periods(console.width)
    is_compact = len(display_periods) < len(PERIODS)

    is_hot = isinstance(board_meta, HotMeta)
    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white", min_width=8)
    for p in display_periods:
        table.add_column(f"{p}日", justify="right", min_width=6)
    table.add_column("共振", justify="center")

    highlight = board_meta.highlight if board_meta else set()
    if board_index_result is not None:
        brow: list[str | Text] = [f"🏛️ {board_index_result.name} 板块指数"]
        brow.append(f"{board_index_result.current_price:.2f}")
        for p in display_periods:
            pr = next(
                (x for x in board_index_result.periods if x.period == p), None
            )
            brow.append(Text("-", style="dim") if pr is None
                        else format_pct(pr, high_mode=high))
        brow.append("")
        table.add_row(*brow)
        table.add_section()

    for r in results:
        row: list[str | Text] = []
        if is_hot:
            rank = board_meta.rank_map.get(r.symbol)
            row.append(str(rank) if rank is not None else "-")
        name_short = r.name.replace(" ", "")
        tag = ""
        if r.limit_up:
            tag = " 涨停"
        elif r.limit_down:
            tag = " 跌停"
        star = "⭐ " if r.symbol in highlight else ""
        row.append(f"{star}{name_short} {r.symbol}{tag}")
        row.append(f"{r.current_price:.2f}")

        for p in display_periods:
            pr = next((x for x in r.periods if x.period == p), None)
            if pr is None:
                row.append(Text("-", style="dim"))
            else:
                row.append(format_pct(pr, high_mode=high))

        resonance = r.high_resonance if high else r.low_resonance
        if resonance >= 3:
            row.append(Text(f"×{resonance}", style="bold yellow"))
        elif resonance > 0:
            row.append(Text(f"×{resonance}", style="yellow"))
        else:
            row.append("")

        table.add_row(*row)

    console.print(table)

    if is_compact:
        shown = "/".join(str(p) for p in display_periods)
        n = len(display_periods)
        console.print(
            f"\n  [dim]窄屏模式 · 显示 {n}/10 周期"
            f"（{shown}日）· 加宽终端可见全部[/dim]"
        )

    # ***REMOVED***: 双警告互斥渲染 (if/elif 替代 if/if)
    if is_stale:
        cutoff_str = format_date_compact(data_cutoff) if data_cutoff else "无缓存"
        expected_str = format_date_compact(expected_cutoff)
        days_behind = (expected_cutoff - data_cutoff).days if data_cutoff else "?"
        console.print(
            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
            f"最近交易日是 {expected_str} · 数据滞后 {days_behind} 天\n"
            "   运行 `kan fetch --force` 拉取最新数据[/bold yellow]"
        )
    elif phase == PHASE_INTRADAY:
        console.print(
            "\n  [bold yellow]⚠️ 当前盘中 · 涨跌停标签反映当前时刻 · 非收盘 final\n"
            "   (盘中价格仍在变动 · 涨停/跌停状态可能与收盘不同)\n"
            "   建议盘后 15:30 后看 final 数据[/bold yellow]"
        )

    # 增量对比 · 仅自选模式 (board_meta is None) · industry/hot 模式不做 diff/snapshot
    if board_meta is None and diff and prev_snapshot:
        changes = compute_diff(all_results, prev_snapshot)
        if changes:
            console.print()
            console.print("[bold]与上次扫描的变化：[/bold]")
            for sym, name, _, desc in changes:
                name_short = name.replace(" ", "")
                console.print(f"  {name_short} {sym} · {desc}")
        else:
            if not is_stale:
                console.print("\n  [dim]与上次扫描无变化（同日数据，次日再对比可见变化）[/dim]")
            else:
                console.print("\n  与上次扫描无变化")
    elif diff and not prev_snapshot:
        console.print("\n  [dim]首次扫描，无历史对比（下次 --diff 将显示变化）[/dim]")

    # 保存快照供下次 diff 用 · 仅自选模式
    if board_meta is None:
        save_snapshot(all_results)

    console.print()
    if high:
        console.print("[dim]  \\[x%] = 触及高点(≥95%) · 100%=区间最高 · 越高=越接近 N 日最高价[/dim]")
    else:
        console.print("[dim]  \\[x%] = 触及低点(≤5%) · 0%=区间最低 · 越低=越接近 N 日最低价[/dim]")
    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单[/dim]"
        )
    console.print(DISCLAIMER, style="dim")
```

> 与原 `scan` 的差异:① 加 `hot` 参数 ② 加 `--industry`/`--hot` 互斥检查 ③ `source_mode` 统一 industry/hot ④ 6 处 `industry is None`(快照/diff 相关)改为 `board_meta is None` ⑤ 板块指数行 / 标题用 `isinstance` 分流 ⑥ 热榜模式加"榜"列 + 行首名次 ⑦ 热榜 caption。

- [ ] **Step 5: 跑 hot CLI 测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py -v`
Expected: PASS(5 个用例全过)

- [ ] **Step 6: 跑 scan/industry 回归测试**

Run: `.venv/bin/python -m pytest tests/test_scan_cli.py tests/test_industry_cli.py -v`
Expected: PASS(原有 scan / industry 行为不变)

- [ ] **Step 7: ruff 检查**

Run: `.venv/bin/ruff check kan/cli_scan_cmds.py tests/test_hot_cli.py`
Expected: 无错误。

- [ ] **Step 8: Commit**

```bash
git add kan/cli_scan_cmds.py tests/test_hot_cli.py
git commit -m "feat(scan): add --hot eastmoney hot-list scan with rank column"
```

---

## Task 5: `low` / `high --hot`

**Files:**
- Modify: `kan/cli_scan_cmds.py`(替换 `_filter_extreme_cmd` / `low` / `high` 三个函数)
- Test: `tests/test_hot_cli.py`(追加 2 个用例)

- [ ] **Step 1: 追加失败测试到 `tests/test_hot_cli.py`**

在 `tests/test_hot_cli.py` 末尾追加:

```python


def test_low_hot_runs(hot_runner, monkeypatch):
    from kan.app import app
    monkeypatch.setattr(
        "kan.scanner.filter_extreme",
        lambda pairs, periods, mode="low": {},
    )
    result = hot_runner.invoke(app, ["low", "30", "--hot", "surge"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "东财飙升榜" in result.output


def test_high_hot_runs(hot_runner, monkeypatch):
    from kan.app import app
    monkeypatch.setattr(
        "kan.scanner.filter_extreme",
        lambda pairs, periods, mode="low": {},
    )
    result = hot_runner.invoke(app, ["high", "30", "--hot", "rank"])
    assert result.exit_code == 0
    assert "Traceback" not in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py::test_low_hot_runs tests/test_hot_cli.py::test_high_hot_runs -v`
Expected: FAIL — `low` / `high` 还不认识 `--hot`(exit 2)。

- [ ] **Step 3: 整函数替换 `_filter_extreme_cmd`**

把 `kan/cli_scan_cmds.py` 里的整个 `_filter_extreme_cmd` 函数替换为:

```python
def _filter_extreme_cmd(
    periods: list[int], mode: str, fmt: export.OutputFormat,
    industry: str | None = None, only_watchlist: bool = False,
    hot: HotList | None = None,
) -> None:
    """low/high 共享实现"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age, data_cutoff_date
        from kan.render import DISCLAIMER
        from kan.scanner import filter_extreme

    console = Console()
    for p in periods:
        if p < 2 or p > 360:
            _print_err(f"❌ 周期 {p} 无效（范围 2-360）")
            raise typer.Exit(1)

    label = "低点" if mode == "low" else "高点"
    signal_style = "bold green" if mode == "low" else "bold yellow"

    if industry is not None and hot is not None:
        _print_err("❌ --industry 与 --hot 不能同时使用")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None
    watchlist_pairs = (
        _load_watchlist_pairs() if source_mode else _get_watchlist_pairs()
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry 或 --hot 使用")
        raise typer.Exit(1)
    from kan._scan_targets import BoardMeta, HotMeta, resolve_scan_targets
    from kan.boards import BoardDataUnavailableError, BoardNotFoundError
    from kan.hot import HotListUnavailableError
    try:
        targets, board_meta = resolve_scan_targets(
            industry, only_watchlist, watchlist_pairs, hot=hot,
        )
    except BoardNotFoundError:
        _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
        raise typer.Exit(1) from None
    except BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except HotListUnavailableError:
        _print_err("❌ 热榜数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    highlight = board_meta.highlight if board_meta else set()
    is_hot = isinstance(board_meta, HotMeta)
    rank_map = board_meta.rank_map if is_hot else {}
    _auto_fetch_stale(targets)
    results_by_period = filter_extreme(targets, periods, mode=mode)

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(
                export.extreme_payload(results_by_period, mode=mode)
            ))
        else:
            typer.echo(export.extreme_markdown(results_by_period, mode=mode))
        return

    if not results_by_period:
        if isinstance(board_meta, BoardMeta):
            where = f"{board_meta.board.name} 行业成分股"
        elif isinstance(board_meta, HotMeta):
            where = board_meta.list_name
        else:
            where = "自选股"
        console.print(f"{where}中没有触及 {'/'.join(map(str, periods))} 日{label}的股票")
        return

    # v0.0.4.5: 数据截止 / 拉取时间分离展示（与 scan 一致）
    data_cutoff = None
    fetched_at = None

    for n, hits in results_by_period.items():
        for r, _ in hits:
            d = data_cutoff_date(r.symbol)
            if d is not None and (data_cutoff is None or d > data_cutoff):
                data_cutoff = d
            t = cache_age(r.symbol)
            if t and (fetched_at is None or t > fetched_at):
                fetched_at = t

        title = f"慢慢看 · {n} 日{label} · {len(hits)} 只触及"
        if data_cutoff:
            title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
        if fetched_at:
            title += f" · {format_fetched_at_compact(fetched_at)} 拉取"

        table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
        if is_hot:
            table.add_column("榜", justify="right", style="cyan", min_width=3)
        table.add_column("股票", style="white", no_wrap=True)
        table.add_column("现价", justify="right", style="white", min_width=8)
        table.add_column(f"{n}日最低", justify="right", style="dim", min_width=8)
        table.add_column(f"{n}日最高", justify="right", style="dim", min_width=8)
        table.add_column("位置", justify="right", min_width=8)

        for result, pr in hits:
            name_short = result.name.replace(" ", "")
            star = "⭐ " if result.symbol in highlight else ""
            row: list[str | Text] = []
            if is_hot:
                rank = rank_map.get(result.symbol)
                row.append(str(rank) if rank is not None else "-")
            row.append(f"{star}{name_short} {result.symbol}")
            row.append(f"{result.current_price:.2f}")
            row.append(f"{pr.n_low:.2f}")
            row.append(f"{pr.n_high:.2f}")
            row.append(Text(f"[{pr.position_pct:.1f}%]", style=signal_style))
            table.add_row(*row)

        console.print(table)
        console.print()

    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单[/dim]"
        )
    console.print(DISCLAIMER, style="dim")
```

- [ ] **Step 4: 整函数替换 `low`**

把 `low` 函数替换为:

```python
@app.command()
def low(
    periods: Annotated[list[int], typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120）")],
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="扫指定申万行业全部成分股 · 自选股 ⭐ 高亮"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="扫东财热榜 · rank=人气榜 / surge=飙升榜 · 自选股 ⭐ 高亮"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜(需配合 --industry 或 --hot)"),
    ] = False,
) -> None:
    """筛选 N 日低点的自选股（支持多周期）"""
    _filter_extreme_cmd(
        periods, mode="low", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot,
    )
```

- [ ] **Step 5: 整函数替换 `high`**

把 `high` 函数替换为:

```python
@app.command()
def high(
    periods: Annotated[list[int], typer.Argument(help="周期天数（2-360 · 支持多个：30 60 120）")],
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="扫指定申万行业全部成分股 · 自选股 ⭐ 高亮"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="扫东财热榜 · rank=人气榜 / surge=飙升榜 · 自选股 ⭐ 高亮"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜(需配合 --industry 或 --hot)"),
    ] = False,
) -> None:
    """筛选 N 日高点的自选股（支持多周期）"""
    _filter_extreme_cmd(
        periods, mode="high", fmt=fmt,
        industry=industry, only_watchlist=only_watchlist, hot=hot,
    )
```

- [ ] **Step 6: 跑测试确认通过 + 回归**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py tests/test_industry_cli.py tests/test_scan_cli.py -v`
Expected: PASS(新增 low/high hot 用例过 · industry low/high 回归过)

- [ ] **Step 7: ruff 检查**

Run: `.venv/bin/ruff check kan/cli_scan_cmds.py tests/test_hot_cli.py`
Expected: 无错误。

- [ ] **Step 8: Commit**

```bash
git add kan/cli_scan_cmds.py tests/test_hot_cli.py
git commit -m "feat(low,high): add --hot eastmoney hot-list extreme scan"
```

---

## Task 6: `trend --hot`

**Files:**
- Modify: `kan/cli_trend_cmds.py`(顶部加 import · 替换 `trend` 函数)
- Test: `tests/test_hot_cli.py`(追加 1 个用例)

- [ ] **Step 1: 追加失败测试到 `tests/test_hot_cli.py`**

在 `tests/test_hot_cli.py` 末尾追加:

```python


def test_trend_hot_runs(hot_runner, monkeypatch):
    from kan.app import app

    class _Tr:
        def __init__(self, sym, name):
            self.symbol, self.name = sym, name
            self.current_price, self.streak, self.streak_pct = 100.0, 0, 0.0
            self.daily_changes = []
            self.direction = "平"

    monkeypatch.setattr(
        "kan.scanner.trend_batch",
        lambda pairs, candle=False: [_Tr(s, n) for s, n in pairs],
    )
    result = hot_runner.invoke(app, ["trend", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "东财人气榜" in result.output
    assert "⭐" in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py::test_trend_hot_runs -v`
Expected: FAIL — `trend` 还不认识 `--hot`(exit 2)。

- [ ] **Step 3: `cli_trend_cmds.py` 顶部加 import**

找到 `kan/cli_trend_cmds.py` 顶部:

```python
from kan import export
from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
```

在其后加一行:

```python
from kan import export
from kan.app import app
from kan.cli_helpers import (
    _auto_fetch_stale,
    _get_watchlist_pairs,
    _load_watchlist_pairs,
    _print_err,
    _with_heavy_imports_spinner,
    format_date_compact,
    format_fetched_at_compact,
)
from kan.hot import HotList
```

- [ ] **Step 4: 整函数替换 `trend`**

把 `kan/cli_trend_cmds.py` 里整个 `trend` 函数替换为:

```python
@app.command()
def trend(
    latest: Annotated[int | None, typer.Option("--latest", "-l", help="展示近 N 天走势详情（1-180）", min=1, max=180)] = None,
    down: Annotated[int | None, typer.Option("--down", help="只看连跌≥N天（不带 N 默认 3）")] = None,
    up: Annotated[int | None, typer.Option("--up", help="只看连涨≥N天（不带 N 默认 3）")] = None,
    candle: Annotated[bool, typer.Option("--candle", "-c", help="阳线阴线口径（默认收盘价口径）")] = False,
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="扫指定申万行业全部成分股 · 自选股 ⭐ 高亮"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="扫东财热榜 · rank=人气榜 / surge=飙升榜 · 自选股 ⭐ 高亮"),
    ] = None,
    only_watchlist: Annotated[
        bool,
        typer.Option("--only-watchlist", help="仅显示自选 ∩ 行业/热榜(需配合 --industry 或 --hot)"),
    ] = False,
    fmt: Annotated[
        export.OutputFormat,
        typer.Option("--format", help="输出格式：terminal（默认）/ md / json"),
    ] = export.OutputFormat.terminal,
) -> None:
    """连续涨跌看板"""
    from rich.console import Console

    status_console = Console(stderr=True)
    with _with_heavy_imports_spinner(status_console, "⏳ 加载数据模块..."):
        from rich.table import Table
        from rich.text import Text

        from kan.fetcher import cache_age, data_cutoff_date
        from kan.render import DISCLAIMER, max_trend_dates
        from kan.scanner import trend_batch
        from kan.trading_calendar import (
            PHASE_INTRADAY,
            latest_trade_date,
            market_phase,
        )

    console = Console()
    if industry is not None and hot is not None:
        _print_err("❌ --industry 与 --hot 不能同时使用")
        raise typer.Exit(2)
    source_mode = industry is not None or hot is not None
    watchlist_pairs = (
        _load_watchlist_pairs() if source_mode else _get_watchlist_pairs()
    )
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry 或 --hot 使用")
        raise typer.Exit(1)
    from kan._scan_targets import BoardMeta, HotMeta, resolve_scan_targets
    from kan.boards import BoardDataUnavailableError, BoardNotFoundError
    from kan.hot import HotListUnavailableError
    try:
        targets, board_meta = resolve_scan_targets(
            industry, only_watchlist, watchlist_pairs, hot=hot,
        )
    except BoardNotFoundError:
        _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词")
        raise typer.Exit(1) from None
    except BoardDataUnavailableError:
        _print_err("❌ 行业数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    except HotListUnavailableError:
        _print_err("❌ 热榜数据源暂时不可用,稍后再试")
        raise typer.Exit(1) from None
    _auto_fetch_stale(targets)
    if down is not None and up is not None:
        _print_err("❌ --down 和 --up 不能同时使用")
        raise typer.Exit(1)
    for name, val in [("--down", down), ("--up", up)]:
        if val is not None and not (2 <= val <= 30):
            _print_err(f"❌ {name} 的值必须在 2-30 之间（当前：{val}）")
            raise typer.Exit(1)

    results = trend_batch(targets, candle=candle)

    if not results:
        _print_err("无缓存数据 · 请先 `kan fetch` 拉取数据")
        raise typer.Exit(1)

    # 筛选连续涨/跌
    filter_label = ""
    if down is not None:
        results = [r for r in results if r.streak <= -down]
        filter_label = f" · 连跌≥{down}天"
        if not results and fmt is export.OutputFormat.terminal:
            console.print(f"没有连续跌 {down} 天以上的股票")
            return
    elif up is not None:
        results = [r for r in results if r.streak >= up]
        filter_label = f" · 连涨≥{up}天"
        if not results and fmt is export.OutputFormat.terminal:
            console.print(f"没有连续涨 {up} 天以上的股票")
            return

    # v0.0.4.5: 数据截止 / 拉取时间分离展示
    data_cutoff = None
    fetched_at = None
    for r in results:
        d = data_cutoff_date(r.symbol)
        if d is not None and (data_cutoff is None or d > data_cutoff):
            data_cutoff = d
        t = cache_age(r.symbol)
        if t and (fetched_at is None or t > fetched_at):
            fetched_at = t

    expected_cutoff = latest_trade_date()
    is_stale = data_cutoff is None or data_cutoff < expected_cutoff
    phase = market_phase()

    mode_label = "阳线阴线口径" if candle else "收盘价口径"
    title = f"慢慢看 · 连续涨跌看板 · {mode_label}{filter_label}"
    if data_cutoff:
        title += f" · 数据截止 {format_date_compact(data_cutoff)} 收盘"
    if fetched_at:
        title += f" · {format_fetched_at_compact(fetched_at)} 拉取"
    if isinstance(board_meta, BoardMeta):
        title = f"慢慢看 · {board_meta.board.name} 行业连续涨跌 · {mode_label}{filter_label}"
    elif isinstance(board_meta, HotMeta):
        title = f"慢慢看 · {board_meta.list_name} 连续涨跌 · {mode_label}{filter_label}"

    if fmt is not export.OutputFormat.terminal:
        if fmt is export.OutputFormat.json:
            typer.echo(export.to_json(export.trend_payload(
                results, candle=candle, data_cutoff=data_cutoff,
                fetched_at=fetched_at, stale=is_stale,
            )))
        else:
            typer.echo(export.trend_markdown(results, title=title, latest=latest))
        return

    is_hot = isinstance(board_meta, HotMeta)
    rank_map = board_meta.rank_map if is_hot else {}
    base_cols = 5 if is_hot else 4

    table = Table(title=title, show_lines=False, pad_edge=False, padding=(0, 1))
    if is_hot:
        table.add_column("榜", justify="right", style="cyan", min_width=3)
    table.add_column("股票", style="white", no_wrap=True)
    table.add_column("现价", justify="right", style="white")
    table.add_column("连续", justify="center")
    table.add_column("累计", justify="right")

    # 有 --latest 时加日期列头（新→旧，最近日期在左）
    date_headers: list[str] = []
    if latest and results:
        max_dates = max_trend_dates(console.width)
        actual_latest = min(latest, max_dates)
        ref = results[0]
        days = ref.daily_changes[:actual_latest]
        for date_str, _ in days:
            short = date_str[-5:]  # MM-DD
            date_headers.append(short)
            table.add_column(short, justify="right", min_width=7)

    highlight = board_meta.highlight if board_meta else set()
    for r in results:
        name_short = r.name.replace(" ", "")

        if r.streak < 0:
            streak_text = Text(r.direction, style="bold green")
            cum_text = Text(f"{abs(r.streak_pct):.2f}%", style="green")
        elif r.streak > 0:
            streak_text = Text(r.direction, style="bold red")
            cum_text = Text(f"{abs(r.streak_pct):.2f}%", style="red")
        else:
            streak_text = Text("平", style="dim")
            cum_text = Text("0%", style="dim")

        star = "⭐ " if r.symbol in highlight else ""
        row: list[str | Text] = []
        if is_hot:
            rank = rank_map.get(r.symbol)
            row.append(str(rank) if rank is not None else "-")
        row += [
            f"{star}{name_short} {r.symbol}",
            f"{r.current_price:.2f}",
            streak_text,
            cum_text,
        ]

        if latest:
            from kan.scanner import get_limit_threshold
            limit = get_limit_threshold(r.symbol, r.name)

            days_data = r.daily_changes[:actual_latest]  # 新→旧 · 按终端宽度截取
            for _, chg in days_data:
                abs_chg = abs(chg)
                if chg > 0 and abs_chg >= limit - 0.1:
                    row.append(Text("涨停", style="bold red"))
                elif chg < 0 and abs_chg >= limit - 0.1:
                    row.append(Text("跌停", style="bold green"))
                elif chg > 0:
                    row.append(Text(f"▲{abs_chg:.2f}%", style="red"))
                elif chg < 0:
                    row.append(Text(f"▼{abs_chg:.2f}%", style="green"))
                else:
                    row.append(Text("—", style="dim"))
            # 补齐列数（某些股票交易日可能少）· base_cols 含热榜名次列
            while len(row) < base_cols + len(date_headers):
                row.append(Text("-", style="dim"))

        table.add_row(*row)

    console.print(table)

    if latest and actual_latest < latest:
        console.print(
            f"\n  [dim]窄屏模式 · 显示近 {actual_latest}/{latest} 天"
            " · 加宽终端可见全部[/dim]"
        )

    # ***REMOVED***: 双警告互斥渲染 (if/elif 替代 if/if · 与 scan 一致)
    if is_stale:
        cutoff_str = format_date_compact(data_cutoff) if data_cutoff else "无缓存"
        expected_str = format_date_compact(expected_cutoff)
        days_behind = (expected_cutoff - data_cutoff).days if data_cutoff else "?"
        console.print(
            f"\n  [bold yellow]⚠️ 当前缓存到 {cutoff_str} 收盘 · "
            f"最近交易日是 {expected_str} · 数据滞后 {days_behind} 天\n"
            "   运行 `kan fetch --force` 拉取最新数据[/bold yellow]"
        )
    elif phase == PHASE_INTRADAY:
        console.print(
            "\n  [bold yellow]⚠️ 当前盘中 · 涨跌停标签反映当前时刻 · 非收盘 final\n"
            "   (盘中价格仍在变动 · 涨停/跌停状态可能与收盘不同)\n"
            "   建议盘后 15:30 后看 final 数据[/bold yellow]"
        )

    console.print()
    if candle:
        console.print("[dim]  阳线阴线口径：收盘 > 开盘 = ▲ · 收盘 < 开盘 = ▼ · 平盘不断连续[/dim]")
    else:
        console.print("[dim]  收盘价口径：今日收盘 > 昨日收盘 = ▲ · 今日收盘 < 昨日收盘 = ▼ · 平盘不断连续[/dim]")
    if is_hot:
        console.print(
            "[dim]  榜 = 东方财富热榜实时名次 · 非慢慢看观点 · 热榜为实时榜单[/dim]"
        )
    console.print(DISCLAIMER, style="dim")
```

> 与原 `trend` 的差异:① 加 `hot` 参数 ② 互斥检查 + `source_mode` ③ `resolve_scan_targets(..., hot=hot)` + `except HotListUnavailableError` ④ 标题用 `isinstance` 分流 ⑤ 热榜模式加"榜"列 + 行首名次 ⑥ `--latest` 补列数的常量 `4` 改为 `base_cols`(热榜模式 = 5)⑦ 热榜 caption。

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py tests/test_trend_cli.py tests/test_industry_cli.py -v`
Expected: PASS(trend hot 用例过 · trend / industry 回归过)

- [ ] **Step 6: ruff 检查**

Run: `.venv/bin/ruff check kan/cli_trend_cmds.py tests/test_hot_cli.py`
Expected: 无错误。

- [ ] **Step 7: Commit**

```bash
git add kan/cli_trend_cmds.py tests/test_hot_cli.py
git commit -m "feat(trend): add --hot eastmoney hot-list streak scan"
```

---

## Task 7: `fetch --hot`

**Files:**
- Modify: `kan/cli_scan_cmds.py`(`fetch` 函数:加 `hot` 参数 + 改 industry 分支)
- Test: `tests/test_hot_cli.py`(追加 1 个用例)

- [ ] **Step 1: 追加失败测试到 `tests/test_hot_cli.py`**

在 `tests/test_hot_cli.py` 末尾追加:

```python


def test_fetch_hot_runs(hot_runner, monkeypatch):
    from kan.app import app
    fetched: list[str] = []
    monkeypatch.setattr(
        "kan.fetcher.fetch_kline",
        lambda sym, force=False: fetched.append(sym) or pd.DataFrame(),
    )
    monkeypatch.setattr("kan.fetcher.is_fresh", lambda sym: False)
    result = hot_runner.invoke(app, ["fetch", "--hot", "rank"])
    assert result.exit_code == 0, result.output
    assert "000725" in fetched and "600519" in fetched
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py::test_fetch_hot_runs -v`
Expected: FAIL — `fetch` 还不认识 `--hot`(exit 2)。

- [ ] **Step 3: `fetch` 加 `hot` 参数**

在 `kan/cli_scan_cmds.py` 的 `fetch` 函数签名里,找到:

```python
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="预拉某申万行业全部成分股 + 板块指数"),
    ] = None,
    only_watchlist: Annotated[
```

替换为(在 `industry` 与 `only_watchlist` 之间插入 `hot`):

```python
    industry: Annotated[
        str | None,
        typer.Option("--industry", help="预拉某申万行业全部成分股 + 板块指数"),
    ] = None,
    hot: Annotated[
        HotList | None,
        typer.Option("--hot", help="预拉东财热榜全部股票 · rank=人气榜 / surge=飙升榜"),
    ] = None,
    only_watchlist: Annotated[
```

- [ ] **Step 4: 改 `fetch` 的 industry 分支支持 hot**

在 `fetch` 函数体里,找到:

```python
    if industry is not None:
        if symbols:
            typer.echo("--industry 与股票代码不能同时使用", err=True)
            raise typer.Exit(2)
        from kan._scan_targets import resolve_scan_targets
        from kan.boards import BoardDataUnavailableError, BoardNotFoundError
        wl_pairs = []
        if only_watchlist:
            from kan.watchlist import load_watchlist
            wl_pairs = [(s.symbol, s.name) for s in load_watchlist().stocks]
        try:
            targets, _meta = resolve_scan_targets(industry, only_watchlist, wl_pairs)
        except BoardNotFoundError:
            typer.echo(f"未找到行业「{industry}」· 可试更短关键词", err=True)
            raise typer.Exit(1) from None
        except BoardDataUnavailableError:
            typer.echo("行业数据源暂时不可用,稍后再试", err=True)
            raise typer.Exit(1) from None
        symbols = [s for s, _ in targets]
```

整块替换为:

```python
    if industry is not None and hot is not None:
        typer.echo("--industry 与 --hot 不能同时使用", err=True)
        raise typer.Exit(2)
    if industry is not None or hot is not None:
        if symbols:
            typer.echo("--industry / --hot 与股票代码不能同时使用", err=True)
            raise typer.Exit(2)
        from kan._scan_targets import resolve_scan_targets
        from kan.boards import BoardDataUnavailableError, BoardNotFoundError
        from kan.hot import HotListUnavailableError
        wl_pairs = []
        if only_watchlist:
            from kan.watchlist import load_watchlist
            wl_pairs = [(s.symbol, s.name) for s in load_watchlist().stocks]
        try:
            targets, _meta = resolve_scan_targets(
                industry, only_watchlist, wl_pairs, hot=hot,
            )
        except BoardNotFoundError:
            typer.echo(f"未找到行业「{industry}」· 可试更短关键词", err=True)
            raise typer.Exit(1) from None
        except BoardDataUnavailableError:
            typer.echo("行业数据源暂时不可用,稍后再试", err=True)
            raise typer.Exit(1) from None
        except HotListUnavailableError:
            typer.echo("热榜数据源暂时不可用,稍后再试", err=True)
            raise typer.Exit(1) from None
        symbols = [s for s, _ in targets]
```

> `from kan.hot import HotList` 已在 Task 4 Step 3 加到 `cli_scan_cmds.py` 顶部,此处不重复。

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `.venv/bin/python -m pytest tests/test_hot_cli.py tests/test_industry_cli.py -v`
Expected: PASS(fetch hot 用例过 · `test_fetch_industry_runs` 回归过)

- [ ] **Step 6: ruff 检查**

Run: `.venv/bin/ruff check kan/cli_scan_cmds.py tests/test_hot_cli.py`
Expected: 无错误。

- [ ] **Step 7: Commit**

```bash
git add kan/cli_scan_cmds.py tests/test_hot_cli.py
git commit -m "feat(fetch): add --hot eastmoney hot-list prefetch"
```

---

## Task 8: CHANGELOG + 全量回归 + 文档收尾

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/design-hot-list.md`(状态行)

- [ ] **Step 1: 跑全量测试套件**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 全部通过,0 regression。新增 17 个用例(test_hot.py 8 + test_hot_cli.py 9)。若有失败,定位修复后重跑,不得跳过。

- [ ] **Step 2: 全量 ruff 检查**

Run: `.venv/bin/ruff check kan tests`
Expected: 无错误。

- [ ] **Step 3: 真实冒烟测试(可选 · 需联网)**

只打东财热榜端点、不拉 K 线,验证真实数据归一化正常:

Run: `.venv/bin/python -c "from kan.hot import fetch_hot_list, HotList; e = fetch_hot_list(HotList.RANK, force=True); print(len(e), e[0])"`
Expected: 打印类似 `100 HotEntry(rank=1, symbol='000725', name='...')`。若东财端点当时被限流,会抛 `HotListUnavailableError` —— 说明降级路径生效,换个时间重试即可,不算实现失败。

- [ ] **Step 4: 更新 CHANGELOG.md**

打开 `CHANGELOG.md`。若顶部已存在 `## [0.0.5.0]` 区块,在其 `### Added` 下追加;若不存在,在 `## [0.0.4.8]` 之上新建区块。要追加的内容:

```markdown
## [0.0.5.0] - 2026-05-23

### Added

- `--hot rank|surge` 东方财富热榜扫描 · 人气榜 / 飙升榜作"临时自选股"标的来源 · 加到 scan/low/high/trend/fetch
- `kan/hot.py` 东财热榜数据子系统 · JSON cache 1h TTL · 代码归一化 · 单源不建假 fallback
- 热榜模式表格新增"榜"列(实时名次)· `--only-watchlist` 支持自选 ∩ 热榜
```

> 若 `## [0.0.5.0]` 已被 `--industry` 那批改动建好,只把上面 3 条 `Added` bullet 并进现有 `### Added`,不要重复建区块标题。

- [ ] **Step 5: 更新设计文档状态行**

打开 `docs/design-hot-list.md`,找到第一行引用块:

```markdown
> 状态:设计待实施 · 目标版本 v0.0.5.0 · 分支 `feat/v0.0.5.0`
```

改为:

```markdown
> 状态:已实施(v0.0.5.0)· 分支 `feat/v0.0.5.0`
```

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md docs/design-hot-list.md
git commit -m "docs: changelog + design status for hot-list feature"
```

---

## 实施完成后

全部 8 个 Task 完成后,功能即可用:

```
kan scan --hot rank          # 扫东财人气榜
kan scan --hot surge         # 扫东财飙升榜
kan low 30 60 --hot rank     # 人气榜里筛 30/60 日低点
kan trend --hot rank --up    # 人气榜里看连涨
kan scan --hot rank --only-watchlist   # 我的自选股里今天上人气榜的
```

合规 / 发版相关收尾(不在本 plan 范围,交回合伙人决策):

- 是否把热榜功能补进 `docs/roadmap.md`(维护者定)。
- v0.0.5.0 发版前的 7 角色 `***REMOVED***`。
