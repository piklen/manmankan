# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses PEP 440 numeric release segments (`A.B.C[.D...]`);
routine patches keep the first three segments stable unless the maintainer
explicitly approves a larger bump.

## [Unreleased]

## [0.0.6.9.26] - 2026-07-24

### Added

- `kan history --pool` 池级位置趋势：按快照日聚合池内位置中位数、低位≤20% 与高位≥80% 只数，带旧→新趋势摘要；残缺快照日（自定义周期/分组扫描遗留）自动跳过；默认周期 180，支持 `-p` 与 `--format json`。

## [0.0.6.9.25] - 2026-07-24

### Fixed

- `kan web` 个股详情页组件 init 被 x-data 自动调用与 x-init 重复执行两次（历史数据重复拉取）。
- `kan web` 持仓页饼图渲染从 x-effect 改为 $watch：x-effect 会把渲染内部对 pieChart 的响应式读写收进依赖，首次赋值即重触发自身造成双渲染。

## [0.0.6.9.24] - 2026-07-24

### Changed

- `kan web` 首页默认视图从全量数据表改为位置热力图（分页展示），与「先看关键变化和极端位置，需要时再展开全部数据」的设计对齐；移动端首屏高度从约 13000px 降到约 3300px。

### Fixed

- `kan web` 位置热力图首屏经常渲染失败（格子全空）：ECharts 5.6 首屏异步管线 race，视图渲染先于坐标系/数据就绪。组合修复：lazyUpdate 整批更新、merge 保持坐标系、移除 setOption 后的 resize 触发、硬指标自检（坐标系 + 已绘元素数）失败自动重渲。
- `kan web` 首页组件 init 被 x-data 自动调用与 x-init 重复执行两次。

## [0.0.6.9.23] - 2026-07-24

### Added

- 新增 `kan status` 本地数据状态一览：K 线缓存只数与最新截止、滞后只数、代码表、快照天数、自选/持仓/现金、tushare 凭证与 endpoint、数据源熔断状态；纯本地读取零网络，单项损坏不影响整页；支持 `--format json`。

## [0.0.6.9.22] - 2026-07-24

### Added

- `kan daily` 新增今日收盘方向分布（涨 / 跌 / 平家数，terminal / JSON / md / csv 同步）。

### Fixed

- `kan daily` 长股票名单折行时续行顶格的问题，改为按显示宽度折行并悬挂缩进。

## [0.0.6.9.21] - 2026-07-24

### Added

- `kan daily` 新增位置变化对比（与上一份快照比较）与池内 180 日中位位置。
- `kan find` 终端输出新增 180 日位置分布摘要；`--format json` stats 新增 position_180_distribution。
- `kan history` 新增趋势摘要行（旧→新位置序列 + 整体方向判断）。
- `kan hold --format csv` 支持（BOM 头，Excel 兼容）。

### Fixed

- 修复 mini-racer 0.14+ 在 macOS 上缺少 `__init__.py` 导致 `from py_mini_racer import MiniRacer` 失败（题材/同花顺 Cookie 生成链路）。
- `kan web` 个股 180 日位置变化（p180_change）计算中 dict→float 的 TypeError。
- `kan find` 窄终端表格列截断。
- `kan scan --sort pos` 高点模式改为降序；无效 `--group` 在 `--format json` 下输出结构化错误。
- `kan scan` 空结果报错区分「候选池为空」与「数据未拉取」。
- `kan trend` / `kan compare` / `kan info` 等命令 `--format json` 错误统一结构化 envelope，trend/compare 输出补 `ok` + `schema_version`。
- `kan daily` / `kan trend` / `kan low` / `kan high` / `kan info` / `kan index` / `kan compare` / `kan history` / `kan board rank` / `kan theme trend` 的 `--format csv` 输出正确 CSV（此前静默输出 Markdown）。

## [0.0.6.9.20] - 2026-07-24

### Fixed

