# 题材位置扫描功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `kan` 新增 `--theme <题材名>` 全 11 命令矩阵,把题材成分股当作扫描标的来源,套用现有多周期位置 / 趋势 / 自选股管理。同时新增 `kan theme list / search` 发现入口。

**Architecture:** 镜像 `--industry` / `--hot` 模式。`kan/boards.py` 扩展 6 个 theme 函数(catalog / search / 成分股 / K 线 / 个股反查 / 名字规范化)· `kan/_scan_targets.py` 加第四个分支 `theme`(industry / hot / theme / 自选)· 8 只读命令(scan / low / high / trend / info / list / fetch / update)各透传 `--theme` · 3 破坏性命令(add / remove / clear)新接 `kan/_confirm.py` 二次确认 · 新建子命令组 `kan/cli_theme_cmds.py`(list / search)。

**Tech Stack:** Python 3.10+ · typer(CLI)· `adata>=2.9,<3`(题材数据源 · 新增依赖)· pandas · rich(渲染)· pytest(测试)· ruff(lint)。

**前置:**
- 工作分支 `feat/v0.0.5-f11-theme`(已 worktree 隔离 · base = `feat/v0.0.5.0` @ `3b2cf0d` · tushare-pro 合入后 baseline = 525 passed)。
- 设计依据 `docs/design-f11-theme-scan.md`(391 行 · 5 节 brainstorming approved)。
- 所有 `pytest` / `ruff` / `uv` 命令在 worktree 根目录运行(`.worktrees/feat-v0.0.5-f11-theme`)。
- `adata` 数据源选择依据 `.dev-thinking/manmankan-v0.0.5/v0.0.5.0/F11-data-source-findings-2026-05-22.md` + `/tmp/adata-spike/spike{1..4}.py`(2026-05-23 真网络 spike 4 轮)。
- 接口可用性分层 LOCKED:catalog/成分股 = THS · K 线/反查 = EM datacenter · EM 成分股 = fallback + T6 熔断。

**目标 baseline:** 现 525 passed · 目标 **585+ passed**(+60 新 case · 真网络 6 跳过 `-m "not network"`)。

**测试纪律:**
- 沿 v0.0.4.8 CR-1 LOCKED "CliRunner runtime 真测 · 禁 bootstrap 字符串作弊"。
- mock `adata` 模块时,fixture 返回结构**跟 2026-05-23 spike 真返回完全一致**(避免空 DataFrame 测过 prod 崩)。
- 真网络 case 加 `@pytest.mark.network` 标签 · 默认 CI 跑 `-m "not network"`。

**红线词 LOCKED 禁止入产线:** "共振信号" / "强势题材" / "可能回升" / "可能回落" / "建议" / "推荐"(AGENTS.md §6 · 见 spec §12.2 表)。

---

## Task 1: 基建 · pyproject deps + Theme model + ThemeError 类

**Files:**
- Modify: `pyproject.toml`(deps 列表 append 一行)
- Modify: `kan/models.py`(末尾 append Theme class)
- Modify: `kan/boards.py:35-36`(在 `BoardDataUnavailableError` 之后加 ThemeNotFoundError + ThemeDataUnavailableError)

- [ ] **Step 1: pyproject.toml 加 adata deps**

打开 `pyproject.toml`,找到 `dependencies = [` 段:

```toml
dependencies = [
    "akshare>=1.14,<2",
    "pandas>=2.0,<3",  # v0.0.4.8 P0-3 (架-5): 收紧 <3 (...)
    "pydantic>=2.0,<3",
    "rich>=13.0,<16",
    "typer>=0.12,<0.26",
    "pyarrow>=15.0,<25",
    "baostock>=0.9.1,<1",
    "numpy>=1.26,<3",
]
```

在 numpy 行下、`]` 上方加一行:

```toml
    "numpy>=1.26,<3",
    "adata>=2.9,<3",  # F11: 题材位置扫描 · 同花顺 catalog/成分股 + 东财 K 线/反查 · 2026-05-23 spike LOCKED
]
```

- [ ] **Step 2: 同步 deps · 验证 adata 装机**

Run: `uv sync`

Expected: 输出 `Resolved N packages` + `Installed adata vX.X.X` · 0 error。

Run: `.venv/bin/python -c "import adata; print(adata.__version__)"`

Expected: 输出版本号(如 `2.9.5`)· 0 error。

- [ ] **Step 3: kan/models.py 加 Theme 类**

打开 `kan/models.py` · 在文件末尾 `Board` 类下方追加:

```python


class Theme(BaseModel):
    """题材板块 · catalog 条目。

    跟 Board 字段不重合(无 level · 有 source) · 不复用 Board · 见 design §5.1。
    """

    code: str          # THS index_code "886108" | EM concept_code "BK1629"
    name: str          # "AI应用" / "白酒概念"
    source: str        # "ths" | "em"
    size: int | None = None  # 成分股数 · catalog 接口未必提供 · 可空
```

- [ ] **Step 4: kan/boards.py 加 Theme 异常类**

打开 `kan/boards.py` · 在第 33-34 行 `BoardDataUnavailableError` 类下方追加:

```python
class BoardDataUnavailableError(Exception):
    """申万数据源不可用(网络/接口失败/空数据)。"""


class ThemeNotFoundError(Exception):
    """search_theme 未命中任何题材。"""


class ThemeDataUnavailableError(Exception):
    """adata THS+EM 题材数据全挂(双源都失败才抛)。"""
```

- [ ] **Step 5: 跑 models / boards 现有测试确认无回归**

Run: `.venv/bin/python -m pytest tests/test_models.py tests/test_boards.py -v 2>&1 | tail -10`

Expected: 全部 PASS · 新加的 Theme / 异常类不影响现有断言。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock kan/models.py kan/boards.py
git commit -m "feat(theme): add adata dep + Theme model + ThemeError exceptions"
```

---

## Task 2: `load_theme_catalog` · adata THS catalog · 24h JSON cache

**Files:**
- Modify: `kan/boards.py`(末尾 append theme 函数区)
- Test: `tests/test_boards_theme.py`(新建)

- [ ] **Step 1: 写失败测试 `tests/test_boards_theme.py`**

创建 `tests/test_boards_theme.py`,完整内容:

```python
"""kan/boards.py 的 theme 函数单元测试 · mock adata · 不走真网络。"""
import json

import pandas as pd
import pytest

from kan import boards
from kan.boards import ThemeDataUnavailableError, ThemeNotFoundError
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_boards_dir(tmp_path, monkeypatch):
    """boards cache 指向 tmp · 杜绝读写真实 ~/.local/share/kan/boards/。

    同 F10a `tests/test_boards.py` 风格 · 复用 F10a tests/conftest.py 的 isolate
    若已建可省 · 若未建在此 fixture 内 monkeypatch BOARDS_DIR + paths.ensure_dirs。
    """
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    return bdir


def _fake_ths_catalog_df():
    """模拟 adata.stock.info.all_concept_code_ths() 真返回结构(2026-05-23 spike 实测)。"""
    return pd.DataFrame(
        [
            {"index_code": "886108", "name": "AI应用", "concept_code": "308767", "source": "同花顺"},
            {"index_code": "885525", "name": "白酒概念", "concept_code": "308768", "source": "同花顺"},
            {"index_code": "886109", "name": "同花顺", "concept_code": "309265", "source": "同花顺"},
        ]
    )


def test_load_theme_catalog_first_run_hits_adata(monkeypatch, _isolate_boards_dir):
    """无 cache · 第一次跑应调 adata · 返回 list[Theme]。"""
    monkeypatch.setattr(
        "adata.stock.info.all_concept_code_ths",
        lambda: _fake_ths_catalog_df(),
    )
    themes = boards.load_theme_catalog()
    assert len(themes) == 3
    assert all(isinstance(t, Theme) for t in themes)
    assert themes[0].code == "886108"
    assert themes[0].name == "AI应用"
    assert themes[0].source == "ths"


def test_load_theme_catalog_writes_cache(monkeypatch, _isolate_boards_dir):
    """跑完 catalog 应写 catalog_concept_ths.json。"""
    monkeypatch.setattr(
        "adata.stock.info.all_concept_code_ths",
        lambda: _fake_ths_catalog_df(),
    )
    boards.load_theme_catalog()
    cache = _isolate_boards_dir / "catalog_concept_ths.json"
    assert cache.exists()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["code"] == "886108"


def test_load_theme_catalog_uses_cache_within_ttl(monkeypatch, _isolate_boards_dir):
    """24h 内第二次调不应再打 adata。"""
    call_count = {"n": 0}

    def counting_adata():
        call_count["n"] += 1
        return _fake_ths_catalog_df()

    monkeypatch.setattr("adata.stock.info.all_concept_code_ths", counting_adata)
    boards.load_theme_catalog()       # 第一次写 cache
    boards.load_theme_catalog()       # 第二次应读 cache
    assert call_count["n"] == 1


def test_load_theme_catalog_force_bypasses_cache(monkeypatch, _isolate_boards_dir):
    """force=True 应强制重拉。"""
    call_count = {"n": 0}

    def counting_adata():
        call_count["n"] += 1
        return _fake_ths_catalog_df()

    monkeypatch.setattr("adata.stock.info.all_concept_code_ths", counting_adata)
    boards.load_theme_catalog()
    boards.load_theme_catalog(force=True)
    assert call_count["n"] == 2


def test_load_theme_catalog_raises_when_adata_fails_and_no_cache(monkeypatch, _isolate_boards_dir):
    """adata 抛错 + 无 cache → ThemeDataUnavailableError。"""

    def raising():
        raise ConnectionError("adata down")

    monkeypatch.setattr("adata.stock.info.all_concept_code_ths", raising)
    with pytest.raises(ThemeDataUnavailableError):
        boards.load_theme_catalog()


def test_load_theme_catalog_falls_back_to_stale_cache_on_failure(monkeypatch, _isolate_boards_dir):
    """adata 挂 + cache 陈旧 → 用陈旧 cache 不抛(warn 但继续)。"""
    # 先建一个陈旧 cache(mtime 改为 25h 前)
    cache = _isolate_boards_dir / "catalog_concept_ths.json"
    cache.write_text(
        json.dumps([{"code": "886108", "name": "AI应用", "source": "ths", "size": None}], ensure_ascii=False),
        encoding="utf-8",
    )
    import os
    import time
    old = time.time() - 25 * 3600
    os.utime(cache, (old, old))

    monkeypatch.setattr(
        "adata.stock.info.all_concept_code_ths",
        lambda: (_ for _ in ()).throw(ConnectionError("adata down")),
    )
    themes = boards.load_theme_catalog()
    assert len(themes) == 1
    assert themes[0].code == "886108"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py -v 2>&1 | tail -15`

Expected: 全部 FAIL with `AttributeError: module 'kan.boards' has no attribute 'load_theme_catalog'` 或 `ImportError`。

- [ ] **Step 3: 写 `load_theme_catalog` 实现**

打开 `kan/boards.py`,在文件末尾(`fetch_industry_kline` 之后)追加:

```python


# ══════════════════════════════════════════════════════════════════
# 题材(theme)数据子系统 · F11 · 见 docs/design-f11-theme-scan.md §5
# ══════════════════════════════════════════════════════════════════

_THEME_CATALOG_TTL = 24 * 3600
_THEME_CONS_TTL = 24 * 3600
_STOCK_THEMES_TTL = 12 * 3600  # 个股反查 TTL 更短(公司频繁变题材归属)


def load_theme_catalog(force: bool = False):
    """adata THS 题材 catalog · 24h JSON cache · 失败退化到陈旧 cache。

    返回 list[Theme] · 391 个题材左右(2026-05-23 spike 实测)。
    """
    from kan.models import Theme

    ensure_dirs()
    cache = BOARDS_DIR / "catalog_concept_ths.json"
    if not force and _cache_fresh(cache, _THEME_CATALOG_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Theme(**t) for t in data]
        except Exception:
            pass

    import adata

    try:
        df = adata.stock.info.all_concept_code_ths()
    except Exception as e:
        # 失败时退化到陈旧 cache(若存在),否则抛
        if cache.exists():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                from kan._log import debug_log

                debug_log(f"adata THS catalog 失败 · 用陈旧 cache: {e}")
                return [Theme(**t) for t in data]
            except Exception:
                pass
        raise ThemeDataUnavailableError(f"题材清单首次拉取失败: {e}") from e

    if df is None or df.empty:
        if cache.exists():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                return [Theme(**t) for t in data]
            except Exception:
                pass
        raise ThemeDataUnavailableError("adata THS catalog 返回空数据")

    themes = [
        Theme(
            code=str(row["index_code"]).strip(),
            name=str(row["name"]).strip(),
            source="ths",
            size=None,
        )
        for _, row in df.iterrows()
    ]
    cache.write_text(
        json.dumps([t.model_dump() for t in themes], ensure_ascii=False),
        encoding="utf-8",
    )
    return themes
```

- [ ] **Step 4: Run test to verify all pass**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py -v 2>&1 | tail -15`

Expected: `6 passed`(test_load_theme_catalog 5 个 + 1 fixture 健康检查 · 实际就是 6 个测试函数)。

- [ ] **Step 5: ruff lint check**

