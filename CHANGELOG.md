# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses PEP 440 four-part releases (`A.B.C.D`); routine patches
increment `D` unless the maintainer explicitly approves a larger bump.

## [Unreleased]

## [0.0.6.7] - 2026-06-02

### Added

- **`kan find --pe / --roe / --moneyflow`** · 估值 + 质量（ROE / 净利·营收增速）+ 资金（主力净额）filter · K 线池（`--industry` / 自选）与全市场 `--all` 截面两路支持（`--roe` 逐股 · `--all` 不支持）· 按用户 filter 输出原始值 · `--format json|md` 带 triggered 审计 · disclaimer 强制
- **`kan find --all`** · 全市场截面取数 · 一次拉全市场估值 / 量价 / 市值 + 行业内分位 + 行业中位对照 · 供外部 AI 筛选 · `--format json|md` · 需 tushare token · 排北交所 · 含 ST · disclaimer 强制
- **`kan find --codes`** · 支持逗号 / 空格 / 换行分隔的自定义代码池,`--codes -` 可从 stdin 读取 · 外部候选集可回传后继续叠加位置 / 共振 / 估值 / 资金 / 技术过滤
- **`kan scan --codes` / `kan scan <codes>`** · 支持指定 1-N 只代码直接扫描 · 输出仅包含显式代码池 · 不写入自选扫描快照
- **scan 行内联 AI 消费字段** · 每行增加 PE TTM、近 5 个交易日主力净额合计、10/20 日线、近 20 日低价与除权除息事件标记(有数据时显示)
- **`kan find --all` K 线预计算筛选** · 全市场模式新增位置 / 共振 / 区间涨幅 / 连阳裸值快照,支持 `--pos` / `--resonance` / `--gain` / `--up-days` / `--exclude-st` 与截面 filter 组合
- **`kan board rank`** · 板块级榜单 · 支持行业 / 题材按主力净额、区间涨幅、位置百分位排序 · `--format json|md`
- **`kan theme trend --min-streak / --sort`** · 题材连续涨跌榜开放 1 天阈值,新增按最新单日涨幅 / 题材资金排序
- **`kan find --format json --compact` / `--fields`** · 低字段量 JSON 输出和字段白名单 · 保留代码/名称/价格、触发 filter、位置/共振和已请求维度摘要;full / compact / fields JSON 均新增 `data_availability` 顶层统计,区分缺数据、未请求和当前模式不支持
- **find filter / field registry** · 集中登记 filter 数据源、频率、`--all` 支持度、缺数据语义和 `--fields` 白名单,避免 CLI / export / docs 的字段契约继续散落

### Fixed

- 北交所 2024 新启用 `920xxx` 代码段被误判为上证（`.SH`）· 修正 `ts_code` 交易所后缀映射为 `.BJ`（影响北交所个股的 tushare K 线 / 截面拉取）
- `kan compare` 不再在超过 8 只时直接拒绝 · 终端自动按 8 只一页展示,JSON / Markdown 保留全量输出
- TuShare K 线顶档源改用 `stk_factor_pro` 前复权 OHLC,并给 K 线缓存写入 `_adjust=qfq`;旧版 TuShare 未复权缓存会自动判 stale 重新拉取,避免除权除息日前后位置跳变

### Internal

- 截面市场指标数据源接入（`MetricsSource` 责任链 + tushare `daily_basic`）· 估值 / 量价 / 市值维度原始指标 · 复用既有「适配器 + 责任链」架构 · 配 tushare token 可用 · 内部数据层骨架（暂无 CLI 变化）

## [0.0.6.6] - 2026-05-30

### Added

- **`kan history <代码或名称>`** · 单只股票位置百分位历史回溯 · 纯离线读每日扫描快照（`kan scan` 累积的 240 天归档）· `--period` 切周期（默认 30）· `--format terminal|md|json` · 单周期纵向时间线（新→旧）+ 每日多周期共振标记 · 只覆盖曾在自选且跑过 `kan scan` 的股票 · 不预测涨跌，只回看历史位置