- `kan low` / `kan high` 表格标题不再折行：数据截止与拉取时间从长标题移到表格下方 caption 小字（low/high 表只有 5 列，长标题必在表宽处折行且断点难看）；`kan scan` / `kan trend` 的标题裁剪逻辑统一为共享 helper。

## [0.0.6.9.19] - 2026-07-24

### Fixed

- `kan scan` 每日快照(`last_scan.json` + `snapshots/` 日归档)只允许「全池 + 默认周期 + 无分组」的扫描写入：此前分组扫描、自定义 `--periods` 扫描会用子集数据覆盖完整快照，导致 `kan history` 位置历史大面积显示占位值 50%、周期数据断档。

## [0.0.6.9.18] - 2026-07-24

### Fixed

- `kan web` 个股详情页 `/stock/{code}` 不再 500：行业位置对照序列化误读模型上不存在的 `stock_pct`/`rank` 字段，已对齐真实模型 `position_pct`/`rank_low_to_high`/`sample` 并补真实模型回归测试。
- `kan web` 页面内联 SVG favicon，浏览器不再因自动请求 `/favicon.ico` 被会话校验拦截而在控制台报 401。

## [0.0.6.9.17] - 2026-07-24

### Fixed

- `kan trend` 累计涨跌幅带显式 +/- 号，管道、重定向或无色终端丢失颜色时涨跌方向仍可读（题材连续涨跌榜同步修复）。
- `kan trend` 表格标题与 `kan scan` 同一策略按终端宽度省略「拉取时间」「数据截止」后缀，窄终端标题折行明显收敛。

## [0.0.6.9.16] - 2026-07-24

### Fixed

- `kan scan --compact` 周期列数随终端宽度自适应：90 列以下只保留 30/180 两个周期，80 列窄终端（含涨停/持仓标记行）表格不再被裁掉右边框。
- `kan scan` / `kan find` 表格标题随终端宽度省略后缀：先舍「拉取时间」、再舍「数据截止」，避免长标题把表格撑宽导致窄终端裁边；Markdown 导出始终保留完整标题。

## [0.0.6.9.15] - 2026-07-24

### Changed

- `--all` 股票池恢复字面全市场语义，保留主板、创业板、科创板、北交所和 ST；需要排除板块时继续使用命令已有的显式过滤项。
- `kan trend --all` 新增 `--force/-f`，可强制重拉每日全市场截面缓存；每个网络请求等待期间持续显示确定进度，不再停留在"开始每日截面"。
- TuShare 适配器只发送官方接口参数：`stock_basic(list_status=L)` 与 `stk_factor_pro(trade_date=...)`，不注入或消费兼容端点自定义的分页规则。
- 数据新鲜度警告区分「全池滞后」与「部分滞后」：部分股票已到最新交易日时按「N/M 只股票数据滞后 · 最新 X · 最旧 Y」提示，不再用「当前缓存到最旧日」与标题数据截止日自相矛盾。

### Fixed

- 全市场股票列表和近期单日 K 线截面在落盘前执行完整性校验；明显不足的响应会返回 `tushare_data_contract_error` 并停止处理，不再缓存或把第一页冒充全市场。
- `kan fetch --force --all` 现在会同时强制刷新全市场股票列表，避免强刷 K 线时仍沿用旧的部分股票池缓存。
- `kan trend --all` 的新鲜度以最新截面日判断，不再把 31 日历史窗口的第一天误报为全市场截止日；新股、停牌等历史不足单独提示，不再误报为市场数据整体滞后。
- `kan scan` 终端表格「量价」列不再被截断成「量缩·…」，宽终端下完整显示「量缩·收跌」等量价事实。
- `kan web` 启动时打印的访问地址立即 flush，stdout 重定向（`> log` / nohup）下也能看到本次会话链接。
- `kan scan --codes` 指定的代码全部无数据时，报错点名具体代码并引导检查代码正确性，不再只给泛泛的 `kan fetch` 提示。

## [0.0.6.9.14] - 2026-07-22

### Added