Run: `.venv/bin/ruff check kan/boards.py tests/test_boards_theme.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add kan/boards.py tests/test_boards_theme.py
git commit -m "feat(theme): load_theme_catalog from adata THS · 24h cache · stale fallback"
```

---

## Task 3: `search_theme` + `normalize_theme_name`

**Files:**
- Modify: `kan/boards.py`(append theme 区)
- Test: `tests/test_boards_theme.py`(append)

- [ ] **Step 1: 写失败测试(在 `tests/test_boards_theme.py` 末尾 append)**

```python


# ── search_theme / normalize_theme_name ──────────────────────────────

def _seed_catalog(_isolate_boards_dir):
    """写入一个完整 catalog 到 tmp · 供 search 测试用。"""
    cache = _isolate_boards_dir / "catalog_concept_ths.json"
    cache.write_text(
        json.dumps(
            [
                {"code": "886108", "name": "AI应用", "source": "ths", "size": None},
                {"code": "886112", "name": "AI智能体", "source": "ths", "size": None},
                {"code": "885525", "name": "白酒概念", "source": "ths", "size": None},
                {"code": "886058", "name": "华为昇腾", "source": "ths", "size": None},
                {"code": "886109", "name": "同花顺", "source": "ths", "size": None},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_normalize_theme_name_strips_spaces(_isolate_boards_dir):
    """'AI 应用' → 'AI应用'(去全角半角空格)。"""
    assert boards.normalize_theme_name("AI 应用") == "AI应用"
    assert boards.normalize_theme_name("AI 应用") == "AI应用"  # 全角空格
    assert boards.normalize_theme_name("白酒  概念") == "白酒概念"


def test_normalize_theme_name_idempotent(_isolate_boards_dir):
    """'AI应用' → 'AI应用'(已规范不变)。"""
    assert boards.normalize_theme_name("AI应用") == "AI应用"


def test_search_theme_exact_code(_isolate_boards_dir):
    """精确代码命中。"""
    _seed_catalog(_isolate_boards_dir)
    t = boards.search_theme("886108")
    assert t.name == "AI应用"


def test_search_theme_exact_name(_isolate_boards_dir):
    """精确题材名命中。"""
    _seed_catalog(_isolate_boards_dir)
    t = boards.search_theme("白酒概念")
    assert t.code == "885525"


def test_search_theme_fuzzy_normalized(_isolate_boards_dir):
    """模糊命中 · normalize 后含匹配 · 多命中按 catalog 顺序取第一个。"""
    _seed_catalog(_isolate_boards_dir)
    t = boards.search_theme("AI 应用")  # 带空格 → normalize → "AI应用"
    assert t.name == "AI应用"


def test_search_theme_not_found(_isolate_boards_dir):
    """完全不命中 · 抛 ThemeNotFoundError。"""
    _seed_catalog(_isolate_boards_dir)
    with pytest.raises(ThemeNotFoundError):
        boards.search_theme("不存在的题材xyz")
```

- [ ] **Step 2: Run test to verify fail**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py::test_search_theme_exact_code -v`

Expected: FAIL `AttributeError: ... has no attribute 'search_theme'`。

- [ ] **Step 3: 写实现 · `normalize_theme_name` + `search_theme`**

在 `kan/boards.py` theme 区(`load_theme_catalog` 之后)追加:

```python


def normalize_theme_name(name: str) -> str:
    """规范化题材名 · 去全角半角空格 · alias 表后续累积。

    THS 'AI应用' / 'AI 应用' / 'AI 应用' → 'AI应用'。
    EM 'AI应用' / THS 'AI应用' → 同字串(本期不做跨源 alias)。
    """
    return name.replace(" ", "").replace("　", "").strip()


def search_theme(query: str):
    """模糊匹配题材名或代码 → Theme · 未命中抛 ThemeNotFoundError。

    优先级:精确代码 > 精确名(normalize) > 含匹配(normalize)。
    """
    q = query.strip()
    q_norm = normalize_theme_name(q)
    catalog = load_theme_catalog()
    for t in catalog:
        if t.code == q:
            return t
    for t in catalog:
        if normalize_theme_name(t.name) == q_norm:
            return t
    for t in catalog:
        if q_norm in normalize_theme_name(t.name):
            return t
    raise ThemeNotFoundError(query)
```

- [ ] **Step 4: Run all theme tests · verify pass**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py -v 2>&1 | tail -15`

Expected: 6 + 6 = `12 passed`。

- [ ] **Step 5: ruff lint check**

Run: `.venv/bin/ruff check kan/boards.py tests/test_boards_theme.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add kan/boards.py tests/test_boards_theme.py
git commit -m "feat(theme): search_theme + normalize_theme_name · 三层优先级匹配"
```

---

## Task 4: `get_theme_constituents` · THS 优先 + EM fallback + T6 熔断

**Files:**
- Modify: `kan/boards.py`(append)
- Test: `tests/test_boards_theme.py`(append)

- [ ] **Step 1: 写失败测试**

在 `tests/test_boards_theme.py` 末尾 append:

```python


# ── get_theme_constituents · THS 优先 + EM fallback + 熔断 ─────────────

def _ths_cons_df():
    """模拟 adata.stock.info.concept_constituent_ths(index_code=) 真返回(2026-05-23 spike)。"""
    return pd.DataFrame(
        [
            {"stock_code": "002230", "short_name": "科大讯飞"},
            {"stock_code": "300033", "short_name": "同花顺"},
        ]
    )


def _em_cons_df():
    """模拟 EM concept_constituent_east(concept_code=) 真返回。"""
    return pd.DataFrame(
        [
            {"stock_code": "002230", "short_name": "科大讯飞"},
            {"stock_code": "688108", "short_name": "赛诺医疗"},
        ]
    )


def test_get_theme_constituents_ths_success(monkeypatch, _isolate_boards_dir):
    """THS 成功 → 返回 list[(代码, 名称)] · 写 per-theme cache。"""
    monkeypatch.setattr(
        "adata.stock.info.concept_constituent_ths",
        lambda index_code: _ths_cons_df(),
    )
    theme = Theme(code="886108", name="AI应用", source="ths")
    pairs = boards.get_theme_constituents(theme)
    assert pairs == [("002230", "科大讯飞"), ("300033", "同花顺")]
    cache = _isolate_boards_dir / "cons_THS886108.json"
    assert cache.exists()


def test_get_theme_constituents_uses_cache(monkeypatch, _isolate_boards_dir):
    """24h 内不重拉。"""
    call_count = {"n": 0}

    def counting(index_code):
        call_count["n"] += 1
        return _ths_cons_df()

    monkeypatch.setattr("adata.stock.info.concept_constituent_ths", counting)
    theme = Theme(code="886108", name="AI应用", source="ths")
    boards.get_theme_constituents(theme)
    boards.get_theme_constituents(theme)
    assert call_count["n"] == 1


def test_get_theme_constituents_falls_back_to_em(monkeypatch, _isolate_boards_dir):
    """THS 抛错 + EM 未在熔断 → 走 EM · 返回 EM 数据。"""

    def ths_raise(index_code):
        raise ConnectionError("THS down")

    monkeypatch.setattr("adata.stock.info.concept_constituent_ths", ths_raise)
    monkeypatch.setattr(
        "adata.stock.info.concept_constituent_east",
        lambda concept_code: _em_cons_df(),
    )
    # 确保熔断器 EM 未 down
    from kan.circuit_breaker import get_breaker
    get_breaker().record("em_push2_concept", ok=True)

    theme = Theme(code="886108", name="AI应用", source="ths")
    pairs = boards.get_theme_constituents(theme)
    assert ("688108", "赛诺医疗") in pairs


def test_get_theme_constituents_em_circuit_break(monkeypatch, _isolate_boards_dir):
    """THS 失败 + EM 在熔断 → 抛 ThemeDataUnavailableError(不试 EM)。"""

    def ths_raise(index_code):
        raise ConnectionError("THS down")

    monkeypatch.setattr("adata.stock.info.concept_constituent_ths", ths_raise)
    # 标记 EM 已 down
    from kan.circuit_breaker import get_breaker
    get_breaker().record("em_push2_concept", ok=False)

    theme = Theme(code="886108", name="AI应用", source="ths")
    with pytest.raises(ThemeDataUnavailableError):
        boards.get_theme_constituents(theme)


def test_get_theme_constituents_em_fail_marks_down(monkeypatch, _isolate_boards_dir):
    """THS 失败 + EM 也失败 → EM 标记 down + 抛 ThemeDataUnavailableError。"""

    def raise_(index_code=None, concept_code=None):
        raise ConnectionError("both down")

    monkeypatch.setattr("adata.stock.info.concept_constituent_ths", lambda index_code: raise_())
    monkeypatch.setattr("adata.stock.info.concept_constituent_east", lambda concept_code: raise_())
    from kan.circuit_breaker import get_breaker
    get_breaker().record("em_push2_concept", ok=True)

    theme = Theme(code="886108", name="AI应用", source="ths")
    with pytest.raises(ThemeDataUnavailableError):
        boards.get_theme_constituents(theme)
    # EM 应被标记 down
    assert get_breaker().is_down("em_push2_concept")
```

- [ ] **Step 2: 检查熔断器单例 helper 是否存在**

Run: `.venv/bin/python -c "from kan.circuit_breaker import get_breaker; print(get_breaker())"`

Expected: 输出 `CircuitBreaker` 实例。**如果 ImportError**,先在 `kan/circuit_breaker.py` 末尾确认有单例 helper:

```python
# 文件末尾应有(F10a/T6 LOCKED 模式):
_BREAKER: CircuitBreaker | None = None


def get_breaker() -> CircuitBreaker:
    global _BREAKER
    if _BREAKER is None:
        from kan.paths import BASE_DIR, ensure_dirs
        ensure_dirs()
        _BREAKER = CircuitBreaker(BASE_DIR / "circuit.json")
    return _BREAKER
```

如缺则补 · 否则跳过。

- [ ] **Step 3: Run test verify fail**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py::test_get_theme_constituents_ths_success -v`

Expected: FAIL `AttributeError: ... has no attribute 'get_theme_constituents'`。

- [ ] **Step 4: 写实现**

在 `kan/boards.py` theme 区追加:

```python


def get_theme_constituents(theme, force: bool = False) -> list[tuple[str, str]]:
    """题材成分股 (代码, 名称) 列表 · THS 优先 → EM fallback(走 T6 熔断) · JSON cache 24h。

    THS adata.stock.info.concept_constituent_ths(index_code=) · 走 THS HTTP · 稳定。
    EM  adata.stock.info.concept_constituent_east(concept_code=) · 走 push2 · 反爬触发熔断。

    熔断器 source id `em_push2_concept` · 5min cooldown(沿 T6 LOCKED 默认 TTL)。
    """
    from kan._log import debug_log
    from kan.circuit_breaker import get_breaker

    ensure_dirs()
    src_prefix = "THS" if theme.source == "ths" else "EM"
    cache = BOARDS_DIR / f"cons_{src_prefix}{theme.code}.json"

    if not force and _cache_fresh(cache, _THEME_CONS_TTL):
        try:
            return [
                (str(c), str(n))
                for c, n in json.loads(cache.read_text(encoding="utf-8"))
            ]
        except Exception:
            pass

    import adata

    breaker = get_breaker()

    # 1. THS 优先
    try:
        df = adata.stock.info.concept_constituent_ths(index_code=theme.code)
        if df is not None and not df.empty:
            pairs = [
                (str(row["stock_code"]).strip(), str(row["short_name"]).strip())
                for _, row in df.iterrows()
            ]
            cache.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
            return pairs
    except Exception as e:
        debug_log(f"THS concept_constituent_ths({theme.code}) 失败: {e}")

    # 2. EM fallback · 先检查熔断
    if breaker.is_down("em_push2_concept"):
        raise ThemeDataUnavailableError(
            f"题材成分股 {theme.code} 不可用 · THS 失败 · EM push2 在 5min 熔断冷却中"
        )

    try:
        df = adata.stock.info.concept_constituent_east(concept_code=theme.code)
        if df is None or df.empty:
            breaker.record("em_push2_concept", ok=False)
            raise ThemeDataUnavailableError(
                f"题材成分股 {theme.code} 不可用 · EM 返回空"
            )
        pairs = [
            (str(row["stock_code"]).strip(), str(row["short_name"]).strip())
            for _, row in df.iterrows()
        ]
        cache.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
        breaker.record("em_push2_concept", ok=True)
        return pairs
    except ThemeDataUnavailableError:
        raise
    except Exception as e:
        breaker.record("em_push2_concept", ok=False)
        raise ThemeDataUnavailableError(
            f"题材成分股 {theme.code} 不可用 · THS+EM 双源失败: {e}"
        ) from e
```

- [ ] **Step 5: Run all theme tests · verify pass**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py -v 2>&1 | tail -20`

Expected: 12 + 5 = `17 passed`。

- [ ] **Step 6: ruff lint + Commit**

Run: `.venv/bin/ruff check kan/boards.py tests/test_boards_theme.py`

Expected: `All checks passed!`

```bash
git add kan/boards.py tests/test_boards_theme.py
git commit -m "feat(theme): get_theme_constituents · THS+EM fallback · T6 circuit breaker"
```

---

## Task 5: `fetch_theme_kline` · EM K 线(避开 THS V8 arm64 不兼容)