### Internal

- 开发期隐私扫描工具改进（禁词清单外置到本地 gitignored 文件）+ 文档精简

## [0.0.6.5] - 2026-05-27

> 自 v0.0.5.0 起累积的多个内部版本（v0.0.5.1 → v0.0.6.1）一次性发布到 PyPI。

### ⚠️ Breaking

- **License 由 MIT 切换为 Parity Public License 7.0.0**（source-available · 禁商用 · 禁 SaaS）
  - 个人散户日常自用完全免费 · 无需任何授权
  - 商业使用 / 把本工具打包卖给第三方需先获作者书面授权
  - 二次开发须保留版权 + 显著 attribution「Based on manmankan (https://github.com/piklen/manmankan)」+ 保留 disclaimer
  - 详见 `LICENSE` + `NOTICE`

### Added

- **`kan find`** · 用户主导的条件选股 DSL：`--pos PERIOD:OP:VAL`（位置百分位筛选）· `--resonance LEVEL:OP:VAL`（共振筛选）· `--exclude-st` · AND 语义 · 输出末尾强制 disclaimer
- **`kan group`** · 多分组管理（create / list / rename / delete / default / copy）· 现有命令新增 `--group` flag · 老用户零感知
- **`kan move`** · 跨组移动单股 · **`kan export`** · CSV 导出
- **数据源适配器 + 责任链架构** · 可注入自定义 `KlineSource` / `ThemeConstituentSource`（Wind / 通达信本地 .blk / 自建数据库）· chain 按 priority 排序 + 失败 fallback
- **公开 Python API** · `from kan.api import scan, low, high, trend, fetch, from_flags, WatchlistSet, ...`
- **`kan theme trend`** · 题材连续涨跌榜
- storage 升级到 v2 schema（多分组）· 老 `watchlist.json` 自动迁移 · 用户零感知

### Migration · v0.0.5.0 → v0.0.6.5

- License 变更（个人自用无影响 · 商业 / 二次开发请先看 LICENSE + NOTICE）
- 新增 `kan find` / `kan group` / `kan move` / `kan export`
- 现有命令新增 `--group`（不带 flag 走默认组「自选」）
- `watchlist.json` 自动迁移 v1 → v2

## [0.0.5.1] - 2026-05-24

### Fixed

- 升级期间显示进度 spinner · 之前选「立即升级」后到结果之间是黑屏静默（10-30s）· 易被误判为卡死 · 非 TTY 环境自动静默不污染 pipe

## [0.0.5.0] - 2026-05-23

### Added

- **东方财富热榜扫描** · `--hot rank|surge` 作临时标的来源 · 加到 scan / low / high / trend / fetch · `--only-watchlist` 取自选 ∩ 热榜
- **TuShare Pro 可选数据源** · `kan config get/set/unset` · 配 token 后顶替 baostock 主路径 · token 自动 mask · 不配 token 行为零变化
- **题材位置扫描** · 9 命令支持 `--theme` · `kan theme list/search` 发现入口
- 成交量异动标签从 2 档扩为 5 档对称（scan 表 / `kan info`）

### Known Issues

- 题材成分股数据源受上游限流 / 接口变更影响可能阶段性不可用 · 触发时给友好提示 · 行业扫描（`--industry`）可用
- Apple Silicon arm64 上某些题材数据路径有 dylib 噪音 · 仅影响 debug log · 可改用 `--industry`

## [0.0.4.8] - 2026-05-16

### Added
- 子命令 `--help` 信息密度提升 · 错误消息加「下一步引导」
- 凌晨 / 晚间日界提示（「今晨 01:00」/「昨晚 23:50」）防误判数据日期
- 批量补数据进度条加 ✅/❌ + 累计失败数
- install.sh / install.ps1 SHA256 在 release notes 公布

### Changed
- 涨跌停状态警告改纯状态描述 · 删除预测性措辞
- 收紧 `pandas>=2.0,<3` 防 pandas 3.0 的 read_parquet 行为变更
- debug 日志脱敏本地路径 + token

### Fixed
- 测试改用真实 CLI runtime · 提升 CLI 命令组覆盖率

## [0.0.4.7.1] - 2026-05-14

### Fixed
- 「检查缓存」阶段分 3 段 spinner · 之前 169 只冷启动时单句提示 5-30s 无反馈 · 易被误判卡死 · 现显示 加载模块 → 交易日历预热 → 数字进度

## [0.0.4.7] - 2026-05-14

### Added
- 🌱 新手专区 + 一键安装脚本（install.sh / install.ps1）· mac / Windows 复制粘贴 2 步装好
- `KAN_DATA_AVAIL_OFFSET_MIN`（跨时区 / WSL2 UTC）+ `KAN_WORKERS`（手动降并发）env var

### Changed
- 日期格式压缩（同年隐藏年份 / 当天只显示时间）· 80 列窄屏不溢出
- stale / 盘中警告改散户语言 · 显式算「滞后 N 天」
- 补数据并发数自适应（cpu_count*2 · 上限 12）

### Fixed
- 交易日历容错 · akshare 失败 + cache 损坏时退化为 weekday 启发式
- 缓存内容 sanity check · 权限校验 · 异常 except 收窄

## [0.0.4.6] - 2026-05-13

### Fixed
- zsh/bash 命令补全报错 hotfix · 补全子进程触发 atexit 询问 prompt 写到 stdout 被 shell 误解析 · 现补全场景完全静默 · isatty 判定从 `or` 改为 `and`

## [0.0.4.5] - 2026-05-13

### Fixed
- **数据时效性核心修复（强烈建议升级）** · 凌晨拉数据后缓存 mtime 是「今天」但 K 线只到「昨天」· 导致 scan 整天显示昨日涨停名单。缓存新鲜度判据由 mtime 改为 K 线 date 列（对比 A 股交易日历）
- 新增交易日历模块 + 市场相位判定（盘前 / 盘中 / 盘后）· 标题分离「数据截止 X 收盘」与「拉取时间」· 盘中相位警告

## [0.0.4.4] - 2026-05-12

### Fixed
- **安装后导入失败修复（强烈建议升级）** · 依赖加 SemVer 上限防拉到不兼容大版本 · 升级改 force-reinstall 避免老 `.so` cache 不重链 · 升级后跑 import smoke test · `scanner.py` 改 lazy import · 顶层 ImportError 兜底给 reinstall 引导
- `kan add` 无效输入不再静默失败 · `kan info` 涨跌符号一致（▼绿 / ▲红）

### Security
- 用户数据目录 0700 · `watchlist.json` / `config.json` 0600（防多账户环境他人读取持仓画像）
- CI workflow 显式声明最小权限 · 加禁词扫描 job

### Added
- release 后 PyPI clean-install smoke matrix（ubuntu/macos × uv/pip × py3.11/3.12）

## [0.0.4.3] - 2026-05-12 [YANKED]

> ⚠️ **本版本已从 PyPI yank** · 安装后即崩溃（依赖版本错位 + 顶层 `import pandas`）。请直接升级到 v0.0.4.4：`uv tool install manmankan --reinstall`

### Performance
- 启动阶段先输出 `⏳ 启动中...` 到 stderr 避免空屏 · `KAN_NO_BOOT_BANNER=1` 可关

## [0.0.4.2] - 2026-05-12

### Changed
- 启动分阶段提示（加载数据模块 → 检查缓存 → 拉取数据）· 单只拉取也进 spinner
- A 股代码表主源失败时显式提示切换备用源

## [0.0.4.1] - 2026-05-12

### Fixed
- `kan fetch / low / high / info / trend` 加载数据模块前先显示 spinner · 避免空屏

## [0.0.4.0] - 2026-05-12

### Fixed
- 数据命令启动反馈缺失 · `fetcher.py` 顶层不再 import akshare/pandas（改按需加载）· 重模块加载前打开 spinner · 首帧反馈从约 500-700ms 提前到 200ms 内

## [0.0.3] - 2026-05-11

### Changed
- 内部重构（零行为变更）· `cli.py` 拆分为八个职责单一的子模块 · 命令组之间零耦合

### Added
- 命令注册守护测试（锁定命令集）

## [0.0.2] - 2026-05-11

### Performance
- 冷启动延迟修复 · `akshare` 改 lazy import（仅 fallback 时才付加载成本）· 用轻量 paths 先决策再 import 重模块 · 启动反馈从约 10s 提前到立即可见

### Added
- **自动更新机制** · `kan update`（`-y` 跳确认 / `--check` 仅查）· 启动 atexit 检查（不阻塞主流程）· 首次发现新版 prompt 询问偏好 · 安装方式自动检测（uv tool / pipx / pip）· daily cache + 3s timeout + 失败静默

## [0.0.1] - 2026-05-10

### Added · 首次公开发布
- **位置扫描** `kan scan` · 多周期（3/5/7/10/15/30/60/90/120/180 日）· `--high` / `-S` / `--diff` / `--exclude-st` · 共振 ×N 标记 · 终端宽度自适应
- **筛选** `kan low N` / `kan high N`（≤5% 低点 / ≥95% 高点 · 多周期）
- **连续涨跌看板** `kan trend` · `--latest` / `--down` / `--up` / `--candle` · 涨跌停跨板块差异化标记
- **单只详情** `kan info` · **自选股管理** `kan add/remove/list/import/clear` · **`kan uninstall`** 一键清数据 + 输出卸载命令
- **数据层** · 多源 K 线 fallback（baostock → 新浪 → 东财 → 腾讯）· 本地 Parquet 缓存（XDG 规范）· 7 天代码-名称缓存
- **Shell 补全** · zsh / bash / fish / powershell
- **合规与隐私** · 强制风险提示 + 关键词黑名单（无买卖建议 / 无目标价 / 无评级）· 数据全本地

[Unreleased]: https://github.com/piklen/manmankan/compare/v0.0.6.7...HEAD
[0.0.6.7]: https://github.com/piklen/manmankan/compare/v0.0.6.6...v0.0.6.7
[0.0.6.6]: https://github.com/piklen/manmankan/compare/v0.0.6.5...v0.0.6.6
[0.0.6.5]: https://github.com/piklen/manmankan/compare/v0.0.5.1...v0.0.6.5
[0.0.5.1]: https://github.com/piklen/manmankan/compare/v0.0.5.0...v0.0.5.1
[0.0.5.0]: https://github.com/piklen/manmankan/compare/v0.0.4.8...v0.0.5.0
[0.0.4.8]: https://github.com/piklen/manmankan/compare/v0.0.4.7.1...v0.0.4.8
[0.0.4.7.1]: https://github.com/piklen/manmankan/compare/v0.0.4.7...v0.0.4.7.1
[0.0.4.7]: https://github.com/piklen/manmankan/compare/v0.0.4.6...v0.0.4.7
[0.0.4.6]: https://github.com/piklen/manmankan/compare/v0.0.4.5...v0.0.4.6
[0.0.4.5]: https://github.com/piklen/manmankan/compare/v0.0.4.4...v0.0.4.5
[0.0.4.4]: https://github.com/piklen/manmankan/compare/v0.0.4.3...v0.0.4.4
[0.0.4.3]: https://github.com/piklen/manmankan/compare/v0.0.4.2...v0.0.4.3
[0.0.4.2]: https://github.com/piklen/manmankan/compare/v0.0.4.1...v0.0.4.2
[0.0.4.1]: https://github.com/piklen/manmankan/compare/v0.0.4.0...v0.0.4.1
[0.0.4.0]: https://github.com/piklen/manmankan/compare/v0.0.3...v0.0.4.0
[0.0.3]: https://github.com/piklen/manmankan/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/piklen/manmankan/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/piklen/manmankan/releases/tag/v0.0.1
