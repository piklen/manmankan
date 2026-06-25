# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses PEP 440 numeric release segments (`A.B.C[.D...]`);
routine patches keep the first three segments stable unless the maintainer
explicitly approves a larger bump.

## [Unreleased]

## [0.0.6.9.5] - 2026-06-26

### Added

- `kan scan --all` / `kan trend --all` / `kan low --all` / `kan high --all` / `kan fetch --all` 支持全市场股票池；`find --all` 补齐与分组、自选池限制参数的互斥校验，避免把全市场扫描误跑成自选池或混合池。
- `kan trend all` 等误用参数会提示改用显式 `--all`；`scan --all --diff` 保持拒绝，避免全市场快照污染自选池日内 diff。

## [0.0.6.9.4] - 2026-06-26

### Fixed

- TuShare 兼容网关的可重试业务错误（限流、排队、超时、异步排队）不再触发本地 5 分钟 TuShare 熔断；命令会短重试，避免临时波动后整批 K 线降级到 baostock。
- K 线数值清洗将空白字符串按缺失值处理，不再把 baostock 返回的空 `volume` / `amount` 误报为“无法解析的数值”。
- `kan find --dry-run --format json` 查询计划补回顶层 `disclaimer`，与普通 `find` JSON 和公开文档保持一致。

## [0.0.6.9.3] - 2026-06-23

### Fixed

- `kan scan` 在窄终端默认输出不再等待 PE/PB、资金流和除权事件等外部增强字段；这些字段未展示时直接走本地 K 线扫描，避免盘中资金流缓存过期后每次卡在外部刷新超时边界。
- `kan scan` 外部增强超时或异常降级时仍保留一手金额、现金占比、交易权限等本地散户事实字段；窄终端渲染不会因此额外挤出“1手元/权限”等列，保持原有紧凑表格。

## [0.0.6.9.2] - 2026-06-23

### Fixed

- `kan scan` 的 PE/PB、资金与除权事件等可选增强字段增加 8 秒硬超时；外部数据源慢或卡住时自动降级为本地 K 线位置扫描，避免主命令长时间无输出。
- `kan scan` 除权除息标记只读本地 dividend 缓存（允许过期），不再在扫描主路径逐股刷新远端 dividend 数据；完整缓存刷新仍交给显式数据更新流程。

## [0.0.6.9.1] - 2026-06-23

### Added

- 散户体验事实字段与入口：`scan` / `find` / `info` 输出一手金额、占已录入现金比例、科创/北交/创业板权限提示、距区间高低点距离和量价方向组合；新增 `--exclude-star` / `--exclude-bj` 权限过滤、`kan guide` 意图导航、`kan daily` 默认池一日事实概览，以及 `find --fields @retail` 字段 preset。
- 新增 `docs/contributor-quickstart.md`，面向首次贡献者补齐 good first issue 选择、本地 smoke、验证命令、PR 自检和 AI 协作边界；README、docs index、SUPPORT、issue contact links 和 site footer 同步入口。
- 许可证迁移至 GNU Affero General Public License v3.0（`AGPL-3.0-only`）；README、site、安装脚本、PyPI classifier、NOTICE 和合规边界同步更新，明确项目许可证覆盖代码 / 文档，不替代第三方行情数据、API、SDK 或投资合规义务。
- GitHub Discussions 已启用；`SUPPORT.md`、issue contact links、README 文档导航和 site footer 同步区分 Discussions / Issues / Security 的支持入口。
- 新增 `docs/china-quickstart.md`，面向中国 A 股用户和中国开发者补齐国内网络、PyPI 镜像、TuShare token、代理、Windows / PowerShell、issue 反馈信息的首用路径；README、docs index、SUPPORT、site 和 issue contact links 同步入口。
- 新增 `docs/mcp.md` 和 `SUPPORT.md`，补齐 MCP 客户端接入、dry-run 写入规则、agent 解释边界、issue 分流和安全报告入口；GitHub issue template config 增加 AI / MCP / security contact links。
- 公开仓库新增 `AGENTS.md` 和 `docs/ai-quickstart.md`，分别服务 AI 编程助手贡献代码、AI agent 首次调用 CLI/JSON/MCP；README、site、`skills/manmankan-skill.md` 和 `kan examples` 同步为“结构 smoke / 真实行情坐标 / MCP dry-run”三步首用路径。
- `kan scan --periods` 支持显式选择 2-360 周期集合，`--compact` / `--wide` 支持终端窄屏与全周期展示手动切换。
- `kan board rank --period`、`kan compare --periods`、`kan history --period` 的周期边界统一到 2-360；`compare` 会按用户指定周期实际计算。
- `kan info <code>` 增加所属申万一级行业的位置均值与低到高排名对照；无行业映射或本地样本不足时自动降级不展示。
- `kan hold` 真实持仓账本：用户手动录入成本 / 股数 / 现金，本地计算今日盈亏、累计盈亏、仓位和 30/60/180 日位置；`scan` / `find` 默认池扩展为自选 ∪ 持仓，并支持 `--only-holdings`。
- **`kan find --rs-index / --rs-board`** · 相对强度 filter · 个股区间涨幅 − 对照（大盘指数 / 所属申万一级行业）区间涨幅的客观差值 · `PERIOD:OP:VAL`（2-360 周期 · 差值可正可负）· K 线池与全市场 `--all` 两路支持 · `--rs-index-code` 可改大盘对照指数（默认沪深300 · `--rs-index` 依赖 tushare `index_daily`，需 2000 积分）· 对照缺失（周期不足 / 个股行业未知 / 指数无权限）按周期降级不命中、不当 0 · `--format json` 带 `@relative_strength` 字段（个股/对照原始涨幅 + 差值 + 行业 + 对照指数）与 triggered 审计 · 只输出客观差值裸值、不判强弱龙头 · disclaimer 强制