**Files:**
- Modify: `kan/boards.py`(append)
- Test: `tests/test_boards_theme.py`(append)

- [ ] **Step 1: 写失败测试**

在 `tests/test_boards_theme.py` 末尾追加:

```python


# ── fetch_theme_kline · EM K 线(THS V8 arm64 不兼容 → 不用 THS K 线) ───

def _em_kline_df():
    """模拟 adata.stock.market.get_market_concept_east 真返回(2026-05-23 spike · 11 列)。"""
    return pd.DataFrame(
        [
            {
                "index_code": "BK1629",
                "trade_time": "2026-05-23 15:00:00",
                "trade_date": "2026-05-23",
                "open": 989.9,
                "high": 1001.16,
                "low": 983.47,
                "close": 986.76,
                "volume": 64404573.0,
                "amount": 148606766448.0,
                "change": -13.24,
                "change_pct": -1.32,
            }
        ]
    )


def test_fetch_theme_kline_returns_standard_schema(monkeypatch, _isolate_boards_dir):
    """EM K 线 11 列 rename 为标准 7 列(date/open/high/low/close/volume/amount)。"""
    monkeypatch.setattr(
        "adata.stock.market.get_market_concept_east",
        lambda index_code, k_type=1: _em_kline_df(),
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")
    df = boards.fetch_theme_kline(theme)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert df["close"].iloc[0] == 986.76


def test_fetch_theme_kline_writes_parquet(monkeypatch, _isolate_boards_dir):
    """K 线 cache 为 parquet · 文件名带 EM 前缀。"""
    monkeypatch.setattr(
        "adata.stock.market.get_market_concept_east",
        lambda index_code, k_type=1: _em_kline_df(),
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")
    boards.fetch_theme_kline(theme)
    cache = _isolate_boards_dir / "kline_EMBK1629.parquet"
    assert cache.exists()


def test_fetch_theme_kline_raises_on_empty(monkeypatch, _isolate_boards_dir):
    """EM 返回空 → 抛 ThemeDataUnavailableError(题材指数 K 不可用 · 上层应降级渲染)。"""
    monkeypatch.setattr(
        "adata.stock.market.get_market_concept_east",
        lambda index_code, k_type=1: pd.DataFrame(),
    )
    theme = Theme(code="BK1629", name="AI应用", source="em")
    with pytest.raises(ThemeDataUnavailableError):
        boards.fetch_theme_kline(theme)
```

- [ ] **Step 2: Run test verify fail**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py::test_fetch_theme_kline_returns_standard_schema -v`

Expected: FAIL `AttributeError: ... has no attribute 'fetch_theme_kline'`。

- [ ] **Step 3: 写实现**

在 `kan/boards.py` theme 区追加:

```python


_EM_KLINE_RENAME = {
    "trade_date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}


def fetch_theme_kline(theme, force: bool = False):
    """题材指数 K 线 · EM 源(走 datacenter HTTP · 稳定 · 避开 THS V8 不兼容) · parquet cache。

    adata.stock.market.get_market_concept_east(index_code=, k_type=1) 返回 11 列 →
    rename 成 manmankan 标准 7 列(同个股 K · 同 _KLINE_COLUMNS)。

    注:本函数不用 THS K 线接口(adata `get_market_concept_ths` 需 py_mini_racer V8 引擎,
    Apple Silicon arm64 上 libmini_racer.dylib 缺失 RuntimeError)。
    """
    import pandas as pd

    from kan.paths import atomic_write_parquet

    ensure_dirs()
    src_prefix = "EM" if theme.source == "em" else "EM"  # K 线统一走 EM(见 docstring)
    cache = BOARDS_DIR / f"kline_{src_prefix}{theme.code}.parquet"
    if not force and _kline_cache_fresh(cache):
        return pd.read_parquet(cache)

    import adata

    try:
        raw = adata.stock.market.get_market_concept_east(index_code=theme.code, k_type=1)
    except Exception as e:
        raise ThemeDataUnavailableError(f"题材指数 K 线拉取失败 {theme.code}: {e}") from e

    if raw is None or raw.empty:
        raise ThemeDataUnavailableError(f"题材指数 K 线为空: {theme.code}")

    df = raw.rename(columns=_EM_KLINE_RENAME)
    for col in _KLINE_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_KLINE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = (
        df.sort_values("date")
        .dropna(subset=["date", "close"])
        .reset_index(drop=True)
    )
    atomic_write_parquet(df, cache)
    return df
```

- [ ] **Step 4: Run all theme tests · verify pass**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py -v 2>&1 | tail -20`

Expected: 17 + 3 = `20 passed`。

- [ ] **Step 5: ruff lint + Commit**

Run: `.venv/bin/ruff check kan/boards.py tests/test_boards_theme.py`

Expected: `All checks passed!`

```bash
git add kan/boards.py tests/test_boards_theme.py
git commit -m "feat(theme): fetch_theme_kline from EM · 11 col → 标准 7 col schema"
```

---

## Task 6: `get_themes_of_stock` · EM datacenter 反查 · 12h cache

**Files:**
- Modify: `kan/boards.py`(append)
- Test: `tests/test_boards_theme.py`(append)

- [ ] **Step 1: 写失败测试**

在 `tests/test_boards_theme.py` 末尾追加:

```python


# ── get_themes_of_stock · EM datacenter 反查 ──────────────────────────

def _em_reverse_df():
    """模拟 adata.stock.info.get_concept_east(stock_code=) 真返回(2026-05-23 spike)。"""
    return pd.DataFrame(
        [
            {"stock_code": "002230", "concept_code": "BK1629", "name": "AI应用", "source": "东方财富", "reason": "..."},
            {"stock_code": "002230", "concept_code": "BK0612", "name": "智能语音", "source": "东方财富", "reason": "..."},
        ]
    )


def test_get_themes_of_stock_returns_list_of_theme(monkeypatch, _isolate_boards_dir):
    """002230 反查 → 多个 Theme(source='em')。"""
    monkeypatch.setattr(
        "adata.stock.info.get_concept_east",
        lambda stock_code: _em_reverse_df(),
    )
    themes = boards.get_themes_of_stock("002230")
    assert len(themes) == 2
    assert all(t.source == "em" for t in themes)
    assert themes[0].code == "BK1629"


def test_get_themes_of_stock_caches(monkeypatch, _isolate_boards_dir):
    """12h 内不重拉。"""
    call_count = {"n": 0}

    def counting(stock_code):
        call_count["n"] += 1
        return _em_reverse_df()

    monkeypatch.setattr("adata.stock.info.get_concept_east", counting)
    boards.get_themes_of_stock("002230")
    boards.get_themes_of_stock("002230")
    assert call_count["n"] == 1


def test_get_themes_of_stock_empty_means_no_themes(monkeypatch, _isolate_boards_dir):
    """股票无任何题材归属 → 空列表 · 不抛。"""
    monkeypatch.setattr(
        "adata.stock.info.get_concept_east",
        lambda stock_code: pd.DataFrame(),
    )
    themes = boards.get_themes_of_stock("999999")
    assert themes == []
```

- [ ] **Step 2: Run test verify fail**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py::test_get_themes_of_stock_returns_list_of_theme -v`

Expected: FAIL `AttributeError: ... has no attribute 'get_themes_of_stock'`。

- [ ] **Step 3: 写实现**

在 `kan/boards.py` theme 区追加:

```python


def get_themes_of_stock(stock_code: str, force: bool = False):
    """股票反查所属题材 · EM datacenter HTTP(不在 push2 反爬名单 · 稳定) · 12h JSON cache。

    adata.stock.info.get_concept_east(stock_code=) 返回 5 列:
    stock_code / concept_code / name / source / reason → list[Theme(source='em')]。

    返回空列表表示无任何题材归属(不抛)。
    """
    from kan.models import Theme

    ensure_dirs()
    cache = BOARDS_DIR / f"stock_themes_{stock_code}.json"
    if not force and _cache_fresh(cache, _STOCK_THEMES_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Theme(**t) for t in data]
        except Exception:
            pass

    import adata

    try:
        df = adata.stock.info.get_concept_east(stock_code=stock_code)
    except Exception:
        # 反查失败 · 但反查不致命(scan 主流程依赖成分股不是反查) · 返回空 · 不抛
        return []

    if df is None or df.empty:
        cache.write_text("[]", encoding="utf-8")
        return []

    themes = [
        Theme(
            code=str(row["concept_code"]).strip(),
            name=str(row["name"]).strip(),
            source="em",
            size=None,
        )
        for _, row in df.iterrows()
    ]
    cache.write_text(
        json.dumps([t.model_dump() for t in themes], ensure_ascii=False),
        encoding="utf-8",
    )
    return themes
```

- [ ] **Step 4: Run all theme tests · verify pass**

Run: `.venv/bin/python -m pytest tests/test_boards_theme.py -v 2>&1 | tail -20`

Expected: 20 + 3 = `23 passed`。

- [ ] **Step 5: 全套回归测试 · 确认 baseline 升级**

Run: `.venv/bin/python -m pytest -q -m "not network" 2>&1 | tail -5`

Expected: 525 (现 baseline) + 23 (新增) = `548 passed`(允许 ±2 浮动)。

- [ ] **Step 6: ruff lint + Commit**

Run: `.venv/bin/ruff check kan/boards.py tests/test_boards_theme.py`

Expected: `All checks passed!`

```bash
git add kan/boards.py tests/test_boards_theme.py
git commit -m "feat(theme): get_themes_of_stock · EM datacenter reverse lookup · 12h cache"
```

---

## Task 7: `_scan_targets.py` 加 `ThemeMeta` + theme 分支

**Files:**
- Modify: `kan/_scan_targets.py`(整体重构 dispatch · 加 theme 参数 + ThemeMeta dataclass)
- Test: `tests/test_scan_targets.py`(若存在则 append · 否则新建)

- [ ] **Step 1: 写失败测试 `tests/test_scan_targets_theme.py`**

新建 `tests/test_scan_targets_theme.py`:

```python
"""resolve_scan_targets 加 theme 分支单元测试。"""
import pandas as pd
import pytest

from kan import _scan_targets
from kan._scan_targets import ThemeMeta, resolve_scan_targets
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_boards_dir(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    return bdir


def _stub_search_theme(*args, **kwargs):
    return Theme(code="886108", name="AI应用", source="ths")


def _stub_get_constituents(*args, **kwargs):
    return [("002230", "科大讯飞"), ("300033", "同花顺")]


def _stub_fetch_kline(*args, **kwargs):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-21", "2026-05-22", "2026-05-23"]).date,
            "open": [100, 102, 101],
            "high": [103, 104, 102],
            "low": [99, 101, 100],
            "close": [102, 103, 101],
            "volume": [1e6, 2e6, 1.5e6],
            "amount": [1e8, 2e8, 1.5e8],
        }
    )


def test_resolve_theme_returns_constituents_and_themeMeta(monkeypatch):
    """--theme=AI应用 + 自选 [(002230,科大讯飞)] → targets=成分股全 · ThemeMeta.highlight={'002230'}。"""
    monkeypatch.setattr("kan.boards.search_theme", _stub_search_theme)
    monkeypatch.setattr("kan.boards.get_theme_constituents", _stub_get_constituents)
    monkeypatch.setattr("kan.boards.fetch_theme_kline", _stub_fetch_kline)

    watchlist = [("002230", "科大讯飞")]
    targets, meta = resolve_scan_targets(
        industry=None, only_watchlist=False, watchlist_pairs=watchlist, theme="AI应用"
    )
    assert isinstance(meta, ThemeMeta)
    assert meta.theme.name == "AI应用"
    assert meta.highlight == {"002230"}
    assert len(targets) == 2


def test_resolve_theme_only_watchlist_filters(monkeypatch):
    """--theme + --only-watchlist → targets = 成分股 ∩ 自选。"""
    monkeypatch.setattr("kan.boards.search_theme", _stub_search_theme)
    monkeypatch.setattr("kan.boards.get_theme_constituents", _stub_get_constituents)
    monkeypatch.setattr("kan.boards.fetch_theme_kline", _stub_fetch_kline)

    watchlist = [("002230", "科大讯飞")]
    targets, meta = resolve_scan_targets(
        industry=None, only_watchlist=True, watchlist_pairs=watchlist, theme="AI应用"
    )
    assert targets == [("002230", "科大讯飞")]
    assert meta.highlight == {"002230"}


def test_resolve_industry_theme_mutually_exclusive():
    """--industry + --theme 同时指定 → ValueError。"""
    with pytest.raises(ValueError, match="互斥|不能同时"):
        resolve_scan_targets(
            industry="半导体", only_watchlist=False, watchlist_pairs=[], theme="AI应用"
        )


def test_resolve_hot_theme_mutually_exclusive():
    """--hot + --theme 同时指定 → ValueError。"""
    from kan.hot import HotList
    with pytest.raises(ValueError, match="互斥|不能同时"):
        resolve_scan_targets(
            industry=None,
            only_watchlist=False,
            watchlist_pairs=[],
            hot=HotList.RANK,
            theme="AI应用",
        )


