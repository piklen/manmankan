# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.4.1] - 2026-05-12

### Fixed · 覆盖剩余命令

- `kan fetch` / `kan low` / `kan high` / `kan info` / `kan trend` 在加载
  `fetcher` / `scanner` / `render` 等数据模块前先显示 stderr spinner。
- `tests/test_cli_silent_period.py` 的 PTY 真终端测试扩展覆盖 `fetch` / `low` /
  `high` / `info` / `trend` 首帧 SLO。

## [0.0.4.0] - 2026-05-12

### Fixed · scan 启动 silent 期

- `kan/fetcher.py` 移除顶层 `akshare` / `pandas` import，改为数据源函数和
  parquet 读写函数内部 lazy import。
- 新增 `_with_heavy_imports_spinner(console, message)`，统一在重模块 import 前打开
  `console.status(..., spinner="dots")`。
- `kan scan` 入口用 stderr spinner 包住 `fetcher` / `scanner` / `render` import，
  冷启动首帧从约 500-700ms 降到 200ms 内。

### Docs

- 新增 `docs/reviews/v0.0.3.md` 记录 v0.0.3 silent 期审计和漏修原因。

## [0.0.3] - 2026-05-11

### Changed · 内部重构（零行为变更）

`kan/cli.py` **1512 → 44 行**八文件拆分，业务逻辑切到独立子模块：

- `kan/app.py`: `typer.Typer` 单例 + version / main callback（避免循环 import）
- `kan/cli_helpers.py`: 12 个共享 helper（错误脱敏 / 网络异常友好化 / 进度反馈 /
  argv normalize / shell 检测 / install 检测 / watchlist 加载 / auto fetch）
- `kan/cli_watchlist_cmds.py`: `help` / `add` / `remove` / `list` / `import` / `clear`
- `kan/cli_scan_cmds.py`: `fetch` / `scan` / `low` / `high` / `info`
- `kan/cli_trend_cmds.py`: `trend`
- `kan/cli_meta_cmds.py`: `update` / `uninstall` / `completion`
- `kan/cli_atexit.py`: 自动补全 + 自动更新 atexit hooks
- `kan/cli.py`: 极薄 entry · `cli_main` + 末尾 import 触发 `@app.command` 注册

共享 helper `_auto_fetch_stale` / `_get_watchlist_pairs` 被 5 个命令组（scan / trend /
low / high / info）复用，挪到 `cli_helpers.py` 让命令组之间 **0 耦合**。

### Added · 测试守护

- `tests/test_cli_registration.py`: import-side-effect canary（命令数 + 命令名
  集合断言 · 锁定 15 命令）· 任何子模块漏 import 立刻红
- pytest 全套从 207 → **209**

### Fixed · CI Lint

- 5 类 7 处 ruff lint 一并清掉（SIM105 `contextlib.suppress` 替代 try/except pass ·
  RUF100 / I001 / RUF059）
- 顺手清 `kan/updater.py` SIM105（pre-existing on main · 熵减）

### Docs

- 删除过时的 `docs/publish-v0.0.2.md` 本地 publish runbook（v0.0.2 实际已通过
  tag-trigger workflow 自动 publish）
- 新增 `docs/publish-template.md`: Trusted Publisher OIDC + tag-trigger 工作流
  标准 checklist · 每次发版照此走

## [0.0.2] - 2026-05-11

### Performance · 冷启动延迟修复

**根因（v0.0.1 实测）**：`kan/watchlist.py` 顶层 `import akshare as ak` 把
pandas / numpy / bs4 / requests 整窝拖入启动路径。单个 akshare import
占 watchlist 模块加载成本 85%（热启动 229ms / 冷启动约 8s）。
用户视角：按回车后 silent ~10s 才看到 ⏳ 加载提示。

**修复**：
- `akshare` 改 lazy import（仅在 baostock 主路径失败 fallback 时才付 import 成本）
- 新增 `kan.paths.is_stock_names_cache_fresh()` + `NAMES_CACHE_MAX_AGE_DAYS`，
  让 CLI 在 import 重模块前用极轻 paths（~370μs）先决策
- `kan/cli.py` 抽 `_load_names_with_optional_spinner` helper，
  spinner 提前到 watchlist 重模块 import 之前显示
- `kan add` 用户视角：按回车后 0 silent 期 · ⏳ 加载提示立即可见

**实测收益**（首次添加股票场景）：
- 冷启动 silent 期 ~10s → 0s（spinner 立即可见）
- baostock 主路径不再触发 pandas / numpy / bs4 / requests 等间接依赖

### Added · 自动更新机制