### Fixed

- `tty-test` CI 的 `uv tool install` 增加 `--force`，避免自托管 runner 已存在 `kan` wrapper 时因 entry point 冲突失败。
- **MCP server 全部工具修复** · root callback 此前用 `len(sys.argv) == 1` 判断"用户未敲子命令"，但 `kan-mcp` 进程的 `sys.argv` 长度恒为 1，导致每个工具经 in-process `CliRunner` invoke 时都被误判为无子命令 → 打印命令速记并 `raise Exit`，`kan_info` / `kan_scan` / `kan_find` / `kan_index` / `kan_fields` / `kan_hold` / `kan_examples` 全部塌缩成同一段 help、永远拿不到真数据。改用 `ctx.invoked_subcommand`（读 Click 解析结果，对真 CLI 与 in-process invoke 都正确），并补 argv 长度 1 下的回归测试（pytest 进程 argv 长度 > 1 会掩盖此 bug，故 monkeypatch argv 复现）。

## [0.0.6.9] - 2026-06-04

### Changed

- README 首屏强化为 GitHub 仓库首页入口:突出本地 A 股数据筛选器、CLI/JSON、AI 可读数据层和不替用户决策的边界。
- PyPI / package metadata keywords 与 homepage 补充 AI workflow、JSON 和项目站点入口。

### Fixed

- 自升级安装后 smoke 改为验证 runtime version、package metadata 和公开 `kan.api`,不再导入历史内部模块路径导致成功安装被误判失败。
- PyPI package summary 更新为「告诉你坐标,不替你决策」定位,避免公开包列表页继续沿用旧版用户面文案。

## [0.0.6.8] - 2026-06-04

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
- **`kan find --format json --compact --no-compact-context`** · compact 可显式省略 `positions` / `low_resonance` / `high_resonance` / `gains` / `up_days`;`--all` 无 K 线 filter 时不再为 compact 输出主动取全市场 K 线快照
- **`kan find --format json --fields @preset`** · 字段 preset 支持 `@core` / `@context` / `@valuation` / `@valuation_context` / `@moneyflow` / `@technical` / `@sentiment` / `@chip` / `@shareholder`,仅展开客观字段集合,不改变筛选规则或排序

### Changed

- `kan find --all --format json --compact|--fields` 现在按 filter、compact 摘要和字段白名单反向驱动截面维度取数;未请求的 moneyflow / technical / sentiment / chip 不再无条件拉取,`data_availability` 对应维度显示 `not_requested`
- `kan find` JSON schema version 升至 `0.0.6.8`
- 首次运行 `kan` 时后台静默初始化 A 股代码-名称表;首次 / 无 cache 的 `kan add <6位代码...>` 走数字代码快路径,不等待名称表下载完成
- `kan help` / README / site 去除用户面硬编码发布版本号;具体版本仅保留在包元数据、CHANGELOG、JSON schema 和 `kan update` 等版本功能中
- README / site 统一调整为「告诉你坐标,不替你决策」定位,强调人和 AI 共用的本地数据筛选器,并压缩 README 的命令手册式内容
- 代码注释、测试说明和 CI 文案中的历史发布版本标记改为中性描述,降低公开仓库的版本噪音