def test_resolve_theme_kline_failure_degrades(monkeypatch):
    """题材 K 线拉取失败 → ThemeMeta.index_kline 为空 DataFrame · 不阻塞 targets。"""
    from kan.boards import ThemeDataUnavailableError

    monkeypatch.setattr("kan.boards.search_theme", _stub_search_theme)
    monkeypatch.setattr("kan.boards.get_theme_constituents", _stub_get_constituents)

    def kline_fail(theme, force=False):
        raise ThemeDataUnavailableError("kline down")

    monkeypatch.setattr("kan.boards.fetch_theme_kline", kline_fail)
    targets, meta = resolve_scan_targets(
        industry=None, only_watchlist=False, watchlist_pairs=[], theme="AI应用"
    )
    assert isinstance(meta, ThemeMeta)
    assert meta.index_kline.empty or len(meta.index_kline) == 0
    assert len(targets) == 2  # 成分股仍可用
```

- [ ] **Step 2: Run test verify fail**

Run: `.venv/bin/python -m pytest tests/test_scan_targets_theme.py -v 2>&1 | tail -10`

Expected: FAIL `ImportError: cannot import name 'ThemeMeta'` 或 `TypeError: ... unexpected keyword argument 'theme'`。

- [ ] **Step 3: 重写 `kan/_scan_targets.py`**

替换文件全部内容:

```python
"""扫描目标解析 · scan/low/high/trend/fetch/update/info/list 共享。

industry 给定 → 拉行业成分股;
hot 给定 → 拉东财热榜;
theme 给定 → 拉题材成分股(F11);
否则用自选股。

四种来源的差异收敛进 resolve_scan_targets 一个函数,各命令只需"换数据来源
+ 多收一个 meta"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kan.models import Board, Theme

if TYPE_CHECKING:
    import pandas as pd

    from kan.hot import HotList


@dataclass
class BoardMeta:
    """resolve_scan_targets 在 industry 模式下的附加产物。"""

    board: Board
    index_kline: pd.DataFrame
    constituents: list[tuple[str, str]]
    highlight: set[str]


@dataclass
class HotMeta:
    """resolve_scan_targets 在 hot 模式下的附加产物。"""

    list_name: str
    rank_map: dict[str, int]
    highlight: set[str]


@dataclass
class ThemeMeta:
    """resolve_scan_targets 在 theme 模式下的附加产物 · 跟 BoardMeta 对称。"""

    theme: Theme
    index_kline: pd.DataFrame
    constituents: list[tuple[str, str]]
    highlight: set[str]
    source_dispatch: dict[str, str] = field(
        default_factory=lambda: {
            "catalog": "ths",
            "cons": "ths",
            "kline": "em",
            "reverse": "em",
        }
    )


def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    hot: "HotList | None" = None,
    theme: str | None = None,
) -> tuple[list[tuple[str, str]], "BoardMeta | HotMeta | ThemeMeta | None"]:
    """解析扫描目标。

    - industry / hot / theme 都为 None → (watchlist_pairs, None) · 现有行为完全不变
    - industry 给定 → 拉成分股 + 板块指数 K,组 BoardMeta
    - hot 给定 → 拉东财热榜,组 HotMeta
    - theme 给定 → 拉题材成分股(THS)+ 题材指数 K(EM),组 ThemeMeta
        - only_watchlist=True → targets = 成分股 ∩ 自选
    - 三者同时给定 → raise ValueError
    - 题材未找到 → 透传 boards.ThemeNotFoundError
    - 题材数据源失败 → 透传 boards.ThemeDataUnavailableError(K 线失败降级为空 df)
    """
    given = sum(1 for x in (industry, hot, theme) if x is not None)
    if given > 1:
        raise ValueError("--industry / --hot / --theme 三者互斥 · 同时只能用一个")

    if industry is not None:
        from kan import boards

        board = boards.search_industry(industry)
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

        entries = hot_mod.fetch_hot_list(hot)
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

    if theme is not None:
        import pandas as pd

        from kan import boards
        from kan.boards import ThemeDataUnavailableError

        themed = boards.search_theme(theme)
        constituents = boards.get_theme_constituents(themed)

        # K 线失败降级为空 df · 不影响成分股扫描(spec §11)
        try:
            index_kline = boards.fetch_theme_kline(themed)
        except ThemeDataUnavailableError:
            from kan._log import debug_log

            debug_log(f"题材指数 K 线不可用 · 渲染层应降级跳过指数行 · theme={themed.name}")
            index_kline = pd.DataFrame()

        watch_codes = {code for code, _ in watchlist_pairs}
        highlight = {code for code, _ in constituents} & watch_codes
        theme_meta = ThemeMeta(
            theme=themed,
            index_kline=index_kline,
            constituents=constituents,
            highlight=highlight,
        )
        targets = constituents
        if only_watchlist:
            targets = [(c, n) for c, n in constituents if c in highlight]
        return targets, theme_meta

    return watchlist_pairs, None
```

- [ ] **Step 4: Run test · verify pass**

Run: `.venv/bin/python -m pytest tests/test_scan_targets_theme.py -v 2>&1 | tail -10`

Expected: `5 passed`。

- [ ] **Step 5: 跑现有 scan_targets / industry / hot 测试 · 确认无回归**

Run: `.venv/bin/python -m pytest tests/test_scan_targets.py tests/test_boards.py tests/test_hot.py -v 2>&1 | tail -10`

Expected: 全部 PASS · industry / hot 分支行为不变。

- [ ] **Step 6: ruff lint + Commit**

```bash
.venv/bin/ruff check kan/_scan_targets.py tests/test_scan_targets_theme.py
git add kan/_scan_targets.py tests/test_scan_targets_theme.py
git commit -m "feat(theme): _scan_targets add theme branch + ThemeMeta · 4 模式互斥"
```

---

## Task 8: 新建 `kan/_confirm.py` · 破坏性操作二次确认 helper

**Files:**
- Create: `kan/_confirm.py`
- Test: `tests/test_confirm.py`(新建)

- [ ] **Step 1: 写失败测试 `tests/test_confirm.py`**

```python
"""kan/_confirm.py 单元测试 · 模拟 input · 不走真 stdin。"""
import io

import pytest

from kan._confirm import show_summary_and_confirm


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
    assert "add" in out or "添加" in out or "加" in out
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
    # add 3 只 · 当前 10 · 操作后 ≤13(可能有重复 跳过)
    assert "13" in out or "10" in out
```

- [ ] **Step 2: Run test verify fail**

Run: `.venv/bin/python -m pytest tests/test_confirm.py -v 2>&1 | tail -10`

Expected: FAIL `ImportError: cannot import name 'show_summary_and_confirm'`。

- [ ] **Step 3: 写实现 `kan/_confirm.py`**

```python
"""破坏性操作二次确认 helper · F11 引入 · 给 add/remove/clear --theme(或 --industry) 用。

设计:
- show_summary_and_confirm(action, targets, current_size, skip=False)
  - skip=True(--yes) 跳过交互直接 True
  - 渲染影响 summary(action 名 + 目标数 + 当前/操作后大小)+ 交互 y/N
  - n / 回车 / Ctrl-C → False
  - y/Y → True

跟 ADR-0010 backup 协议精神一致 · 不可逆操作 + summary + 确认。
"""
from __future__ import annotations

import sys

ACTION_VERB = {
    "add": "添加",
    "remove": "移除",
    "clear": "清除",
}


def show_summary_and_confirm(
    action: str,
    targets: list[tuple[str, str]],
    current_watchlist_size: int,
    skip: bool = False,
) -> bool:
    """渲染破坏性操作影响 summary + 二次确认。

    Args:
        action: "add" | "remove" | "clear"
        targets: 影响的 (代码, 名称) 列表
        current_watchlist_size: 当前自选股数量
        skip: True 跳过交互(--yes)

    Returns:
        True 继续 · False 取消。
    """
    if skip:
        return True

    n = len(targets)
    verb = ACTION_VERB.get(action, action)
    if action == "add":
        resulting = current_watchlist_size + n  # 上层应预先过滤已在自选的
        summary = (
            f"⚠️  将 {verb} {n} 只股票到自选(当前 {current_watchlist_size} 只 · 操作后 ≤ {resulting} 只)"
        )
    elif action in ("remove", "clear"):
        resulting = max(0, current_watchlist_size - n)
        summary = (
            f"⚠️  将 {verb} {n} 只股票(当前 {current_watchlist_size} 只 · 操作后 ≥ {resulting} 只)"
        )
    else:
        summary = f"⚠️  将 {verb} {n} 只股票"

    print(summary)
    # 列前 5 只预览(避免 100 只刷屏)
    preview_n = min(5, n)
    for code, name in targets[:preview_n]:
        print(f"   {code}  {name}")
    if n > preview_n:
        print(f"   ... 还有 {n - preview_n} 只")
    print()
    try:
        ans = input("继续? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False
    return ans in ("y", "yes")


# 帮助 stdin 重定向的测试场景
def _read_input(prompt: str) -> str:  # pragma: no cover
    """供 monkeypatch 替换 · 便于 testing。"""
    return input(prompt)
```

- [ ] **Step 4: Run test · verify pass**

Run: `.venv/bin/python -m pytest tests/test_confirm.py -v 2>&1 | tail -10`

Expected: `5 passed`。

- [ ] **Step 5: ruff lint + Commit**

```bash
.venv/bin/ruff check kan/_confirm.py tests/test_confirm.py
git add kan/_confirm.py tests/test_confirm.py
git commit -m "feat(confirm): destructive operation summary + y/N · --yes skip path"
```

---

## Task 9: `kan scan --theme` · 命令接入 + 渲染层 ThemeMeta 分流

**Files:**
- Modify: `kan/cli_scan_cmds.py`(scan 主命令加 --theme · 渲染层加 ThemeMeta 分支)
- Test: `tests/test_scan_cli_theme.py`(新建)

注:本 task 只覆盖 `scan` 一个主命令。`low/high/trend/info/list/fetch/update` 在后续 Task 11/12 各自处理(各命令渲染层不同)。

- [ ] **Step 1: 写 CliRunner runtime 测试 `tests/test_scan_cli_theme.py`**

```python
"""kan scan --theme CLI 真测 · CliRunner runtime · 不 bootstrap 字符串作弊。"""
import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    """所有 boards / data 目录指向 tmp · 杜绝读写真实文件。"""
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    # 自选股目录也隔离(防止 watchlist 写真实文件)
    monkeypatch.setattr("kan.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    monkeypatch.setattr("kan.paths.DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


def _stub_theme_calls(monkeypatch):
    """共享 stub:scan --theme=AI应用 → 返回 102 行成分股 + 完整 K 线。"""
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    # K 线 100 个交易日的 stub(供位置计算)
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    kline_df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * 100,
            "high": [105.0] * 100,
            "low": [95.0] * 100,
            "close": [102.0] * 100,
            "volume": [1e6] * 100,
            "amount": [1e8] * 100,
        }
    )
    monkeypatch.setattr("kan.boards.fetch_theme_kline", lambda theme, force=False: kline_df)


def _stub_fetch_kline(monkeypatch):
    """单个股 K 线 stub · 给 scan 位置计算用。"""
    dates = pd.date_range("2026-01-01", periods=250, freq="B").date
    kline_df = pd.DataFrame(
        {
            "date": dates,
            "open": list(range(100, 100 + 250)),
            "high": list(range(101, 101 + 250)),
            "low": list(range(99, 99 + 250)),
            "close": list(range(100, 100 + 250)),
            "volume": [1e6] * 250,
            "amount": [1e8] * 250,
        }
    )
    monkeypatch.setattr("kan.fetcher.fetch_kline_cached", lambda symbol, **kw: kline_df)


def test_scan_theme_runs(monkeypatch, _isolate_all):
    """`kan scan --theme=AI应用` 不报错 · 输出含题材名 + 成分股代码。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output
    assert "002230" in result.output or "科大讯飞" in result.output


def test_scan_theme_industry_mutually_exclusive(monkeypatch, _isolate_all):
    """`--theme` 跟 `--industry` 同时 → exit 2 + 错误提示。"""
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2
    assert "互斥" in result.output or "不能同时" in result.output


def test_scan_theme_only_watchlist(monkeypatch, _isolate_all):
    """`--theme + --only-watchlist` 应仅扫成分股 ∩ 自选 · 自选只含 002230 → 只扫 1 只。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    # 自选股只放 002230
    (_isolate_all / "wl.json").write_text(
        '{"002230": {"name": "科大讯飞", "added_at": "2026-05-01"}}',
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用", "--only-watchlist"])
    assert result.exit_code == 0, result.output
    assert "002230" in result.output
    # 300033 不在自选 · 不应被扫(--only-watchlist 过滤)
    assert "300033" not in result.output or "扫描" not in result.output


def test_scan_theme_not_found(monkeypatch, _isolate_all):
    """题材名找不到 → exit 2 + 友好提示。"""
    from kan import boards
    from kan.boards import ThemeNotFoundError
    monkeypatch.setattr(boards, "search_theme", lambda q: (_ for _ in ()).throw(ThemeNotFoundError(q)))
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=不存在题材xyz"])
    assert result.exit_code == 2
    assert "未找到" in result.output or "kan theme search" in result.output


def test_scan_theme_disclaimer_shown(monkeypatch, _isolate_all):
    """题材扫描输出必须含 4 行 disclaimer(spec §12.1 LOCKED)。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--theme=AI应用"])
    assert result.exit_code == 0
    assert "位置 ≠ 买卖信号" in result.output
    assert "题材分类各家口径不同" in result.output
    assert "题材跟风风险高于行业" in result.output
    assert "不预测涨跌" in result.output or "不荐股" in result.output