- `kan web` 首页 180 日位置新增变化指示（↑/↓对比上一份快照），散户一眼看到位置变化方向。
- `kan web` 首页位置分布条旁新增变化概况（↑N ↓N），整体位置变化方向一目了然。
- `kan web` 个股详情页关键周期卡片新增「距低/距高」百分比距离。
- `kan web` 个股详情页基础字段新增股息率 TTM 和量比。
- `kan web` 个股详情页新增「导出位置历史 CSV」按钮。
- `kan web` 新增键盘快捷键帮助浮层（按 ? 或点击 header 的 ? 按钮）。
- `kan web` 持仓页新增「导出 CSV」按钮。

## [0.0.6.9.13] - 2026-07-22

### Added

- `kan web` 找股票结果新增「+ 自选」快捷按钮：筛选结果卡片上一键加入自选，找到即加入一步到位。
- `kan web` 找股票新增「全部加入自选」批量操作：筛选出一批符合条件的股票后可一键全部加入。
- `kan web` 首页新增「导出 CSV」按钮：一键导出当前排序后的位置扫描数据，BOM 头确保 Excel 正确识别中文。

## [0.0.6.9.12] - 2026-07-22

### Added

- `kan web` 首页新增池内概况统计：涨停/跌停数量 + 连阳≥3天股票数，散户一眼看到自选池极端状态。
- `kan web` 首页新增 180 日位置分布条：绿(低位)→灰(中位)→红(高位) 渐变色彩条，直观展示自选池整体位置区间。
- `kan web` 首页 freshness banner 新增具体更新时间显示（更新于 YYYY-MM-DD HH:MM）。
- `kan web` 数据表格单元格新增内联位置条：每个位置百分比下方 3px 彩色进度条，不读数字即可扫出关键位置。
- `kan web` 个股详情页新增「加入自选」快捷按钮：看完个股后一键加入，不必返回首页输入代码。

## [0.0.6.9.11] - 2026-07-22

### Added

- `kan web` 新增暗色模式：跟随系统 `prefers-color-scheme` 自动切换，也可手动点击 header 🌙/☀️ 按钮或按 D 键切换，偏好持久化到 localStorage。
- `kan web` 新增全局键盘快捷键：1-4 切换页面、D 深色模式、R 更新数据、/ 聚焦添加自选输入框。
- `kan web` 新增市场相位指示器：header 实时显示盘前/盘中/已收盘/休市状态。
- `kan web` 新增操作 toast 通知：添加/移除自选、更新数据、筛选完成等操作即时视觉反馈。
- `kan web` 新增最近浏览记录：首页展示最近查看的 8 只股票快捷标签（localStorage）。
- `kan web` 新增持仓仓位分布环形饼图（多只持仓时自动展示，含现金占比）。
- `kan web` 个股详情页新增迷你位置标尺（渐变轨道 + 动画圆点），关键周期位置值颜色编码。
- `kan web` 新增回到顶部悬浮按钮（滚动超过 400px 显示）。
- `kan web` 设置页新增使用提示区（每日更新、快捷键、数据安全、终端等价）。

### Changed

- `kan web` 首屏性能优化：ECharts 改为按需懒加载（仅在热力图/个股走势/仓位饼图可见时加载），减少首屏 JS 体积约 1MB。
- `kan web` 视觉全面升级：卡片阴影层次、按钮 hover/active 微交互、fade-in 入场动画、表格斑马纹、数字等宽对齐、概览列表 hover 位移。
- `kan web` 数据过期时 freshness banner 脉冲提醒动画。
- `kan web` 表格行点击直接跳转个股详情页（首页和找股票页）。
- `kan web` 空数据状态改为带图标的引导卡片，明确告诉新用户下一步操作。
- `kan web` 移动端响应式增强：概览卡片纵向堆叠、工具栏自适应折行、添加自选输入框全宽。
- `kan web` header 改为 sticky 定位，滚动时导航栏固定。
- `kan web` 排序按钮增加方向箭头指示（↓ 降序 / ↑ 升序）。
- `kan web` 中文字体栈优化（PingFang SC / Microsoft YaHei）+ 抗锯齿渲染。