**核心**：
- `kan update` 命令 · 检查并升级到最新版本（`-y` 跳过 confirm · `--check` 仅查不升）
- 启动 atexit hook 自动检查（主命令完成后才查 · 不阻塞主流程）
- 首次发现新版本 prompt y/n/skip 询问偏好 · 偏好持久化 `~/.local/share/kan/config.json`

**5 个交互场景**：
- 首次发现新版 + TTY → prompt 询问 auto_update 偏好
- 选 y → 后续自动调对应包管理器 upgrade
- 选 n → 每周限流 hint + `kan update` 命令引导
- 网络失败 / PyPI 不可达 → 静默跳过 · 不破坏主命令
- 非 TTY / `KAN_NO_UPDATE_CHECK=1` → 完全静默

**安装方式自动检测**：通过 `sys.executable` 路径模式判 uv tool / pipx / pip venv

**性能 + 隐私**：daily cache（同一天再启动跳过 PyPI 请求）· 3s timeout · 失败静默

### Internal
- `kan/paths.py`：`is_stock_names_cache_fresh()` + `NAMES_CACHE_MAX_AGE_DAYS` 常量
- `kan/watchlist.py`：移除顶层 `import akshare as ak` · 保留 re-export 兼容
- `kan/config.py`（新）· schema 持久化 + 损坏自愈 + atomic write
- `kan/updater.py`（新）· PyPI 查询 + 包管理器派发 + 版本对比
- `kan/cli.py`：抽 `_load_names_with_optional_spinner` helper + 新 `kan update` 命令 + atexit register `_check_updates_atexit`
- `tests/test_paths.py`：4 case 守护 fresh 检查
- `tests/test_watchlist.py::TestColdStartInvariants`：subprocess + monkeypatch 双重防 akshare 顶层 import 回归
- `tests/test_config.py`（新）· 10 case 守护配置持久化（损坏自愈 + Unicode + atomic）
- `tests/test_updater.py`（新）· 27 case 守护 PyPI / cache / 派发 / 升级各路径

## [0.0.1] - 2026-05-10

### Added · 首次公开发布

**位置扫描** `kan scan`
- 多周期位置扫描（3/5/7/10/15/30/60/90/120/180 日）
- `--high` 高点模式 / `-S --signal` 仅显示有共振信号 / `--diff` 增量模式
- `--exclude-st` 排除 ST/*ST
- 多周期共振信号自动高亮（×N 标记）
- 终端宽度自适应（130+ 列 10 周期 · 100 列 6 周期 · 80 列 4 周期 · 共振列始终可见）

**筛选模式**
- `kan low N [N2 ...]` / `kan high N [N2 ...]` 触及阈值筛选（≤5% 低点 / ≥95% 高点 · 支持多周期）

**连续涨跌看板** `kan trend`
- `--latest N` 近 N 天走势
- `--down N` / `--up N` 筛选连续涨/跌（N 范围 2-30）
- `--candle` 阳线阴线口径
- 涨跌停自动标记
- 跨板块差异化涨跌停限制（按 2026-07-06 政策日期切换）

**单只详情**
- `kan info <代码>` 全周期位置 + 涨跌 + 共振统计

**自选股管理**
- `kan add` 支持代码 + 名称搜索 + 批量
- `kan remove` 支持名称 + 批量
- `kan list` / `kan import` / `kan clear`
- `kan uninstall` 一次清数据 + 输出包卸载命令（自动检测 uv tool / pipx / pip）

**数据层**
- 多源 K 线 fallback：`baostock → 新浪 → 东财 → 腾讯`
- 本地 Parquet 缓存（`~/.local/share/kan/data/` · XDG 规范）
- 7 天 A 股代码-名称缓存 + 自动过期更新
- `kan fetch [--force]` 手动刷新

**Shell 集成**
- `kan completion install [shell]` 一键启用 zsh / bash / fish / powershell 命令前缀补全
- 任意命令首次启动自动启用补全（`KAN_NO_COMPLETION_AUTOINSTALL=1` 可关闭 · 非 TTY 跳过）

**合规与隐私**
- 强制风险提示 + 关键词黑名单（无买卖建议 / 无目标价 / 无评级）
- 所有数据本地存储 · 不上传任何用户数据
- `CONTRIBUTING.md` + `SECURITY.md` + 公开输出语言纪律

[Unreleased]: https://github.com/piklen/manmankan/compare/v0.0.4.1...HEAD
[0.0.4.1]: https://github.com/piklen/manmankan/compare/v0.0.4.0...v0.0.4.1
[0.0.4.0]: https://github.com/piklen/manmankan/compare/v0.0.3...v0.0.4.0
[0.0.3]: https://github.com/piklen/manmankan/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/piklen/manmankan/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/piklen/manmankan/releases/tag/v0.0.1