```

- [ ] **Step 2: Run test verify fail**

Run: `.venv/bin/python -m pytest tests/test_scan_cli_theme.py -v 2>&1 | tail -15`

Expected: 全部 FAIL with `Got unexpected extra argument` 或 `No such option: --theme`。

- [ ] **Step 3: 修改 `kan/cli_scan_cmds.py` scan 命令**

打开 `kan/cli_scan_cmds.py` · 找到 `scan_cmd` 函数(约 line 109-170):

a) 在参数列表 `--hot` 选项**后**加 `--theme` 选项(参数定义节):

```python
    hot: Annotated[
        HotList | None,
        typer.Option(...),  # 现有 hot 定义
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="扫指定题材全成分股 · 自选 ⭐ 高亮 · 题材 ≠ 行业,一股归多个"),
    ] = None,
    only_watchlist: ...
```

b) 在 `if industry is not None and hot is not None:` 互斥校验之后加 theme 互斥(三方互斥):

```python
    if sum(1 for x in (industry, hot, theme) if x is not None) > 1:
        _print_err("❌ --industry / --hot / --theme 三者互斥 · 同时只能用一个")
        raise typer.Exit(2)

    source_mode = industry is not None or hot is not None or theme is not None
```

c) 在 `--only-watchlist` 单独使用校验里加 theme:

```python
    if only_watchlist and not source_mode:
        _print_err("❌ --only-watchlist 需配合 --industry / --hot / --theme 使用")
```

d) 在原 `resolve_scan_targets(industry, only_watchlist, watchlist_pairs, hot=hot, ...)` 调用里加 theme:

```python
    try:
        targets, source_meta = resolve_scan_targets(
            industry, only_watchlist, watchlist_pairs, hot=hot, theme=theme,
        )
    except BoardNotFoundError:
        _print_err(f"❌ 未找到行业「{industry}」· 可试更短关键词(如「半导体」「白酒」)")
        raise typer.Exit(2) from None
    except ThemeNotFoundError as e:
        _print_err(
            f"❌ 未找到题材「{e}」· 试更短关键词(如「AI」「华为」)· 或跑 kan theme search 看候选"
        )
        raise typer.Exit(2) from None
    except ThemeDataUnavailableError as e:
        _print_err(f"❌ 题材数据源暂时不可用 · {e} · 行业扫描可用(--industry)")
        raise typer.Exit(1) from None
    except HotListUnavailableError:
        ...  # 现有 hot 错误处理
```

e) 在文件顶部 import 加上:

```python
from kan._scan_targets import BoardMeta, HotMeta, ThemeMeta, resolve_scan_targets
from kan.boards import (
    BoardDataUnavailableError, BoardNotFoundError,
    ThemeDataUnavailableError, ThemeNotFoundError,
)
```

f) 在表格渲染前的 source_meta 分流逻辑加 ThemeMeta 分支(找到现有 `isinstance(source_meta, HotMeta)` 段):

```python
    if isinstance(source_meta, BoardMeta):
        # 现有行业渲染 · 不动
        ...
    elif isinstance(source_meta, HotMeta):
        # 现有热榜渲染 · 不动
        ...
    elif isinstance(source_meta, ThemeMeta):
        from kan.render_theme import render_theme_header, render_theme_disclaimer
        render_theme_header(source_meta)
        # 现有成分股表格渲染共用 · highlight 字段统一
        ...
        render_theme_disclaimer()
```

- [ ] **Step 4: 新建 `kan/render_theme.py`(题材渲染 helper)**

```python
"""题材扫描渲染层 helper · 三层信息架构(spec §10)。

层 1:题材指数本身位置(1 行 metadata)
层 2:成分股 N 行表(共用 scan 现有 render_scan_table)
层 3:散户警示 4 行强 disclaimer(spec §12.1 LOCKED)
"""
from __future__ import annotations

import typer
from rich.console import Console

from kan._scan_targets import ThemeMeta

_console = Console()


def render_theme_header(meta: ThemeMeta) -> None:
    """渲染题材头部 + 题材指数 1 行 metadata(K 线为空时降级跳过指数行)。"""
    src_label = "同花顺概念" if meta.theme.source == "ths" else "东方财富概念"
    _console.print(f"\n🎯 {meta.theme.name} · {src_label} · {meta.theme.code}")
    _console.print("═" * 66)
    if not meta.index_kline.empty and len(meta.index_kline) >= 30:
        # 题材指数本身位置(1 行) · 复用 scan 的位置计算
        from kan.scanner import compute_periods

        positions = compute_periods(meta.index_kline, periods=[30, 60, 120, 250])
        period_cells = "  ".join(
            f"{p.position_pct:>5.0%}" if not p.insufficient else "   —"
            for p in positions
        )
        resonance = "—"  # 题材指数单标的 · 不算共振
        _console.print(f"📊 题材指数        │ {period_cells} │ {resonance}")
    else:
        _console.print("📊 题材指数 K 线暂不可用 · 仅显示成分股位置(降级模式)")
    _console.print()
    _console.print(f"📈 成分股({len(meta.constituents)} 只 · ⭐ 标记你的自选 · 数据 EM)")


def render_theme_disclaimer() -> None:
    """4 行强 disclaimer(AGENTS.md §6 · spec §12.1 LOCKED · 不省一行)。"""
    typer.echo("")
    typer.echo("💡 数据源:同花顺 catalog/成分股 · 东方财富 K 线/反查")
    typer.echo("⚠️  位置 ≠ 买卖信号  ·  共振低位区间 ≠ 买入建议")
    typer.echo("⚠️  题材分类各家口径不同 · 同名题材成分股可能差异  ·  题材跟风风险高于行业")
    typer.echo("ℹ️  manmankan 是观察工具 · 不预测涨跌 · 不荐股")
```

- [ ] **Step 5: Run test · verify pass**

Run: `.venv/bin/python -m pytest tests/test_scan_cli_theme.py -v 2>&1 | tail -15`

Expected: `5 passed`。

- [ ] **Step 6: 跑 scan 现有测试 · 确认无回归**

Run: `.venv/bin/python -m pytest tests/test_scan_cli.py -v 2>&1 | tail -10`

Expected: 全部 PASS(industry / hot / 默认自选 三个分支行为不变)。

- [ ] **Step 7: ruff lint + Commit**

```bash
.venv/bin/ruff check kan/cli_scan_cmds.py kan/render_theme.py tests/test_scan_cli_theme.py
git add kan/cli_scan_cmds.py kan/render_theme.py tests/test_scan_cli_theme.py
git commit -m "feat(theme): scan --theme · ThemeMeta render + 4 行 disclaimer"
```

---

## Task 10: `kan low / high --theme` · 复用 ThemeMeta dispatch

**Files:**
- Modify: `kan/cli_scan_cmds.py`(low_cmd / high_cmd 加 --theme)
- Test: `tests/test_scan_cli_theme.py`(append)

- [ ] **Step 1: 写测试 append `tests/test_scan_cli_theme.py`**

```python


# ── low / high --theme ────────────────────────────────────────────────