### Fixed

- `kan find --format json --codes ...` 的非法 / 空代码池错误现在返回 `ok:false` JSON envelope,不再退回纯文本错误,保持 AI / 脚本消费契约一致
- `kan find --codes ... --format json` 无 filter 时走轻量 code-pool JSON,不再为外部代码池隐式触发 K 线 / 交易日历网络链路
- `kan history --format json` 的无历史、未命中和非法周期错误统一返回机器可读 JSON envelope
- `kan update` 升级后 smoke test 改用真实公开 API / 模块,并在指定目标版本时校验 runtime version
- K 线源同 priority race 改用 daemon worker,避免慢 loser 在已中标后继续拖住 CLI 进程退出
- 扫描快照写入改走原子 JSON 写入并保持 `0600` 文件权限
- debug 日志脱敏补齐 JSON token / Authorization / Bearer token 常见泄漏形态
- 东方财富飙升榜在上游字段缺失时改走更稳的 fallback,避免 `kan scan --hot surge` 因单一接口漂移直接不可用
- 北交所 2024 新启用 `920xxx` 代码段被误判为上证（`.SH`）· 修正 `ts_code` 交易所后缀映射为 `.BJ`（影响北交所个股的 tushare K 线 / 截面拉取）
- `kan compare` 不再在超过 8 只时直接拒绝 · 终端自动按 8 只一页展示,JSON / Markdown 保留全量输出
- TuShare K 线顶档源改用 `stk_factor_pro` 前复权 OHLC,并给 K 线缓存写入 `_adjust=qfq`;旧版 TuShare 未复权缓存会自动判 stale 重新拉取,避免除权除息日前后位置跳变

### Internal

- 增加 find registry → docs / CLI help / field schema 一致性测试,降低 filter 元数据、字段白名单、文档和 help 漂移风险
- `typer` 依赖上界调整为 `<0.27`,并通过 lockfile / package smoke / TTY CI 验证
- 隐私扫描新增用户面硬编码版本号 gate,防止 README / site / `kan help` 再次出现当前具体版本号
- release workflow 新增 tag / version / main ancestry gate,并在 PyPI 发布前跑 dist wheel clean-install smoke
- release workflow 绑定 `pypi` environment,配合仓库环境 reviewer 做发布前人工确认
- GitHub Pages 站点移除浏览器 Tailwind CDN,改用本地静态 CSS,降低站点运行时供应链依赖
- test workflow 将 macOS 全量 pytest 替换为 Python 3.11/3.12 targeted smoke + TTY 覆盖,保留平台信号,避免 GitHub macOS runner 偶发卡住拖慢发版
- 合规文档和路线图澄清 AI 边界:支持 AI 消费 JSON 数据做后续研究 / 筛选,但不输出 AI 选股建议、自动荐股或策略结论
- 截面市场指标数据源接入（`MetricsSource` 责任链 + tushare `daily_basic`）· 估值 / 量价 / 市值维度原始指标 · 复用既有「适配器 + 责任链」架构 · 配 tushare token 可用 · 内部数据层骨架（暂无 CLI 变化）
- 收敛 v0.0.6.6 review gap:中性措辞、JSON 契约和 registry 文档继续由测试守护

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

- **`kan find`** · 用户主导的条件筛选 DSL：`--pos PERIOD:OP:VAL`（位置百分位筛选）· `--resonance LEVEL:OP:VAL`（共振筛选）· `--exclude-st` · AND 语义 · 输出末尾强制 disclaimer
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

[Unreleased]: https://github.com/piklen/manmankan/compare/v0.0.6.9.5...HEAD
[0.0.6.9.5]: https://github.com/piklen/manmankan/compare/v0.0.6.9.4...v0.0.6.9.5
[0.0.6.9.4]: https://github.com/piklen/manmankan/compare/v0.0.6.9.3...v0.0.6.9.4
[0.0.6.9.3]: https://github.com/piklen/manmankan/compare/v0.0.6.9.2...v0.0.6.9.3
[0.0.6.9.2]: https://github.com/piklen/manmankan/compare/v0.0.6.9.1...v0.0.6.9.2
[0.0.6.9.1]: https://github.com/piklen/manmankan/compare/v0.0.6.9...v0.0.6.9.1
[0.0.6.9]: https://github.com/piklen/manmankan/compare/v0.0.6.8...v0.0.6.9
[0.0.6.8]: https://github.com/piklen/manmankan/compare/v0.0.6.6...v0.0.6.8
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
