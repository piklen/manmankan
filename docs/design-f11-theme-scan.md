# 题材位置扫描功能 · 设计方案

> 状态:已实施(v0.0.5.0)
> 创建:2026-05-23 · 5 节 brainstorming 全 approved
> 分支:`feat/v0.0.5-f11-theme`(从 `feat/v0.0.5.0` fork · `.worktrees/feat-v0.0.5-f11-theme` 隔离开发)
> 目标版本:v0.0.5.0(PR #18 扩容 · 跟 hot-list / 行业扫描 同批发版)
> 工时估算:12-17h

## 1. 背景与目标

`kan` 已支持三种扫描标的来源:自选股(默认)、申万行业成分股(`--industry`)、东方财富热榜(`--hot`)。本功能新增第四种:**题材成分股**(`--theme`)。

**题材 ≠ 行业**:行业是申万官方层级分类(一只股归一个 + 有官方成分股注册表);题材是行情商标签型分类(一只股归多个 + 无官方注册 + 各家口径不同)。茅台实测在东财归 ~5 个题材,在同花顺归 6 个题材;科大讯飞同属"AI 应用 / 教育 / 智慧城市"等 ~45 个题材。

散户日常说"AI 应用 / 光伏 / 华为概念 / 数据要素"等 —— **没有学术标准**,各家(同花顺 ~391 个 / 东方财富 ~486 个)各自维护。题材跟"投机炒作"距离近 → 合规风险高于行业 → disclaimer 必须比 `--industry` 更强一档(AGENTS.md §6)。

## 2. 非目标(明确不做)

- **题材活跃榜 / top N 热度排序**:adata 无"批量题材实时榜"接口,实现需 O(391) HTTP 调用 + 24h cache + cron,触发反爬风险大于价值。`kan theme list` 本版用静态拼音序;真活跃榜留作后续候选。
- **付费数据源(Tushare 6000 积分 / Wind / iFinD)**:`adata` 实证免费可解,且保留 manmankan"零配置体验" → 不引入 per-user token 数据源。
- **`kan theme info BK1184`(单题材详情)**:跟个股 `kan info` 语义重叠 · 边际价值低 · 不加。
- **题材成分股动态调整自动追踪**:成分股每日有小调整 · cache TTL 24h 内不刷新 · 用户主动 `--force` 才重拉。
- **AI 选股 / 题材推荐 / 热点信号订阅**:AGENTS.md §6 红线明文不做。

## 3. 命令范围(已实施矩阵)

| 类 | 命令 | `--theme` 加载语义 |
|---|---|---|
| 只读 / 数据 (7) | `scan` `low` `high` `trend` `info` `list` `fetch` | 扫指定题材全成分股或自选交集 · 跟 `--industry` 对称 |
| 破坏性 (2) | `add` `remove` | 批量增删自选 · **必经 `_confirm` 二次确认** · `--yes` 跳过 |
| 发现入口 (新 sub-app) | `kan theme list` `kan theme search` | 列题材清单 / 模糊搜 · 跟 `kan watchlist` 子命令树对齐 |

约束:

- `--theme` 与 `--industry` / `--hot` 互斥 → `❌ --industry / --hot / --theme 三者互斥 · 同时只能用一个`,exit 2。
- `--theme` 与显式股票代码互斥(沿用 `fetch --industry` 已有校验)。
- `--only-watchlist` 对 `scan` / `low` / `high` / `trend` / `fetch --theme` 生效:targets = 成分股 ∩ 自选,全部 ⭐。
- `compare` 仍只接受显式股票代码;`clear` 仍只做清空全部自选;`update` 仍只做包升级,三者本版不接 `--theme`。

## 4. 数据源:adata 按接口分发

### 4.1 调研推翻的旧假设

早期方案设想"默认 THS · fallback EM 对称双源"。两轮数据源调研推翻此假设:

- **2026-05-22 akshare 直拉调研**:同花顺 akshare 1.18.60 **无题材成分股接口** · 东财 `stock_board_concept_cons_em` **连接级拒绝** · 富途返回非 JSON · 题材成分股 API 全死。
- **2026-05-23 adata 真网络调研**:adata 解决核心阻塞,但 **不是"源对源对称"** 而是 **"接口可用性分层"** —— 同一根域名下不同子域名 / 不同端点 反爬粒度不同。

### 4.2 数据源映射

| 接口 | adata 调用 | 实际端点 | 状态 | 选用理由 |
|---|---|---|---|---|
| catalog | `info.all_concept_code_ths()` | THS HTTP | ✅ 391 题材 · 3.74s | 稳定 |
| 题材成分股 | `info.concept_constituent_ths(index_code=)` | THS HTTP | ✅ ~100 行/题材 · 2s | 稳定 |
| 个股 → 题材 反查 | `info.get_concept_east(stock_code=)` | `datacenter.eastmoney.com` | ✅ 0.18s | 稳定 · 不在反爬端点 |
| 题材 K 线 | `market.get_market_concept_east(index_code=)` | EM HTTP | ✅ OHLC 11 列 · 0.32s | 稳定 · 避开 THS `py_mini_racer` V8 引擎(arm64 dylib 不兼容) |
| EM 成分股(fallback) | `info.concept_constituent_east(concept_code=)` | `push2.eastmoney.com` | ⚠️ 首 1-2 次通 · stress 后 ConnectionError | 反爬触发 · 走 T6 熔断器 5min cooldown |

### 4.3 关键工程含义

- **没有"主源 / 备源"** · 4 个接口各选最稳源 · 调用时根据接口类型分发。
- THS K 线被排除:不是 THS 不能用,而是 `py_mini_racer` 在 Apple Silicon arm64 没有预编译 dylib,真实开发机不可用。EM K 线避开此问题。
- EM 成分股仅作 fallback:`get_theme_constituents` 优先调 THS · THS 失败 → 检查 T6 熔断器 EM 是否冷却中 · 否则尝试 EM · EM 失败标记 down 5min。
- `adata` 进主 deps(`pyproject.toml` 加 `adata>=2.9.0,<3` · `<3` cap 防 major breaking)· 不做 optional-extras(违反零配置承诺)。

## 5. 数据模块 `kan/boards.py` 扩展

### 5.1 数据结构

新增 `Theme(BaseModel)` 到 `kan/models.py`:

```python
class Theme(BaseModel):
    code: str          # THS index_code (886108) | EM concept_code (BK1629)
    name: str          # "AI应用" / "白酒概念"
    source: str        # "ths" | "em"
    size: int | None   # 成分股数 · catalog 接口未必提供
```

**Theme 不复用 Board**:`Board` 有 `level` 无 `source`,`Theme` 有 `source` 无 `level`。两个独立模型在 manmankan 规模下比加 `kind: industry|theme` discriminator 简单(避免调用方 if/else)。

### 5.2 异常

- `ThemeNotFoundError`:`search_theme` / 题材代码不存在。
- `ThemeDataUnavailableError`:adata THS+EM 题材数据全挂(双源都失败才抛)。

### 5.3 接口(沿 F10a 风格 · 跟 industry 函数对称)

| 函数 | 行为 |
|---|---|
| `load_theme_catalog(force: bool = False) -> list[Theme]` | 调 `adata.stock.info.all_concept_code_ths()` · JSON cache `boards/catalog_concept_ths.json` 24h TTL · 失败退化到陈旧 cache(warn 提示) |
| `search_theme(query: str) -> Theme` | 模糊匹配 · 多命中给候选列表 · 跟 `search_industry` 风格一致 |
| `get_theme_constituents(theme: Theme, force: bool = False) -> list[tuple[str, str]]` | THS 优先 → T6 熔断器检查 EM 是否冷却 → EM fallback · per-theme JSON cache 24h TTL |
| `fetch_theme_kline(theme: Theme, force: bool = False) -> pd.DataFrame` | `adata.stock.market.get_market_concept_east` · rename 11 列为标准 7 列 (`date/open/high/low/close/volume/amount`) · parquet cache |
| `get_themes_of_stock(stock_code: str) -> list[Theme]` | `adata.stock.info.get_concept_east` · 12h cache(短于题材数据 · 因公司频繁变题材归属) |
| `normalize_theme_name(name: str) -> str` | "AI 应用 / AI应用 / AI智能应用" → 规范化 · 用于 THS↔EM fallback 时名字对齐 |

### 5.4 缓存 schema

```
~/.local/share/manmankan/boards/                    (F10a 已建 BOARDS_DIR)
├── catalog_sw.json                  (F10a · 行业)
├── catalog_concept_ths.json         (新 · 题材 catalog · 24h)
├── catalog_concept_em.json          (新 · EM 备查 · 24h · adata catalog bug workaround:从 get_concept_east 反查累积)
├── cons_THS886108.json              (新 · 题材成分股 · per-theme · 24h)
├── cons_EMBK1629.json               (新 · EM fallback 缓存 · 24h)
├── kline_EMBK1629.parquet           (新 · 题材指数 K · 跟个股 K 同 schema · 24h)
└── stock_themes_002230.json         (新 · 个股反查 · per-stock · 12h)
```

文件名前缀区分源(`THS` / `EM`),F10a `catalog_sw.json` 不动。

### 5.5 T6 熔断器复用

复用 `kan/circuit_breaker.py`(F10a/T6 已建跨进程持久化 `circuit.json`)· 加新源 ID `em_push2_concept`(粒度按 URL path · 不按"逻辑源" · 因 EM datacenter 跟 EM push2 反爬不连坐):

```python
if is_down("em_push2_concept"):
    raise ThemeDataUnavailableError("EM 成分股反爬冷却中 · 5min 后再试")
try:
    return adata.stock.info.concept_constituent_east(concept_code=code)
except (ConnectionError, RemoteDisconnected) as e:
    mark_down("em_push2_concept")
    raise ThemeDataUnavailableError(f"EM 反爬触发 · {e}")
```

### 5.6 退化策略

| 场景 | 退化 |
|---|---|
| THS catalog 失败 + cache 陈旧 | 用陈旧 cache + warn "题材数据已过期" + 继续跑 |
| THS 成分股失败 → EM 也失败 / cooldown | 抛 `ThemeDataUnavailableError` · CLI 提示"题材功能暂不可用 · 行业扫描可用" |
| 题材 K 线 EM 失败 | 三层架构降级:不显示题材指数行 + 只显示成分股表 + warn |
| 新概念历史 < 250d | 多周期列 250d / 120d 显示 "—" · 不报错 · dim 提示"该题材成立 X 天" |
| THS / EM 名字不一致 | `normalize_theme_name` + alias 表(初始小 · 用户反馈累积) |

## 6. `resolve_scan_targets` 改动 + ThemeMeta

`_scan_targets.py` 加 `theme` 参数 + `ThemeMeta` dataclass:

```python
@dataclass
class ThemeMeta:
    theme: Theme
    index_kline: pd.DataFrame              # EM 题材指数 K(已 rename)
    constituents: list[tuple[str, str]]    # 全成分股(THS)
    highlight: set[str]                    # 成分股 ∩ 自选
    source_dispatch: dict[str, str]        # 调试用:{"catalog":"ths","cons":"ths","kline":"em","reverse":"em"}

def resolve_scan_targets(
    industry: str | None,
    only_watchlist: bool,
    watchlist_pairs: list[tuple[str, str]],
    hot: HotList | None = None,
    theme: str | None = None,                         # 新
) -> tuple[list[tuple[str, str]], BoardMeta | HotMeta | ThemeMeta | None]:
    # 三模式互斥:industry / hot / theme 同时只能给一个
    given = sum(1 for x in (industry, hot, theme) if x is not None)
    if given > 1:
        raise ValueError("--industry / --hot / --theme 不能同时指定")
    # ... theme 分支 ...
```

返回类型 `BoardMeta | HotMeta | ThemeMeta | None`。命令层 isinstance 分流到题材渲染。

## 7. CLI 层命令接入

每条命令加 1 个 typer.Option:

```python
theme: Annotated[
    str | None,
    typer.Option("--theme", help="扫指定题材全成分股 · 自选 ⭐ 高亮 · 题材 ≠ 行业,一股归多个"),
] = None,
```

互斥校验(三方互斥)+ 调 `resolve_scan_targets(theme=theme, ...)` + 渲染分流。

文件改动:

| 文件 | 改动 | 行数 |
|---|---|---|
| `kan/cli_scan_cmds.py` | scan 加 `--theme` 接入 | ~150 |
| `kan/cli_extreme_cmds.py` | low / high 加 `--theme` 接入 | ~80 |
| `kan/cli_info_cmds.py` | info 加 `--theme` 接入 | ~80 |
| `kan/cli_fetch_cmds.py` | fetch 加 `--theme` 接入 | ~40 |
| `kan/cli_trend_cmds.py` | trend 加 `--theme` | ~30 |
| `kan/cli_watchlist_cmds.py` | add / remove / list 加 `--theme` + 破坏性接 `_confirm` | ~80 |
| `kan/_scan_targets.py` | 加 theme 分支 + ThemeMeta | ~30 |
| `kan/cli_theme_cmds.py` | 新建 · theme list / search | ~180 |
| `kan/_confirm.py` | 新建 · 破坏性 helper | ~80 |
| `kan/boards.py` | 扩 6 个 theme 函数 | ~250 |
| `kan/models.py` | 加 Theme | ~10 |

## 8. `kan theme` 子命令树(新建 `cli_theme_cmds.py`)

```
$ kan theme --help
Usage: kan theme COMMAND [ARGS]

  题材板块管理(同花顺 ~391 个 · 一股归多个 · 标签型分类)

Commands:
  list    列题材清单(默认拼音前 30 · --all 全部)
  search  按关键词搜题材(模糊匹配)
```

`kan theme list` 默认前 30 拼音序;`--all` 显示全 ~391 个 + 散户超载警告。`kan theme search 关键词` 模糊匹配 + 候选列表。

注:本版**不实现** "top N 活跃热度榜"(adata 无批量接口 · O(391) HTTP 触发反爬 · 留作后续候选)。

## 9. 破坏性 3 命令 + `_confirm.py`

新建 `kan/_confirm.py`(~80 行):

```python
def show_summary_and_confirm(
    action: str,                          # "add" | "remove" | "clear"
    targets: list[tuple[str, str]],
    current_watchlist_size: int,
    skip: bool = False,                   # --yes 传 True
) -> bool:
    """渲染影响 summary + interactive y/N · `--yes` 跳过返回 True。
    
    输出示例(add --theme=AI应用 · 自选当前 169 只):
        将 add 101 只股票到自选(操作后 256 只 · 已在自选 14 只跳过):
          ⭐ 002230 科大讯飞(已在自选 · 跳过)
             300033 同花顺
             ... (101 只)
        继续? [y/N]:
    """
```

破坏性 2 命令 `kan add/remove --theme=X` 必经此 helper · `--yes` 才跳过。

设计参考 ADR-0010 backup 协议精神(破坏性操作前出 summary + 确认)。`_confirm.py` 后续也给 F10-破坏性 3 命令(`--industry`)用,职责通用。

## 10. 渲染:三层信息架构

```
$ kan scan --theme=AI应用

🎯 AI应用 · 同花顺概念 · 886108
══════════════════════════════════════════════════════════════════
📊 题材指数        │ 30d   60d   120d  250d │ 共振低位
AI应用(同花顺)    │ 82%   78%   85%   88%  │ —

📈 成分股(101 只 · ⭐ 标记你的自选 · 数据 EM)
代码       名称        30d   60d   120d  250d  涨跌幅
⭐ 002230  科大讯飞    72%   68%   78%   85%   +2.1%
   300033  同花顺      88%   82%   90%   91%   +3.4%
   ... (101 只)

💡 数据源:同花顺 catalog/成分股 · 东方财富 K 线/反查
⚠️ 位置 ≠ 买卖信号  ·  共振低位区间 ≠ 买入建议
⚠️ 题材分类各家口径不同 · 同名题材成分股可能差异  ·  题材跟风风险高于行业
ℹ️ manmankan 是观察工具 · 不预测涨跌 · 不荐股
```

三层:**题材指数 1 行 metadata** + **成分股 N 行表格 ⭐ 高亮** + **散户警示 4 行强 disclaimer**。

`--only-watchlist` 跑同样三层,但成分股表过滤为 ∩ 自选。

`kan info --theme=AI应用` 输出题材深度档案(题材描述 + 全成分股清单 + K 速览)。

## 11. 错误处理

| 场景 | 提示 | exit |
|---|---|---|
| 题材名找不到 | `❌ 未找到题材「X」· 试更短关键词(如「AI」「华为」)· 或跑 kan theme search X 看候选` | 2 |
| search 多命中 | 列 ≤8 候选 · "用完整名 kan scan --theme=AI应用" | 0 |
| THS catalog 失败 + 无 cache | `❌ 题材清单首次拉取失败 · 检查网络后重试 · 行业扫描可用(--industry)` | 1 |
| 成分股 THS+EM 都失败 | `❌ 题材数据源完全不可用(已知会偶发) · 稍后重试 · 行业扫描可用` | 1 |
| 题材 K 线失败 | warn "题材指数 K 暂不可用" + 仍渲染成分股表 | 0 |
| 新概念 < 250d | 多周期列显 "—" + dim "该题材成立 X 天" | 0 |
| 用户 add --theme 输 n | `已取消 · 自选股未变` | 0 |

## 12. 合规(AGENTS.md §6)

### 12.1 强 disclaimer(每次 `--theme` 输出底部 4 行 · 不省)

```
💡 数据源:同花顺 catalog/成分股 · 东方财富 K 线/反查
⚠️ 位置 ≠ 买卖信号  ·  共振低位区间 ≠ 买入建议
⚠️ 题材分类各家口径不同 · 同名题材成分股可能差异  ·  题材跟风风险高于行业
ℹ️ manmankan 是观察工具 · 不预测涨跌 · 不荐股
```

题材线 disclaimer 比 `--industry` 多一档 —— "题材跟风风险高于行业" 是 F11 独有警示。

### 12.2 红线词审查(实施时 grep)

| 不允许 | 替换 |
|---|---|
| "共振信号 / 共振买入" | "共振低位区间"(F10a LOCKED) |
| "强势题材 / 高位机会" | "近 250d 位置 X%" 中性陈述 |
| "题材轮动 / 热点切换" | "近 N 日涨跌幅" 中性数据 |
| "可能回升 / 可能回落" | 移除(v0.0.4.8 P0-4 LOCKED) |
| "跟风 / 炒作" | 仅在散户警示**第三人称语境**用 |
| "推荐 / 建议" | 移除 |

### 12.3 `kan theme list` 输出散户教育

```
💡 题材是标签 · 一只股可能在多个题材中(科大讯飞同属 AI/教育/智慧城市等)
💡 题材分类各家口径不同 · 这是同花顺口径
⚠️ 题材跟"投机炒作"是 CSRC 监管重点 · 用工具看位置不等于买卖建议
```

## 13. 测试

三层金字塔:

| 层 | 数量 | 工具 |
|---|---|---|
| unit | ~25 | pytest + `fake_adata` fixture mock |
| integration (CliRunner) | ~30 | typer.testing.CliRunner · 9 个 `--theme` 命令真跑 · `_confirm` y/N 交互 · `--yes` skip |
| 真网络冒烟 | ~6 | 真 adata HTTP · `@pytest.mark.network` 默认跳 · daily cron 跑 |

### 13.1 `fake_adata` fixture

测试 stub 必须返回接近真实接口的字段结构,避免只用空 DataFrame 测过但生产字段变化时崩溃。

### 13.2 真网络 case(可单独跳)

```python
@pytest.mark.network
def test_adata_ths_catalog_real_world(): ...    # catalog 不少于 100 题材
@pytest.mark.network
def test_adata_em_push2_circuit_break_real(): ... # stress 触发反爬 + 熔断器 down
@pytest.mark.network
def test_adata_em_kline_real_world(): ...        # 11 列 schema 未变 · OHLC 非 NaN
```

### 13.3 CI 集成

`.github/workflows/test.yml`(F10a 已建)扩 marker 跳过:

```yaml
- name: Test (offline · default)
  run: uv run pytest -q -m "not network"
- name: Test (network smoke · daily cron · 容忍偶发失败)
  if: github.event_name == 'schedule'
  run: uv run pytest -q -m network
```

### 13.4 目标

- 基线:525 passed(feat/v0.0.5.0 合入 TuShare Pro 后)
- 目标:**585+ passed**(525 + ~60 新 case · 网络 6 跳过)
- 覆盖:`boards.py` theme 部分 ≥ 60% · `cli_theme_cmds.py` ≥ 60% · `_confirm.py` ≥ 70%

## 14. 风险与待验证

- ⚠️ **EM push2 反爬频次阈值未实证**:2026-05-23 stress 4 次 3 次挂,但用户日常使用频次 < stress · 触发率待生产观察。熔断器 5min cooldown 是经验值。
- ⚠️ **adata 包升级 breaking**:2.9.5 实测,deps cap `<3` 防 major · 但 2.x 内 minor 升级仍可能改 schema · 实施时实测目标版本。
- ⚠️ **题材名 alias 表初始空**:`normalize_theme_name` 第一版只做"去空格 + 小写",alias 表(如 THS "人工智能" ↔ EM "AI应用")随用户反馈累积。
- ⚠️ **新概念 < 250d 实测**:2024-2025 新增的"算力租赁 / Sora / 商业航天 / 数据要素" 实施时全量真跑测多周期退化。
- ⚠️ **依赖合并风险**:`adata` 与主线依赖更新同时改 `pyproject.toml` / `uv.lock` 时,发布分支必须在合并前重跑 `uv sync` / `uv build`。
- ⚠️ **rate-limit 在并发扫描下影响放大**:`kan scan --theme=X` 跑 101 只成分股 K 线时,如果走 EM datacenter 是反查接口(0.18s × 101 ≈ 20s),不会触发 push2 反爬;但若误触 push2 路径,反爬会连锁。实施时 strict 接口分发。

## 15. 数据源调研摘要

本版数据源选择来自 2026-05-22/23 的真网络调研:

- akshare 当时没有可稳定使用的同花顺题材成分股接口,东财题材成分股接口存在连接级失败。
- adata 的同花顺 catalog/成分股接口可满足题材清单和成分股需求。
- adata 的东方财富 datacenter K 线/反查接口比 push2 成分股接口稳定,因此本版按接口可用性分发,不是按站点做对称 fallback。

## 16. 跟 `tushare-pro` 集成的边界(已合入版)

tushare-pro 数据源接入已进入 v0.0.5.0 发布分支。F11 跟 tushare-pro 的关系是"同版发布,数据通路正交":

### 16.1 工程隔离点

- **依赖边界**:tushare-pro 走自写 HTTP client(`kan/tushare_pro.py` · 不依赖 `tushare` Python 包)· F11 加 `adata>=2.9,<3`。
- **`fetcher.py` 改 +12 行**:仅在 K 线获取链路插入 Tushare Pro 作 top-priority 源 · F11 题材数据通路不经过 `fetcher.py`(题材数据走 `boards.py` 独立链路 + adata)· 正交。
- **`kan/config.py` + `kan config` 子命令组**:tushare-pro 引入 per-user token 配置基建(`kan config get/set/unset tushare-token`)· F11 不需要 per-user 配置(adata 零 token)· 不复用。
- **测试**:tushare-pro 测试套件 +455 行不动 · F11 测试新增独立模块 `tests/test_boards_theme.py` / `tests/test_cli_theme_cmds.py` / `tests/test_confirm_destructive.py` · 互不干扰。

### 16.2 保留约束

- **F11 数据源永远走 adata · 不走 Tushare**:即使用户配了 tushare token,F11 题材调用仍走 adata · 跟 fetcher 数据源策略解耦 · 因 Tushare 题材接口(`dc_member` / `ths_member`)需 6000 积分(~¥600/年)· 破坏零配置承诺。
- **不复用 `kan config`**:F11 不引入新 config key · 不在 `kan/config.py` 加字段 · 跟 tushare-pro 的 config 范式解耦。

### 16.3 子命令树风格对齐

tushare-pro 加 `kan config <get|set|unset>` · F11 加 `kan theme <list|search>` —— 两个子命令树同为 typer.Typer 注册风格 · 实施时参考 `kan/cli_config_cmds.py` 体例写 `kan/cli_theme_cmds.py`,保持命令组注册 / 帮助文案 / 退出码 一致。

## 17. 版本与发布

- 目标版本 **v0.0.5.0**,与热榜扫描 / TuShare Pro / 导出格式 同批发布。
- `CHANGELOG.md` 记录用户可见能力;`roadmap.md` 保持候选功能视角。
- 发版前必须重跑离线测试、隐私/版本自检、TTY 入口测试和 `uv build`。