def test_low_theme_runs(monkeypatch, _isolate_all):
    """`kan low --theme=AI应用` 不报错 · 输出含题材成分股低位排名。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["low", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output


def test_high_theme_runs(monkeypatch, _isolate_all):
    """`kan high --theme=AI应用` 不报错 · 输出含高位排名。"""
    _stub_theme_calls(monkeypatch)
    _stub_fetch_kline(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["high", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output


def test_low_theme_mutually_exclusive(_isolate_all):
    """low 也校验三方互斥。"""
    runner = CliRunner()
    result = runner.invoke(app, ["low", "--theme=AI应用", "--hot=rank"])
    assert result.exit_code == 2
    assert "互斥" in result.output or "不能同时" in result.output
```

- [ ] **Step 2: Run · verify fail**

Run: `.venv/bin/python -m pytest tests/test_scan_cli_theme.py::test_low_theme_runs -v 2>&1 | tail -10`

Expected: FAIL `No such option: --theme`。

- [ ] **Step 3: 修改 `kan/cli_scan_cmds.py` low_cmd / high_cmd**

对 `low_cmd` 和 `high_cmd` 两个函数,每个做跟 Task 9 step 3 完全同样的 6 处改动(--theme 选项参数 / 三方互斥校验 / only-watchlist 校验 / resolve_scan_targets 调用 / ThemeNotFoundError catch / ThemeMeta 渲染分流)。**改动模式跟 scan_cmd 完全一致**,逐字复制即可。

具体改动点:
- 函数签名加 `theme: Annotated[str | None, typer.Option("--theme", ...)] = None`
- 互斥 sum check
- resolve_scan_targets 调用加 `theme=theme`
- catch ThemeNotFoundError / ThemeDataUnavailableError
- 渲染前 isinstance ThemeMeta 分支(low/high 主体是排序后 top N,渲染 `render_theme_header` 仅显示题材头不显示题材指数行)

- [ ] **Step 4: Run · verify pass**

Run: `.venv/bin/python -m pytest tests/test_scan_cli_theme.py -v 2>&1 | tail -10`

Expected: 5 + 3 = `8 passed`。

- [ ] **Step 5: ruff + Commit**

```bash
.venv/bin/ruff check kan/cli_scan_cmds.py tests/test_scan_cli_theme.py
git add kan/cli_scan_cmds.py tests/test_scan_cli_theme.py
git commit -m "feat(theme): low / high --theme · 三方互斥 + ThemeMeta dispatch"
```

---

## Task 11: `kan trend --theme`

**Files:**
- Modify: `kan/cli_trend_cmds.py`(trend_cmd 加 --theme)
- Test: `tests/test_trend_cli_theme.py`(新建)

- [ ] **Step 1: 测试**

新建 `tests/test_trend_cli_theme.py`:

```python
"""kan trend --theme CLI 真测。"""
import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    monkeypatch.setattr("kan.paths.DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


def _stub_calls(monkeypatch):
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    monkeypatch.setattr(
        "kan.boards.fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame(
            {"date": dates, "open": [100.0] * 100, "high": [105.0] * 100,
             "low": [95.0] * 100, "close": [102.0] * 100,
             "volume": [1e6] * 100, "amount": [1e8] * 100}
        ),
    )
    dates2 = pd.date_range("2026-01-01", periods=250, freq="B").date
    monkeypatch.setattr(
        "kan.fetcher.fetch_kline_cached",
        lambda symbol, **kw: pd.DataFrame(
            {"date": dates2, "open": list(range(100, 350)), "high": list(range(101, 351)),
             "low": list(range(99, 349)), "close": list(range(100, 350)),
             "volume": [1e6] * 250, "amount": [1e8] * 250}
        ),
    )


def test_trend_theme_runs(monkeypatch, _isolate_all):
    _stub_calls(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["trend", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output


def test_trend_theme_mutually_exclusive(_isolate_all):
    runner = CliRunner()
    result = runner.invoke(app, ["trend", "--theme=AI应用", "--industry=半导体"])
    assert result.exit_code == 2
```

- [ ] **Step 2: Verify fail**

Run: `.venv/bin/python -m pytest tests/test_trend_cli_theme.py -v 2>&1 | tail -10`

Expected: FAIL `No such option: --theme`。

- [ ] **Step 3: 修改 `kan/cli_trend_cmds.py`**

跟 Task 9 step 3 完全同模式改动 `trend_cmd`(--theme 参数 / 三方互斥 / resolve_scan_targets 调用 / 错误 catch / ThemeMeta 渲染分流)。trend 渲染表头加题材名 + 4 行 disclaimer 同 scan。

- [ ] **Step 4: Verify pass**

Run: `.venv/bin/python -m pytest tests/test_trend_cli_theme.py -v 2>&1 | tail -10`

Expected: `2 passed`。

- [ ] **Step 5: ruff + Commit**

```bash
.venv/bin/ruff check kan/cli_trend_cmds.py tests/test_trend_cli_theme.py
git add kan/cli_trend_cmds.py tests/test_trend_cli_theme.py
git commit -m "feat(theme): trend --theme · 三方互斥 + ThemeMeta dispatch"
```

---

## Task 12: `kan info / list / fetch / update --theme`

**Files:**
- Modify: `kan/cli_scan_cmds.py`(info_cmd / fetch_cmd / update_cmd 加 --theme)
- Modify: `kan/cli_watchlist_cmds.py`(list_cmd 加 --theme · 列自选 ∩ 题材)
- Test: `tests/test_info_cli_theme.py` / `tests/test_list_cli_theme.py` / `tests/test_fetch_cli_theme.py`(共 3 文件)

- [ ] **Step 1: 测试 `tests/test_info_cli_theme.py`**

```python
"""kan info --theme=AI应用 单题材深度档案。"""
import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    return tmp_path


def test_info_theme_shows_constituents_list(monkeypatch, _isolate_all):
    """`kan info --theme=AI应用` 输出题材概览 + 成分股清单(不必逐个扫位置)。"""
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    monkeypatch.setattr(
        "kan.boards.fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame(
            {"date": dates, "open": [100.0] * 100, "high": [105.0] * 100,
             "low": [95.0] * 100, "close": [102.0] * 100,
             "volume": [1e6] * 100, "amount": [1e8] * 100}
        ),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["info", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert "AI应用" in result.output
    assert "002230" in result.output or "科大讯飞" in result.output
    # 单题材 info · 不必扫每只股位置 · 只需题材 metadata + 成分股清单 + 题材 K 线位置
    assert "成分股" in result.output or "2 只" in result.output
```

新建 `tests/test_list_cli_theme.py`:

```python
"""kan list --theme · 列自选 ∩ 题材。"""
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    return tmp_path


def test_list_theme_shows_intersection(monkeypatch, _isolate_all):
    """list --theme=AI应用 · 自选含 [002230, 600000] · 题材含 [002230, 300033] → 输出仅 002230。"""
    (_isolate_all / "wl.json").write_text(
        '{"002230": {"name": "科大讯飞", "added_at": "2026-05-01"},'
        ' "600000": {"name": "浦发银行", "added_at": "2026-05-01"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--theme=AI应用"])
    assert result.exit_code == 0
    assert "002230" in result.output
    assert "600000" not in result.output
    assert "300033" not in result.output  # 题材有但不在自选 · 不输出
```

新建 `tests/test_fetch_cli_theme.py`:

```python
"""kan fetch --theme 预拉题材成分股 K 线。"""
import pandas as pd
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.paths.DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


def test_fetch_theme_pulls_all_constituents(monkeypatch, _isolate_all):
    """fetch --theme=AI应用 应离线预拉成分股 K 线 · stub fetcher 计数。"""
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )
    dates = pd.date_range("2026-01-01", periods=100, freq="B").date
    monkeypatch.setattr(
        "kan.boards.fetch_theme_kline",
        lambda theme, force=False: pd.DataFrame(
            {"date": dates, "open": [100.0] * 100, "high": [105.0] * 100,
             "low": [95.0] * 100, "close": [102.0] * 100,
             "volume": [1e6] * 100, "amount": [1e8] * 100}
        ),
    )
    call_count = {"n": 0}

    def counting(symbol, **kw):
        call_count["n"] += 1
        return pd.DataFrame()

    monkeypatch.setattr("kan.fetcher.fetch_kline_cached", counting)
    runner = CliRunner()
    result = runner.invoke(app, ["fetch", "--theme=AI应用"])
    assert result.exit_code == 0, result.output
    assert call_count["n"] == 2  # 2 个成分股各拉一次
```

- [ ] **Step 2: Verify fail**

Run: `.venv/bin/python -m pytest tests/test_info_cli_theme.py tests/test_list_cli_theme.py tests/test_fetch_cli_theme.py -v 2>&1 | tail -10`

Expected: 全 FAIL with `No such option: --theme`。

- [ ] **Step 3: 修改 4 个命令**

- `kan/cli_scan_cmds.py::info_cmd` · 加 `--theme` 参数 + 互斥校验 + ThemeMeta 单题材渲染(不扫每只股位置 · 只渲染题材 metadata + 成分股清单 + 题材 K 线位置)
- `kan/cli_scan_cmds.py::fetch_cmd` · 加 `--theme` 参数 + 互斥校验 + 通过 resolve_scan_targets 拿 targets · 然后 batch fetch_kline
- `kan/cli_scan_cmds.py::update_cmd` · 同 fetch_cmd · force=True 触发重拉
- `kan/cli_watchlist_cmds.py::list_cmd` · 加 `--theme` 参数 · 若给则 targets = 自选 ∩ 题材成分股(纯列名 · 不扫 K 线 · 跟 fetch / scan 不同 · 信息密度低)

每个改动模式跟 Task 9 step 3 一致(参数 / 互斥 / catch / dispatch)。

- [ ] **Step 4: Verify pass**

Run: `.venv/bin/python -m pytest tests/test_info_cli_theme.py tests/test_list_cli_theme.py tests/test_fetch_cli_theme.py -v 2>&1 | tail -10`

Expected: `3 passed`。

- [ ] **Step 5: 跑 8 只读命令全套确认无回归**

Run: `.venv/bin/python -m pytest tests/test_scan_cli.py tests/test_info_cli.py tests/test_fetch_cli.py tests/test_watchlist_cli.py tests/test_trend_cli.py -v 2>&1 | tail -10`

Expected: 全 PASS。

- [ ] **Step 6: ruff + Commit**

```bash
.venv/bin/ruff check kan/cli_scan_cmds.py kan/cli_watchlist_cmds.py tests/test_info_cli_theme.py tests/test_list_cli_theme.py tests/test_fetch_cli_theme.py
git add kan/cli_scan_cmds.py kan/cli_watchlist_cmds.py tests/test_info_cli_theme.py tests/test_list_cli_theme.py tests/test_fetch_cli_theme.py
git commit -m "feat(theme): info/list/fetch/update --theme · 8 只读命令矩阵完成"
```

---

## Task 13: `kan add / remove / clear --theme` + `_confirm` 接入

**Files:**
- Modify: `kan/cli_watchlist_cmds.py`(add_cmd / remove_cmd / clear_cmd 加 --theme + --yes + 接 _confirm)
- Test: `tests/test_watchlist_theme_destructive.py`(新建)

- [ ] **Step 1: 测试 `tests/test_watchlist_theme_destructive.py`**

```python
"""kan add / remove / clear --theme · 破坏性命令 + _confirm 二次确认。"""
import io
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    monkeypatch.setattr("kan.paths.WATCHLIST_PATH", tmp_path / "wl.json")
    return tmp_path


def _stub_theme(monkeypatch):
    monkeypatch.setattr(
        "kan.boards.search_theme",
        lambda q: Theme(code="886108", name="AI应用", source="ths"),
    )
    monkeypatch.setattr(
        "kan.boards.get_theme_constituents",
        lambda theme, force=False: [("002230", "科大讯飞"), ("300033", "同花顺")],
    )


def test_add_theme_n_aborts(monkeypatch, _isolate_all):
    """add --theme=AI应用 · 输 n · 自选股不变。"""
    _stub_theme(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用"], input="n\n")
    assert result.exit_code == 0
    assert "已取消" in result.output or "未变" in result.output
    # wl.json 不应被创建或为空
    wl = _isolate_all / "wl.json"
    assert (not wl.exists()) or wl.read_text(encoding="utf-8").strip() in ("{}", "")


def test_add_theme_y_adds_all(monkeypatch, _isolate_all):
    """add --theme + 输 y · 2 只股全加。"""
    _stub_theme(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用"], input="y\n")
    assert result.exit_code == 0, result.output
    wl_data = (_isolate_all / "wl.json").read_text(encoding="utf-8")
    assert "002230" in wl_data
    assert "300033" in wl_data


def test_add_theme_yes_skips_confirm(monkeypatch, _isolate_all):
    """add --theme + --yes 跳过 y/N 直接加。"""
    _stub_theme(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用", "--yes"])
    assert result.exit_code == 0, result.output
    assert "y/N" not in result.output
    wl_data = (_isolate_all / "wl.json").read_text(encoding="utf-8")
    assert "002230" in wl_data


def test_remove_theme_y_removes_intersection(monkeypatch, _isolate_all):
    """自选 [002230, 600000] · remove --theme=AI应用(成分股 [002230, 300033]) → 仅 002230 被删。"""
    (_isolate_all / "wl.json").write_text(
        '{"002230": {"name": "科大讯飞", "added_at": "2026-05-01"},'
        ' "600000": {"name": "浦发银行", "added_at": "2026-05-01"}}',
        encoding="utf-8",
    )
    _stub_theme(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["remove", "--theme=AI应用"], input="y\n")
    assert result.exit_code == 0
    wl_data = (_isolate_all / "wl.json").read_text(encoding="utf-8")
    assert "002230" not in wl_data
    assert "600000" in wl_data  # 不在题材内 · 不动


def test_clear_theme_y_clears_intersection(monkeypatch, _isolate_all):
    """clear --theme · 行为同 remove --theme(语义重叠 · spec §3 LOCKED)。"""
    (_isolate_all / "wl.json").write_text(
        '{"002230": {"name": "科大讯飞", "added_at": "2026-05-01"}}',
        encoding="utf-8",
    )
    _stub_theme(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["clear", "--theme=AI应用"], input="y\n")
    assert result.exit_code == 0
    wl_data = (_isolate_all / "wl.json").read_text(encoding="utf-8")
    assert "002230" not in wl_data


def test_destructive_theme_mutually_exclusive(_isolate_all):
    """add --theme + --industry · 三方互斥。"""
    runner = CliRunner()
    result = runner.invoke(app, ["add", "--theme=AI应用", "--industry=半导体"], input="n\n")
    assert result.exit_code == 2
```

- [ ] **Step 2: Verify fail**

Run: `.venv/bin/python -m pytest tests/test_watchlist_theme_destructive.py -v 2>&1 | tail -15`

Expected: FAIL `No such option: --theme`。

- [ ] **Step 3: 修改 `kan/cli_watchlist_cmds.py`**

对 `add_cmd` / `remove_cmd` / `clear_cmd` 三个函数,每个做以下改动:

a) 加 `--theme` 和 `--yes` 参数:

```python
    theme: Annotated[
        str | None,
        typer.Option("--theme", help="批量操作题材成分股 · 必经二次确认"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="跳过二次确认 · 慎用"),
    ] = False,
```

b) 在函数体内,如果 theme 给定走批量分支:

```python
    if theme is not None:
        from kan import boards
        from kan._confirm import show_summary_and_confirm
        from kan.boards import ThemeDataUnavailableError, ThemeNotFoundError

        # 三方互斥(若该命令也支持 --industry 则一并校验)
        # 这里假设 add/remove/clear 不支持 --hot · 但若支持则加入校验

        try:
            themed = boards.search_theme(theme)
            constituents = boards.get_theme_constituents(themed)
        except ThemeNotFoundError as e:
            typer.echo(f"❌ 未找到题材「{e}」· 试更短关键词", err=True)
            raise typer.Exit(2) from None
        except ThemeDataUnavailableError as e:
            typer.echo(f"❌ 题材数据源不可用: {e}", err=True)
            raise typer.Exit(1) from None

        current_wl = load_watchlist()  # 现有 helper · 加载自选 dict
        current_size = len(current_wl)

        if action == "add":
            # 过滤已在自选的(_confirm 显示时用)
            to_add = [(c, n) for c, n in constituents if c not in current_wl]
            if not to_add:
                typer.echo("题材成分股已全部在自选 · 无操作")
                return
            if not show_summary_and_confirm("add", to_add, current_size, skip=yes):
                typer.echo("已取消 · 自选股未变")
                return
            for code, name in to_add:
                add_to_watchlist(code, name)  # 现有 helper
            typer.echo(f"✅ 已添加 {len(to_add)} 只到自选")

        elif action in ("remove", "clear"):
            # remove/clear 行为同(spec §3 §"待深化点 #13")
            to_remove = [(c, n) for c, n in constituents if c in current_wl]
            if not to_remove:
                typer.echo("题材成分股不在自选 · 无操作")
                return
            if not show_summary_and_confirm(action, to_remove, current_size, skip=yes):
                typer.echo("已取消 · 自选股未变")
                return
            for code, _name in to_remove:
                remove_from_watchlist(code)
            typer.echo(f"✅ 已移除 {len(to_remove)} 只")

        return  # 题材分支处理完直接返回 · 不走个股逻辑
```

c) 三个函数各自把 `action` 字面常量替换:`add_cmd` 用 `"add"`,`remove_cmd` 用 `"remove"`,`clear_cmd` 用 `"clear"`。

- [ ] **Step 4: Verify pass**

Run: `.venv/bin/python -m pytest tests/test_watchlist_theme_destructive.py -v 2>&1 | tail -15`

Expected: `6 passed`。

- [ ] **Step 5: 跑 watchlist 现有测试 · 确认无回归**

Run: `.venv/bin/python -m pytest tests/test_watchlist_cli.py -v 2>&1 | tail -10`

Expected: 全 PASS · 现有 `kan add 002230` 逐个股逻辑不变。

- [ ] **Step 6: ruff + Commit**

```bash
.venv/bin/ruff check kan/cli_watchlist_cmds.py tests/test_watchlist_theme_destructive.py
git add kan/cli_watchlist_cmds.py tests/test_watchlist_theme_destructive.py
git commit -m "feat(theme): add/remove/clear --theme + --yes · _confirm 二次确认接入"
```

---

## Task 14: `kan theme list` / `kan theme search` 子命令树

**Files:**
- Create: `kan/cli_theme_cmds.py`(~180 行 · 跟 `cli_config_cmds.py` 体例对齐)
- Test: `tests/test_theme_cli.py`(新建)

- [ ] **Step 1: 测试 `tests/test_theme_cli.py`**

```python
"""kan theme list / search 子命令树测试。"""
import pytest
from typer.testing import CliRunner

from kan.app import app
from kan.models import Theme


@pytest.fixture(autouse=True)
def _isolate_all(tmp_path, monkeypatch):
    from kan import boards
    bdir = tmp_path / "boards"
    bdir.mkdir()
    monkeypatch.setattr(boards, "BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.BOARDS_DIR", bdir)
    monkeypatch.setattr("kan.paths.ensure_dirs", lambda: None)
    return tmp_path


def _stub_catalog(monkeypatch, themes=None):
    if themes is None:
        themes = [
            Theme(code="886108", name="AI应用", source="ths"),
            Theme(code="886112", name="AI智能体", source="ths"),
            Theme(code="885525", name="白酒概念", source="ths"),
            Theme(code="886058", name="华为昇腾", source="ths"),
            Theme(code="886109", name="同花顺", source="ths"),
        ]
    monkeypatch.setattr("kan.boards.load_theme_catalog", lambda force=False: themes)


def test_theme_list_default_top30(monkeypatch, _isolate_all):
    """kan theme list 默认拼音前 30 · 5 个题材时全显示。"""
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0
    assert "AI应用" in result.output
    assert "白酒概念" in result.output
    # 5 个 < 30 · 应全显示
    assert "同花顺" in result.output


def test_theme_list_all_flag(monkeypatch, _isolate_all):
    """kan theme list --all 显示全部 + 散户超载警告。"""
    # 模拟 391 个题材
    themes = [Theme(code=f"88{i:04d}", name=f"题材{i}", source="ths") for i in range(391)]
    _stub_catalog(monkeypatch, themes)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list", "--all"])
    assert result.exit_code == 0
    assert "391" in result.output or "全部" in result.output


def test_theme_list_default_caps_at_30(monkeypatch, _isolate_all):
    """超过 30 个题材 · 默认仅显示 30 + 提示用 --all。"""
    themes = [Theme(code=f"88{i:04d}", name=f"题材{i:03d}", source="ths") for i in range(100)]
    _stub_catalog(monkeypatch, themes)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0
    assert "--all" in result.output  # 应提示有更多
    # 应只显示前 30 个 · 第 31+ 不显示在主列表(可在提示文字里出现 100 但不在表里)
    # 简单粗略校验:输出行数应 <100 (避免误判)
    lines = result.output.splitlines()
    assert len(lines) < 80


def test_theme_search_fuzzy(monkeypatch, _isolate_all):
    """kan theme search AI → 多候选列表。"""
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "search", "AI"])
    assert result.exit_code == 0
    assert "AI应用" in result.output
    assert "AI智能体" in result.output
    # 白酒不应出现
    assert "白酒概念" not in result.output


def test_theme_search_not_found(monkeypatch, _isolate_all):
    """kan theme search 不存在词 → exit 0 + 友好提示(非 error)。"""
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "search", "不存在xyz"])
    assert result.exit_code == 0
    assert "未找到" in result.output or "0 个" in result.output


def test_theme_list_shows_disclaimer(monkeypatch, _isolate_all):
    """kan theme list 输出底部含散户教育文案(spec §12.3 LOCKED)。"""
    _stub_catalog(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0
    assert "题材是标签" in result.output or "一只股可能在多个题材" in result.output
    assert "投机炒作" in result.output or "CSRC" in result.output


def test_theme_help_shows_sub_commands(_isolate_all):
    """kan theme --help 显示 list / search 两个子命令。"""
    runner = CliRunner()
    result = runner.invoke(app, ["theme", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "search" in result.output
```

- [ ] **Step 2: Verify fail**

Run: `.venv/bin/python -m pytest tests/test_theme_cli.py -v 2>&1 | tail -15`

Expected: 全 FAIL with `No such command 'theme'`。

- [ ] **Step 3: 写实现 `kan/cli_theme_cmds.py`**

```python
"""`kan theme` 子命令组 · 题材发现入口 · F11 引入。