## [0.0.6.9.10] - 2026-07-13

### Fixed

- `kan fetch --force --all` / `kan compare` 拉取进度数字丢失：调度器心跳事件覆盖进度事件导致渲染时检测不到 PROGRESS kind，修复后进度后缀和股票代码正确显示。

## [0.0.6.9.9] - 2026-07-13

### Added

- 新增统一操作生命周期反馈层：所有需网络 I/O 的 CLI 命令从启动到输出完毕显示连续、准确、可诊断的阶段状态（处理中/等待/降级/较慢/疑似停滞），替换旧版 `_with_heavy_imports_spinner` 机制；短命令不强制闪动画。
- 新增 provider-aware 动态调度器 (`kan/data/scheduler.py`)：每个数据源 lane（Baostock/TuShare/data-hub/EM）独立 AIMD 并发窗口，自动识别 40203/429 限流并退避，Baostock 固定单并发避免全局锁排队数百个无用 worker。
- 新增 provider 能力契约 (`kan/data/protocols.py` / `provider_contracts.py`)：结构化区分 success/empty/invalid/限流/timeout/transport/circuit-open 结果，fallback 成功不再掩盖上一 provider 的背压事实。
- 新增 DoH DNS 解析器 (`kan/infra/doh_dns.py`)：绕过 Clash fake-ip DNS 劫持，确保 akshare 访问同花顺/申万研究等金融数据站点时拿到真实 IP。

### Changed

- `kan fetch --all` 统一走 `fetch_batch`/调度器，不再在命令层逐股调用 `fetch_kline`。
- `kan trend --all` 生命周期覆盖完整阶段：交易日历→逐日截面获取→concat→sort→symbol filter→趋势计算→freshness→输出构造，不再在 100% 进度冻结。
- `kan board rank --kind theme` / `kan theme trend` 优先走 data-hub TuShare batch K 线，150/200 题材匹配，不再依赖单题材逐次 EM API。
- 所有裸 `ThreadPoolExecutor` 获取点（relative_strength/info/compare/index/scan enrichment 等）迁移至 `run_provider_jobs` 统一调度。
- 题材数据源线程安全加固：`py_mini_racer` (V8) 加全局锁，THS/EM 成分股拉取串行化，防止并发初始化导致 segfault。

### Fixed

- 修复 `kan board rank --kind theme` 因 `mini_racer` 多线程并发初始化 V8 导致的 segfault (exit 133)。
- 修复 `kan theme trend` 因 `ths_index` type=N(883xxx) 与 `ths_daily` 返回 code(700xxx) 编码错位导致 0 条 K 线匹配的超时 (exit 124)。
- 修复 `kan find --industry` 因 Clash fake-ip DNS 劫持导致申万研究 API 无法访问，返回 `BoardDataUnavailableError` 的问题。
- 修复题材选股 `kan find --industry` 成分股缓存过期后无 stale fallback 直接抛异常的问题。

## [0.0.6.9.8] - 2026-07-10

### Added

- 新增 `kan web` 本地看盘台:数据表 / 位置热力图双视图、个股位置标尺与走势、持仓页、筛选页(带等价 CLI 命令)、token 设置页;仅监听本机回环,补数据走后台任务加进度流。
- 首页新增大盘指数多周期位置对照(上证/深证/创业板/沪深300),数据不可用时中性降级。
- 指数日线在 TuShare 无 token 或接口未覆盖时 fallback 到 akshare 新浪源,指数位置对照对零 token 用户可用。
- 今日页新增数据截止日 / 正常应截止日、180 日高低位、自选关键变化和上一份不同交易日快照对比;默认聚焦 30 / 60 / 180 日,完整周期在个股页按需展开。
- 数据更新区分空股票池、已是最新、部分失败和全部失败;Web 每日快照与 CLI diff/history 隔离,不会覆盖命令行基线。
- 持仓与现金支持在 Web 内新增、修改和删除,普通用户不必返回终端完成日常管理。