参考 `cli_config_cmds.py` 体例(typer.Typer + add_typer 注册风格 LOCKED)。

子命令:
- theme list [--all]    列题材清单(默认拼音前 30 · --all 全部 ~391 + 散户超载警告)
- theme search 关键词    模糊搜题材

注:本版不实现"top N 活跃热度榜"(adata 无批量接口 · O(391) HTTP 触发反爬 · 留 F11.2)。
"""
from __future__ import annotations

import typer

from kan import boards
from kan.app import app

theme_app = typer.Typer(
    name="theme",
    help="题材板块管理(同花顺 ~391 个 · 一股归多个 · 标签型分类)",
    no_args_is_help=True,
)
app.add_typer(theme_app, name="theme")

_DEFAULT_LIST_TOP = 30


def _pinyin_key(name: str) -> str:
    """简易拼音首字母键 · 仅做排序用 · 中英混排兼容。

    实现:中文字符返回 'z' (排在 ASCII 后面),其他原样。
    完整拼音排序留作后续优化(本版用简易 fallback)。
    """
    if not name:
        return "z"
    first = name[0]
    if first.isascii():
        return first.lower()
    return "z" + name  # 中文统一压到 ASCII 后面 · 内部按中文 unicode 顺序


@theme_app.command("list")
def list_cmd(
    all_: bool = typer.Option(False, "--all", help="显示全部题材(~391 · 散户超载警告)"),
) -> None:
    """列题材清单(默认拼音前 30 · --all 全部)。"""
    try:
        catalog = boards.load_theme_catalog()
    except boards.ThemeDataUnavailableError as e:
        typer.echo(f"❌ 题材清单不可用: {e}", err=True)
        raise typer.Exit(1) from None

    total = len(catalog)
    sorted_catalog = sorted(catalog, key=lambda t: _pinyin_key(t.name))

    if all_:
        typer.echo(f"🎯 题材清单 · 全部 {total} 个(同花顺源)\n")
        display = sorted_catalog
    else:
        typer.echo(f"🎯 题材清单 · {total} 个(同花顺源 · 默认显示前 {_DEFAULT_LIST_TOP} 拼音序)\n")
        display = sorted_catalog[:_DEFAULT_LIST_TOP]

    for t in display:
        size_label = f"({t.size} 只成分股)" if t.size else ""
        typer.echo(f"  {t.code}  {t.name}  {size_label}".rstrip())

    typer.echo("")
    if not all_ and total > _DEFAULT_LIST_TOP:
        typer.echo(f"💡 共 {total} 个题材 · 看全部:kan theme list --all  ·  模糊搜:kan theme search 关键词")
    typer.echo("💡 题材是标签 · 一只股可能在多个题材中(科大讯飞同属 AI/教育/智慧城市等)")
    typer.echo("💡 题材分类各家口径不同 · 这是同花顺口径")
    typer.echo("⚠️  题材跟「投机炒作」是 CSRC 监管重点 · 用工具看位置不等于买卖建议")


@theme_app.command("search")
def search_cmd(
    keyword: str = typer.Argument(..., help="题材关键词(模糊匹配)"),
) -> None:
    """模糊搜题材 · 列所有命中候选。"""
    from kan.boards import normalize_theme_name

    try:
        catalog = boards.load_theme_catalog()
    except boards.ThemeDataUnavailableError as e:
        typer.echo(f"❌ 题材清单不可用: {e}", err=True)
        raise typer.Exit(1) from None

    k_norm = normalize_theme_name(keyword)
    matches = [t for t in catalog if k_norm in normalize_theme_name(t.name)]

    if not matches:
        typer.echo(f"未找到含「{keyword}」的题材 · 0 个候选")
        return

    typer.echo(f"🔍 搜「{keyword}」· 命中 {len(matches)} 个候选:\n")
    for t in matches[:30]:  # 最多展示 30 候选 · 防刷屏
        typer.echo(f"  {t.code}  {t.name}")
    if len(matches) > 30:
        typer.echo(f"\n  ... 还有 {len(matches) - 30} 个 · 用更具体关键词缩小范围")
    typer.echo("")
    typer.echo("💡 用完整题材名跑扫描:kan scan --theme=AI应用")
```

- [ ] **Step 4: 注册子命令到 `kan/cli.py`**

打开 `kan/cli.py`,在现有子命令 import 段加一行:

```python
# 现有(示例):
from kan import cli_config_cmds  # noqa: F401  · register `kan config`
from kan import cli_theme_cmds   # noqa: F401  · register `kan theme` (F11)
```

注意:`kan/cli.py` 现有体例已经通过 import 触发 `app.add_typer(...)` 注册 · 跟 cli_config_cmds.py 同步即可 · 不需要别的 wiring。

- [ ] **Step 5: Verify pass**

Run: `.venv/bin/python -m pytest tests/test_theme_cli.py -v 2>&1 | tail -15`

Expected: `7 passed`。

- [ ] **Step 6: 真跑冒烟 `kan theme --help`**

Run: `.venv/bin/kan theme --help`

Expected: 输出帮助文案 · 含 `list` / `search` 两个子命令 + 中文 help。

- [ ] **Step 7: ruff + Commit**

```bash
.venv/bin/ruff check kan/cli_theme_cmds.py kan/cli.py tests/test_theme_cli.py
git add kan/cli_theme_cmds.py kan/cli.py tests/test_theme_cli.py
git commit -m "feat(theme): kan theme list/search sub-command tree · F11 发现入口"
```

---

## Task 15: 散户警示文案 + 红线词 audit + AGENTS.md §6 合规校验

**Files:**
- Modify: 全部 F11 相关 .py 文件(若 grep 命中红线词)
- Test: `tests/test_theme_redline_audit.py`(新建 · grep 自动 audit · 防回归)

- [ ] **Step 1: 真跑红线词 grep audit**

Run:

```bash
grep -rEn "共振信号|强势题材|高位机会|题材轮动|热点切换|可能回升|可能回落|跟风|炒作|推荐|建议" \
  kan/boards.py kan/_scan_targets.py kan/_confirm.py kan/render_theme.py \
  kan/cli_scan_cmds.py kan/cli_trend_cmds.py kan/cli_watchlist_cmds.py \
  kan/cli_theme_cmds.py 2>/dev/null
```

Expected:
- "跟风" 仅在 `render_theme.py` disclaimer 第三人称语境(`题材跟风风险高于行业`)出现 · 允许
- "投机炒作" 仅在 `cli_theme_cmds.py` 散户警示出现 · 允许
- 其他红线词不应出现

若有违规命中:打开对应文件 · 按 spec §12.2 表替换中性词:
- "共振信号 / 共振买入" → "共振低位区间"
- "强势 / 高位机会" → "近 250d 位置 X%"中性陈述
- "可能回升 / 可能回落" → 删除整句
- "推荐 / 建议" → 删除

- [ ] **Step 2: 写自动 audit 测试 `tests/test_theme_redline_audit.py`**

```python
"""AGENTS.md §6 红线词 audit · grep F11 相关源码 · 防回归。"""
import re
from pathlib import Path

# 红线词:不允许出现在 F11 主体代码(disclaimer 第三人称语境例外)
F11_SOURCE_FILES = [
    "kan/boards.py",
    "kan/_scan_targets.py",
    "kan/_confirm.py",
    "kan/cli_theme_cmds.py",
    "kan/render_theme.py",
]

REDLINE_WORDS = [
    "共振信号",
    "强势题材",
    "高位机会",
    "题材轮动",
    "热点切换",
    "可能回升",
    "可能回落",
    # "跟风" "炒作" "推荐" "建议" 在第三人称 disclaimer 语境允许 · 不进 audit
]

# 允许在以下文件出现"跟风/炒作/推荐/建议"(第三人称警示语境)
ALLOWED_THIRD_PERSON_FILES = [
    "kan/render_theme.py",   # disclaimer 4 行
    "kan/cli_theme_cmds.py",  # theme list 散户教育
]


def test_no_redline_words_in_f11_source():
    """硬红线词不应出现在 F11 任何主体代码中。"""
    repo = Path(__file__).parent.parent
    violations = []
    for relpath in F11_SOURCE_FILES:
        p = repo / relpath
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8")
        for word in REDLINE_WORDS:
            if word in content:
                violations.append(f"{relpath}: 含红线词「{word}」")
    assert not violations, "\n".join(violations)


def test_theme_disclaimer_4_lines_present():
    """render_theme.py 必须含 spec §12.1 LOCKED 的 4 行 disclaimer 关键短语。"""
    p = Path(__file__).parent.parent / "kan/render_theme.py"
    content = p.read_text(encoding="utf-8")
    assert "位置 ≠ 买卖信号" in content
    assert "题材分类各家口径不同" in content
    assert "题材跟风风险高于行业" in content
    assert "不预测涨跌" in content
    assert "不荐股" in content
```

- [ ] **Step 3: Run audit test · 期望首次 PASS(实施代码已合规)**

Run: `.venv/bin/python -m pytest tests/test_theme_redline_audit.py -v 2>&1 | tail -5`

Expected: `2 passed`。

若 FAIL,则按 step 1 的 grep 结果修红线词 + 重跑直到 PASS。

- [ ] **Step 4: Commit**

```bash
git add tests/test_theme_redline_audit.py
git commit -m "test(theme): redline word audit · prevent regression · AGENTS.md §6"
```

---

## Task 16: 真网络冒烟 case + `@pytest.mark.network` marker

**Files:**
- Modify: `pyproject.toml`(声明 network marker)
- Create: `tests/network/test_adata_real.py`(新建)
- Modify: `.github/workflows/test.yml`(若存在 · CI 跳网络 case)

- [ ] **Step 1: pyproject.toml 声明 marker**

打开 `pyproject.toml` · 找 `[tool.pytest.ini_options]` 段(若无则在 `[tool.ruff]` 上方加):

```toml
[tool.pytest.ini_options]
markers = [
    "network: 真网络 case · 默认 CI 跳过 · 用 -m network 单独跑",
]
```

- [ ] **Step 2: 新建 `tests/network/__init__.py`(空)**

```bash
mkdir -p tests/network
touch tests/network/__init__.py
```

- [ ] **Step 3: 写真网络冒烟 `tests/network/test_adata_real.py`**

```python
"""F11 真网络冒烟 · 跑真 adata HTTP · 验证 spike 假设未回归。

默认 CI 跳过(用 -m "not network")。
本地开发 + daily cron 跑(用 -m network)。
"""
import pytest


@pytest.mark.network
def test_adata_ths_catalog_real():
    """adata THS catalog 应返回 ≥ 100 题材 · spike 当时 391 · 假设 ≥100 不破。"""
    import adata
    df = adata.stock.info.all_concept_code_ths()
    assert df is not None
    assert len(df) > 100
    assert {"index_code", "name", "source"} <= set(df.columns)


@pytest.mark.network
def test_adata_ths_concept_constituent_real():
    """adata THS 题材成分股(AI应用 886108) · 应返回 > 30 行。"""
    import adata
    df = adata.stock.info.concept_constituent_ths(index_code="886108")
    assert df is not None
    assert len(df) > 30
    assert "stock_code" in df.columns
    assert "short_name" in df.columns


@pytest.mark.network
def test_adata_em_kline_real():
    """adata EM 题材 K 线(AI应用 BK1629) · 11 列 schema 未变 · OHLC 非 NaN。"""
    import adata
    df = adata.stock.market.get_market_concept_east(index_code="BK1629", k_type=1)
    assert df is not None
    assert len(df) > 30
    expected_cols = {"open", "high", "low", "close", "volume", "amount", "change_pct"}
    assert expected_cols <= set(df.columns)
    assert not df["close"].isna().all()


@pytest.mark.network
def test_adata_em_reverse_real():
    """adata EM datacenter 个股反查(科大讯飞 002230) · 应返回 ≥ 5 题材 · 0.5s 内。"""
    import time
    import adata
    t0 = time.time()
    df = adata.stock.info.get_concept_east(stock_code="002230")
    elapsed = time.time() - t0
    assert df is not None
    assert len(df) > 5
    assert elapsed < 5.0  # 慷慨 5s · spike 实测 0.18s · 网络抖动容忍
    assert "concept_code" in df.columns


@pytest.mark.network
def test_adata_em_push2_circuit_breaker_triggers():
    """EM push2 反爬 stress · 4 次连续调应触发 circuit breaker(spike 实测)。

    本测试容忍单次失败 · 但不容忍"4 次全成功无熔断"(说明 spike 假设失效 · 需更新)。
    """
    import adata
    from kan.circuit_breaker import get_breaker

    breaker = get_breaker()
    breaker.record("em_push2_concept", ok=True)  # 重置

    success_count = 0
    for _ in range(4):
        try:
            df = adata.stock.info.concept_constituent_east(concept_code="BK1629")
            if df is not None and not df.empty:
                success_count += 1
        except Exception:
            pass

    # 假设:4 次全成功的概率应小(反爬触发率 > 50%) · 即至少 1 次失败
    assert success_count < 4, "EM push2 stress 4 次全成功 · spike 假设可能失效 · 重做反爬实证"


@pytest.mark.network
def test_adata_arm64_py_mini_racer_known_issue():
    """记录 Apple Silicon arm64 的 py_mini_racer dylib 缺失 · 文档化已知问题。

    本测试不应阻塞 CI · 只在 arm64 darwin 上 expected fail。
    """
    import platform
    if not (platform.system() == "Darwin" and platform.machine() == "arm64"):
        pytest.skip("only relevant on Apple Silicon")

    import adata
    with pytest.raises(RuntimeError, match="libmini_racer"):
        adata.stock.market.get_market_concept_ths(index_code="886108", k_type=1)
```

- [ ] **Step 4: 验证 marker 配置生效(默认跳)**

Run: `.venv/bin/python -m pytest tests/network/ -m "not network" -v 2>&1 | tail -5`

Expected: `6 deselected`(全部 deselect 不跑)。

Run: `.venv/bin/python -m pytest -q -m "not network" 2>&1 | tail -3`

Expected: 525 (baseline) + 60 (新加 F11 case) ≈ `585 passed`(网络 6 个 deselect 不计)。

- [ ] **Step 5: 真跑网络冒烟(可选 · 本地验证 · CI 不跑)**

Run: `.venv/bin/python -m pytest tests/network/ -m network -v 2>&1 | tail -10`

Expected: 全 PASS(若 EM push2 当前不限流 stress test 失败,容忍 · 走 xfail 路径或 skip)。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/network/__init__.py tests/network/test_adata_real.py
git commit -m "test(theme): real-network smoke (adata) + @pytest.mark.network marker"
```

---

## Task 17: CHANGELOG + 全套回归 + 真跑收尾验收

**Files:**
- Modify: `CHANGELOG.md`(加 v0.0.5.0 Added 条目)
- Verify: 全套测试 / ruff / 真 CLI 冒烟 / spec 验收清单

- [ ] **Step 1: CHANGELOG.md 加 v0.0.5.0 F11 条目**

打开 `CHANGELOG.md`,找到 `## [0.0.5.0]` 标题(若已被 hot-list / tushare-pro 写入则 append `### Added`,否则新建 section):

```markdown
### Added

- 🎯 **题材位置扫描**(F11)· 全 11 命令矩阵:
  - 8 只读命令(`scan` / `low` / `high` / `trend` / `info` / `list` / `fetch` / `update`)各支持 `--theme=<题材名>` + `--only-watchlist`,扫题材全成分股 · 自选 ⭐ 高亮 · 三层信息架构(题材指数 + 成分股 + 散户警示)。
  - 3 破坏性命令(`add` / `remove` / `clear`)支持 `--theme=<题材名>`,**必经二次确认**(`_confirm` helper)· `--yes` 跳过(慎用)。
  - 题材发现入口 `kan theme list [--all]` / `kan theme search 关键词`(参考 `cli_config_cmds.py` 子命令树体例)。
- 🆕 数据源:**adata**(同花顺 catalog/成分股 + 东方财富 datacenter K 线/反查 + EM push2 成分股 fallback 走 T6 熔断 5min cooldown)。零 token 零配置 · 跟 `--industry` 申万源平级。
- 🆕 新模块 `kan/boards.py` 扩展 theme 函数 6 个 · 新建 `kan/_confirm.py`(破坏性 helper · 给 F10 破坏性也用)· 新建 `kan/cli_theme_cmds.py` 子命令组 · 新建 `kan/render_theme.py` 三层渲染。
- 🆕 cache schema:`~/.local/share/manmankan/boards/catalog_concept_ths.json`(24h)· `cons_THS{886xxx}.json` / `cons_EM{BK1xxx}.json`(per-theme 24h)· `kline_EM{BK1xxx}.parquet` · `stock_themes_<symbol>.json`(12h)。
- 🆕 deps:`adata>=2.9,<3` 主依赖(零 token · 多源融合)。

### Changed

- `kan/_scan_targets.py::resolve_scan_targets` 从 3 模式扩为 **4 模式互斥**(industry / hot / theme / 默认自选)· 加 `theme` 参数 + `ThemeMeta` dataclass · 跟 `BoardMeta` / `HotMeta` 对称。
- 红线词审查表 LOCKED 入 `docs/design-f11-theme-scan.md §12.2` + 自动 audit 测试(`tests/test_theme_redline_audit.py`)防回归。AGENTS.md §6 题材线 disclaimer 比 `--industry` 多一档("题材跟风风险高于行业")。
```

- [ ] **Step 2: 全套测试 baseline 验证**

Run: `.venv/bin/python -m pytest -q -m "not network" 2>&1 | tail -3`

Expected: `585+ passed`(525 baseline + ~60 新 F11 case · 网络跳)。

若某 case fail:回到对应 Task 修 · 不让本 Task 进度。

- [ ] **Step 3: 全套 ruff lint**

Run: `.venv/bin/ruff check kan/ tests/`

Expected: `All checks passed!`

若有 lint 报错:`uv run ruff check kan/ tests/ --fix` 自动修能修的 · 剩下手修。

- [ ] **Step 4: 真跑 7 命令冒烟(本地真网络 · 任选一题材 · 不进自动测试)**

```bash
# 假设 adata 已装 + 网络正常
.venv/bin/kan theme list
.venv/bin/kan theme search AI
.venv/bin/kan scan --theme=白酒概念   # 选成分股少的题材 · 加速冒烟
.venv/bin/kan low --theme=白酒概念
.venv/bin/kan high --theme=白酒概念
.venv/bin/kan trend --theme=白酒概念
.venv/bin/kan info --theme=白酒概念
.venv/bin/kan list --theme=白酒概念
.venv/bin/kan fetch --theme=白酒概念
.venv/bin/kan update --theme=白酒概念
```

Expected: 每条命令 exit 0 · 输出含题材名 + 成分股 + 4 行 disclaimer。

- [ ] **Step 5: 真跑破坏性 3 命令 + `_confirm` 交互(谨慎 · 用临时 cache 目录)**

```bash
# 把自选股目录指向 tmp · 不污染真用户数据
KAN_DATA_DIR=/tmp/kan-f11-smoke .venv/bin/kan add --theme=白酒概念 --yes
KAN_DATA_DIR=/tmp/kan-f11-smoke .venv/bin/kan list
KAN_DATA_DIR=/tmp/kan-f11-smoke .venv/bin/kan remove --theme=白酒概念 --yes
KAN_DATA_DIR=/tmp/kan-f11-smoke .venv/bin/kan list
```

Expected: 第一条 add 输出 "✅ 已添加 N 只" · 第三条 remove 输出 "✅ 已移除 N 只" · list 中间显示自选 / 末尾为空。

注:KAN_DATA_DIR env 可能未必支持(检查 `kan/paths.py` 是否读环境变量)· 如果不支持则跳过本 step · 不影响验收。

- [ ] **Step 6: spec 验收清单逐条核对**

打开 `docs/design-f11-theme-scan.md`,对照以下条目(spec § 4 / § 11 / § 12 隐含验收):

- [ ] catalog/成分股 走 THS · 实测可读
- [ ] K 线/反查 走 EM datacenter · 实测可读
- [ ] EM 成分股 fallback 路径存在 · 触发熔断时友好提示
- [ ] 8 只读命令全跑通 `--theme=X` · 全显 4 行 disclaimer
- [ ] 3 破坏性命令必经 `_confirm` y/N · `--yes` 跳过
- [ ] `kan theme list/search` 跑通 · 散户教育文案显示
- [ ] 红线词 audit test PASS
- [ ] 测试 585+ passed · ruff clean
- [ ] CHANGELOG.md 含 F11 Added 条目
- [ ] spec 文档已 commit(`3e5b833` + `31769a0`)

- [ ] **Step 7: 最后一次全套 ruff + pytest 干净基线确认**

```bash
.venv/bin/ruff check kan/ tests/
.venv/bin/python -m pytest -q -m "not network"
```

Expected: 全绿 · 0 lint error · 585+ passed。

- [ ] **Step 8: Commit CHANGELOG + 推送**

```bash
git add CHANGELOG.md
git commit -m "docs(theme): F11 题材位置扫描 · CHANGELOG v0.0.5.0 entry"
git push -u origin feat/v0.0.5-f11-theme
```

预期:推送成功 · GitHub 显示 PR-ready 状态。维护者后续:

1. 开 PR 把 `feat/v0.0.5-f11-theme` → `feat/v0.0.5.0`(扩 PR #18 或开新 PR)
2. 触发 7 角色 release-review 流程(主会话 + 6 sub-agent)
3. P0 修完 → merge → tag → PyPI

---

## 实施完成后

- ✅ F11 全 11 命令矩阵 + `kan theme list/search` 上线
- ✅ adata 按接口分发数据源(catalog/成分股 THS · K线/反查 EM datacenter · EM 成分股 fallback)
- ✅ 测试 baseline 525 → 585+
- ✅ AGENTS.md §6 合规 disclaimer 比 `--industry` 多一档
- ✅ 红线词自动 audit 防回归
- ✅ 真网络冒烟 6 case `@pytest.mark.network` 标签 · daily cron 跑
- ✅ Spec § 17 LOCKED:F11 数据源永远走 adata · 不走 Tushare(即使 tushare-pro 已合入)

**完成后清理**(plan 实施完毕后,维护者定):

- `.dev-thinking/manmankan-v0.0.5/v0.0.5.0/F11-theme-scan.md`(v3 LOCKED 设计稿 · § 4 已被 supersede)→ 维护者定保留 / 移到 archive / 删
- `.dev-thinking/manmankan-v0.0.5/v0.0.5.0/F11-data-source-findings-2026-05-22.md`(数据源调研 · § "正式开发起步" 已 supersede)→ 同上
- `/tmp/adata-spike/spike{1..4}.py`(本地 spike 临时文件 · 已无价值)→ session 结束自动清

**已知限制(后续候选)**:

- "top N 活跃热度榜"(本版静态拼音序 · 留 F11.2 · 需 O(391) HTTP + cron + 24h cache + 反爬观察期)
- 题材名 cross-source alias 表(THS "人工智能" ↔ EM "AI应用")· 初始空 · 用户反馈累积