### Changed

- 看盘台补数据进度从两档粗粒度改为逐股推送(SSE 显示当前刷新的股票与完成计数)。
- 持仓名称为代码占位时自动用本地股票名称缓存解析,CLI 与看盘台同时生效。
- 产品入口调整为普通 A 股散户优先:`kan`、`kan guide`、安装脚本、README 和官网都先引导 `kan web`;CLI / JSON / MCP 保持兼容并作为 AI / 开发者第二入口。
- 找股票页改用中文条件和可直接尝试的示例,高级 DSL 与等价 CLI 折叠展示。
- 普通命令结束后不再弹出 shell completion / MCP 注册询问;这些开发者设置只在用户主动运行 `kan setup`、`kan completion` 或 `kan mcp install` 时出现。

### Fixed

- `kan find --help` 只注册筛选命令所需模块,不再为一个帮助页加载完整 CLI 命令图,降低冷启动等待与 TTY 性能抖动。
- 自托管 CI 的测试数据目录与 `uv tool` 安装目录按 run / job / Python 版本隔离,特性分支统一由 PR 门禁验证,避免 push / PR 重复任务争抢 runner 后误报 TTY 性能失败。
- 题材成分股按上游真实页数完整拉取并限制异常页数,THS 会话 Cookie 失效会刷新重试;东财名称未匹配不再误触发全局熔断。
- Windows 自选文件的冲突令牌统一按原始字节计算,CRLF 不再导致同一文件误报“已被其他窗口修改”。
- Web 更新不存在的持仓返回 404,非法代码仍返回 400;题材/行业上游异常详情只写 debug 日志,不再直接展示给用户。
- 移除会与 AkShare 新版 `mini-racer` 覆盖同名包的 `adata` 依赖,题材数据改走内置 AkShare / 公开 HTTP 适配器;全新 macOS / Windows 安装不再因 ABI 混装导致交易日历失效。
- `kan` 空参数改为精简的普通用户启动页;`kan --help` / `kan help` 才展示完整命令表。
- `kan add 123` 等非 6 位纯数字输入立即提示格式错误,不再先加载全市场名称表。
- Web 新鲜度同时校验截止日与 180 日历史覆盖,短历史缓存会补拉;新股完成 180 日范围请求后不会永久误报陈旧。
- 持仓追加写入重新执行完整字段校验,拒绝 NaN、负数和越界数值;损坏持仓文件时隐藏写入表单并提示先备份。
- Parquet 改用同目录唯一临时文件写入数据和请求周期 metadata 后单次原子替换,并发写不再共用固定 `.tmp`。
- 非 ASCII 或超长 Web 会话值会被直接拒绝,不再让单个畸形回环请求触发 500。
- `kan scan --all` 不再覆写默认池的 diff 快照。
- 交易日历依赖的 py_mini_racer 在 dylib 加载失败机器上不再向终端输出裸 traceback。
- 自适应并发测试不再依赖真实线程调度时序,消除 CI 偶发失败。
- 看盘台序列化对 NaN/Inf 统一归一为 None(与 AI 导出口径对齐),避免个别股票非法浮点在 JSON 渲染阶段触发 500(该阶段在路由 return 之后,路由内 try/except 兜不住)。
- 补数据进度流(SSE)改为 async 生成器,不再占用请求线程池 worker;多标签页或客户端中途断开不会拖垮其他页面。
- 自选和配置写入补齐进程内锁及 POSIX / Windows 文件锁,并统一使用唯一 `0600` 临时文件;多标签页或 Web / CLI 并发不再丢更新、共用临时文件或留下宽权限 token 文件。
- `kan web` 每次启动生成随机会话链接,页面 / API / SSE 分别校验会话参数或请求头,不会把可重放 Cookie 共享给其他回环端口;同时禁止第三方页面 iframe 嵌入。
- Web 添加自选的非法代码提示改为页面内可执行的 6 位代码说明,不再引导普通用户跳回 CLI。
- Web 首次添加精确代码只读取已有名称缓存;缓存为空时先立即入池并提示名称加载中,不再同步等待全市场名称表。
- 看盘台个股历史周期越界改由 service 校验返回 400 并带范围提示,与 CLI 报错一致(此前被 Query 层通用 422 掩盖)。

## [0.0.6.9.7] - 2026-07-02

### Changed

- `kan trend --all` 改用近 31 个交易日的全市场 daily 截面计算连续涨跌,避免全市场扫描逐股补 K 线触发数千次请求；输出严格限制在目标股票池内,并同步每日截面缓存提示。

### Fixed

- 公开档案隐私自检不再因维护者本地环境说明和 runner 临时目录清理模式命中。

## [0.0.6.9.6] - 2026-06-26

### Changed

- 全市场 K 线补缓存从固定并发改为自适应并发:默认从现有启发式并发起跑,健康窗口内最多探到 20；遇到限流、超时、背压或失败会快速降并发。`KAN_WORKERS` 和调用方显式 `max_workers` 仍作为硬上限。

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

[Unreleased]: https://github.com/piklen/manmankan/compare/v0.0.6.9.26...HEAD
[0.0.6.9.26]: https://github.com/piklen/manmankan/compare/v0.0.6.9.25...v0.0.6.9.26
[0.0.6.9.25]: https://github.com/piklen/manmankan/compare/v0.0.6.9.24...v0.0.6.9.25
[0.0.6.9.24]: https://github.com/piklen/manmankan/compare/v0.0.6.9.23...v0.0.6.9.24
[0.0.6.9.23]: https://github.com/piklen/manmankan/compare/v0.0.6.9.22...v0.0.6.9.23
[0.0.6.9.22]: https://github.com/piklen/manmankan/compare/v0.0.6.9.21...v0.0.6.9.22
[0.0.6.9.21]: https://github.com/piklen/manmankan/compare/v0.0.6.9.20...v0.0.6.9.21
[0.0.6.9.20]: https://github.com/piklen/manmankan/compare/v0.0.6.9.19...v0.0.6.9.20
[0.0.6.9.19]: https://github.com/piklen/manmankan/compare/v0.0.6.9.18...v0.0.6.9.19
[0.0.6.9.18]: https://github.com/piklen/manmankan/compare/v0.0.6.9.17...v0.0.6.9.18
[0.0.6.9.17]: https://github.com/piklen/manmankan/compare/v0.0.6.9.16...v0.0.6.9.17
[0.0.6.9.16]: https://github.com/piklen/manmankan/compare/v0.0.6.9.15...v0.0.6.9.16
[0.0.6.9.15]: https://github.com/piklen/manmankan/compare/v0.0.6.9.14...v0.0.6.9.15
[0.0.6.9.14]: https://github.com/piklen/manmankan/compare/v0.0.6.9.13...v0.0.6.9.14
[0.0.6.9.13]: https://github.com/piklen/manmankan/compare/v0.0.6.9.12...v0.0.6.9.13
[0.0.6.9.12]: https://github.com/piklen/manmankan/compare/v0.0.6.9.11...v0.0.6.9.12
[0.0.6.9.11]: https://github.com/piklen/manmankan/compare/v0.0.6.9.10...v0.0.6.9.11
[0.0.6.9.10]: https://github.com/piklen/manmankan/compare/v0.0.6.9.9...v0.0.6.9.10
[0.0.6.9.9]: https://github.com/piklen/manmankan/compare/v0.0.6.9.8...v0.0.6.9.9
[0.0.6.9.8]: https://github.com/piklen/manmankan/compare/v0.0.6.9.7...v0.0.6.9.8
[0.0.6.9.7]: https://github.com/piklen/manmankan/compare/v0.0.6.9.6...v0.0.6.9.7
[0.0.6.9.6]: https://github.com/piklen/manmankan/compare/v0.0.6.9.5...v0.0.6.9.6
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
