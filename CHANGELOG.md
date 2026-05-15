# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.4.7.1] - 2026-05-14

### Fixed · "检查缓存" spinner 进度可见 hotfix (真用户反馈触发)

**主诉 case**：用户升级 v0.0.4.7 后跑 `kan scan` · 169 只自选股 + 冷启动 · `⏳ 检查缓存 ...` spinner 5-30s 沉默无任何子进度 · 真小白误判工具卡死。

**根因**：v0.0.4.7 之前的 `_auto_fetch_stale` 第一个 spinner 是单句"检查缓存..." · 内部干 3 件事(lazy import akshare/pandas · 遍历 169 只调 is_fresh · 首次 latest_trade_date 可能拉 akshare)但全在同一 spinner 文字下 · 用户看不到任何 sub-progress。

**修复方案**（B+C 组合 · 3 阶段 spinner）：

- **Stage 1** `⏳ 加载数据模块...` (akshare/pandas import 阶段 · 1-3s)
- **Stage 2** `⏳ 加载交易日历 · 169 只自选股待检查...` (explicit pre-warm `latest_trade_date()` · 防 ticking 阶段第 1 只时 latent 触发 akshare 5-15s 拉取)
- **Stage 3** `⏳ 检查缓存 · 80/169 只 · 已发现 N 只 stale` (数字 ticking + 已发现 stale 数 · 每 5% update 一次 spinner · 防闪烁)

不给精确 ETA (精度差容易让用户失望) · 用 "首次稍慢 · 后续秒级" 诚实表达 · 首次扫描会刷新全市场交易日历是一次性。

**影响范围**：

- 所有 v0.0.4.7 升级用户首次 `kan scan` / `kan trend` / `kan low` / `kan high` 都会受益(任何走 `_auto_fetch_stale` 的命令)
- 30 只自选股第一次 scan 约 5-10s 看到 ticking · 169 只约 10-30s · 千只约 30-60s
- 第二次起 ticking 极快(akshare 已 warm + trade_dates 已 cached)
- ⚠️ 注:首次 scan 仍有总 30-60s 等待 · 但用户看得见进度 · 不再误判卡死

**升级**：

```bash
uv tool install --upgrade manmankan
```

无需手动操作 · 自动生效。

**测试**：

- 新增 `tests/test_spinner_check_cache_progress.py` 3 case (覆盖 1 只 / 169 只 / 0 只边界)
- 全套 292 passed (291 + 1 新)
- ruff clean · privacy clean

## [0.0.4.7] - 2026-05-14

### Added · 分发资产 + 散户友好

- **🌱 新手专区 + 一键安装脚本**：mac / Windows 第一次用命令行的散户复制粘贴 2 步装好
  - `scripts/install.sh`（mac / Linux）：检测 / 装 uv → 装 manmankan → smoke verify · 全程中文 · 失败给 fallback
  - `scripts/install.ps1`（Windows）：同等流程 + PowerShell ExecutionPolicy 友好提示
  - README 顶部 `<details>` 折叠"新手专区"（不打扰老用户）· 含 mac / Win 各 2 步 + 装好后示例 + FAQ
  - 调用：`curl -LsSf https://raw.githubusercontent.com/piklen/manmankan/main/scripts/install.sh | bash`

### Added · 防御纵深 + 故障可观察

- **`KAN_DATA_AVAIL_OFFSET_MIN` env var**：跨时区 / WSL2 UTC / Docker 容器用户自救
  - 默认 15:30 北京时间 · 设 `KAN_DATA_AVAIL_OFFSET_MIN=510` → WSL2 UTC 也能识别盘后
- **`KAN_WORKERS` env var**：弱网 / 限流时手动降并发
  - 默认 `min(cpu_count*2, 12)` · 设 `KAN_WORKERS=3` → 强制 3 并发
- **故障 debug 日志**：`_read_cutoff_from_parquet` 异常路径加 debug logging ·
  用户开 `KAN_DEBUG=1` 才显示

### Changed · UX 散户化

- **日期格式压缩**：scan / trend / info / low / high 5 处 title
  - 同年隐藏 year：`数据截止 05-12 收盘`（旧 `2026-05-12`）
  - 当天 fetched_at 只显示时间：`16:35 拉取`（旧 `2026-05-13 16:35`）
  - 节省 ~16 char title 长度 · 80 列窄屏不溢出
- **stale 警告改散户语言**：
  - 旧：`数据截止 X · 应有最近交易日 Y · 建议 kan fetch --force 更新`
  - 新：`当前缓存到 X 收盘 · 最近交易日是 Y · 数据滞后 N 天 / 运行 kan fetch --force 拉取最新数据`
  - 关键升级：显式算"滞后 N 天" · 散户秒懂
- **盘中警告改散户语言**：
  - 旧：`当前盘中 · 数据持续变动 · 涨跌停标记可能瞬时反转`
  - 新：`当前盘中 · 数据每秒变动 · 现在标的『涨停』可能下一秒打开 / 建议盘后 15:30 后再看(数据 final)`
- **双警告互斥渲染**：`if/if` → `if/elif` · stale 状态下 fetch 后会重判 intraday · 减少噪音
- **数据补全 UX 改善**：
  - 移除 v0.0.4.5 一次性迁移文案（对老用户冗余）
  - spinner description 加 stale 总数：`⏳ 补数据 · 169 只 stale · 最近: 寒武纪`
  - 用户看到"169 只"立刻明白为什么这么多只在拉
- **并发数自适应**：max_workers 硬编码 5 → `min(cpu_count*2, 12)` 启发式
  - 8 核 Mac：5 → 12 并发（首次补全 169 只时间减半）
  - 16 核 Mac Studio：cap 12 防 akshare 限流
  - akshare 是 I/O bound · `cpu_count*2` 比 `cpu-1` 更合理

### Fixed · 交易日历防御纵深

- **`latest_trade_date()` 不再抛 RuntimeError**：akshare 失败 + cache 损坏双失败时
  退化 weekday 启发式 + stderr warning
- **缓存内容 sanity check**：三 invariant（count > 5000 · year < 2010 · max date > today-30）·
  失败 cache miss
- **`chmod 0o600` 真校验**：不再静默 `contextlib.suppress(OSError)` ·
  失败 stderr warn + 显示实际 mode
- **akshare 返回值校验**：DataFrame 空 / 缺列 / count 过少都触发 sanity 失败
- **`_read_cache` except 缩窄**：`except Exception` →
  `except (JSONDecodeError, ValueError, OSError)` + stderr warn
- **`_trade_dates_memo` 加锁**：threading.Lock + double-checked locking ·
  防 fetch_batch 多 worker 并发首调

### Tests

- `tests/test_trading_calendar.py` · 17 case（production 故障 + sanity 边界 + env var override + thread-safety）
- `tests/test_cli_helpers_format.py` · 11 case（compact helpers + 文案 grep + if/elif）
- `tests/test_auto_workers.py` · 12 case（auto cpu_count + KAN_WORKERS env + 文案 grep）
- `tests/test_cr4_coverage.py` · 2 case（lex sort）
- **全套 290 passed**（260 baseline + 30 新 · 0 regression）
- ruff check kan/ tests/ · All checks passed

### Migration

升级方式：
```bash
uv tool install --upgrade manmankan   # uv 用户
pipx upgrade manmankan                 # pipx 用户
pip install -U manmankan               # pip 用户
```

或者用一键脚本 (mac / Linux):
```bash
curl -LsSf https://raw.githubusercontent.com/piklen/manmankan/main/scripts/install.sh | bash
```

跨时区用户:
```bash
export KAN_DATA_AVAIL_OFFSET_MIN=510   # WSL2 UTC 系统 (中国 23:30 = UTC 15:30)
```

弱网或自定并发:
```bash
export KAN_WORKERS=3   # 手动降到 3 并发
```

升级后无需任何手动操作 · 自动生效。

## [0.0.4.6] - 2026-05-13

### Fixed · zsh/bash 命令补全报错 hotfix

**主诉 case**：用户输入 `kan upd<Tab>` 触发 zsh 命令补全时报错：
```
_arguments:comparguments:327: invalid argument: 是否启用「以后自动升级」
```

**根因**：v0.0.4.5 发布后，已升级用户 config 中 `auto_update` 仍是 `None`（默认值，
从未选过偏好）。zsh 补全调用 `kan` 子进程拿候选项时触发 `_check_updates_atexit` hook：

1. typer 注入的补全脚本调用：
   `eval $(env _TYPER_COMPLETE_ARGS="kan upd" _KAN_COMPLETE=complete_zsh kan)`
2. 该 `kan` 子进程的 stdout 被 zsh `eval $(...)` 捕获，当 `_arguments` spec 解析
3. Python 退出时跑 atexit，检测到新版本 + `auto_update is None` → 进入"首次询问"
   分支，调 `typer.prompt(...)`
4. prompt 文本「是否启用「以后自动升级」 [y/n/skip]:」默认写到 stdout → 被 zsh
   `eval` 抓走 → `_arguments` 把这串中文当 spec 解析 → 报错

**第二道护栏失效**：旧 isatty 判定用 `or`（`stdout.isatty() or stderr.isatty()`），
补全场景 stdout 被 pipe（非 tty）但 stderr 仍是 tty，hook 错误判为"还是可交互"没跳过。

**修复方案**（双护栏冗余）：
- **新增 `_is_shell_completion_run()`**：检测 `_KAN_COMPLETE` / `_TYPER_COMPLETE_ARGS`
  任一被设置 → 两个 atexit hook 立即 return，不输出任何字符。
- **isatty 判定从 `or` 改为 `and`**：抽象为 `_is_interactive_session()`，stdout 和
  stderr 都是 tty 才算可交互；pipe 场景（包括 `kan info | grep`）也不弹 prompt。
- **`_auto_install_completion` 同步加 completion 护栏**：补全子调用绝不允许写
  shell rc 文件（用户没主动 `kan completion install`）。

**影响范围**：
- v0.0.4.5 用户升级后第一次 Tab 补全必复现（auto_update 偏好未保存）
- v0.0.4.6 完全静默补全调用，主流程 prompt 行为不变（交互式终端仍可询问）
- 测试：新增 `tests/test_atexit_completion_isolation.py` 7 个回归测试 + 全量 248 绿

**自查 / 复测命令**：
```bash
# 升级前复现（v0.0.4.5）：
kan upd<Tab>
# → _arguments:comparguments:327: invalid argument: 是否启用「以后自动升级」

# 升级后（v0.0.4.6）：
kan upd<Tab>
# → 干净显示候选项 update · 无报错
```

## [0.0.4.5] - 2026-05-13

### Fixed · 数据时效性核心修复（v0.0.4.4 及之前用户必装）

**主诉 case**：用户跑 `kan scan` 看到大族激光 002008 / 长电科技 / 风华高科等股票显示
"涨停"标签 · 但实际今天这些股票并未涨停。

**根因**：凌晨 02:55 跑过一次 `kan fetch` 后，缓存文件 `mtime` 日期已经是"今天"，
但 K 线数据实际只到"昨天"（A 股 15:00 才收盘）。旧的 `_is_cache_fresh()` 判定
`mtime_date == today()` 为 True · 整天不再触发刷新 · `scan` 显示的"涨停"是昨日
真实涨停名单 + UI 标题错配为"今日更新"。

**修复方案**：
- **缓存新鲜度判据从 mtime → K 线 date 列**：`_is_cache_fresh` 改为读 parquet
  最后一行 `date` 列 · 对比"应有最近交易日"（基于 A 股交易日历 + 收盘时段）。
- **新增 `kan/trading_calendar.py` 模块**：封装 akshare 交易日历（7 天本地缓存）+
  市场相位判定（pre/intraday/post/closed_day）+ `latest_trade_date(now)` 工具函数。
- **标题分离展示"数据截止 X 收盘 · Y 拉取"**：scan / info / low / high / trend 全部
  改为双字段展示 —— "数据截止"是 K 线 cutoff 日期 · "拉取"是文件 mtime · 严格分离
  语义，用户一眼分辨数据时效性。
- **盘中相位警告**：盘中（9:30-15:00）跑 scan 时显示 "⚠️ 当前盘中 · 数据持续变动 ·
  涨跌停标记可能瞬时反转"，防止用户基于实时变动数据做决策。
- **stale 警告升级**：缓存数据 cutoff 落后应有交易日时显示 "⚠️ 数据截止 X · 应有
  最近交易日 Y · 建议 `kan fetch --force` 更新"。

### Changed · 升级体验

- **首次升级到 v0.0.4.5 时第一次 scan 会全量刷新缓存**（30-60s · 一次性）· 因为旧
  缓存按新判据全部判 stale · `_auto_fetch_stale` 自动触发。之后每天只补 1-2 只
  增量。这是预期行为 · 不是性能回退。

### Tests

- 新增 `tests/test_data_freshness.py` · 17 个 case 覆盖 5 类场景：
  - 凌晨 02:55 反模式 smoking gun（mtime 今天 + K 线昨天 → 必须判 stale）
  - 盘后 16:00 / 盘中 14:00 / 盘前 09:00 三相位
  - 周六周日 → 期望周五
  - 长假后第一天 → 期望节前最后交易日
  - 15:30 阈值边界（前后 1 分钟）
- 全套 241 测试通过 · 0.7s · ruff clean。

## [0.0.4.4] - 2026-05-12

### Fixed · ***REMOVED***溃修复（升级用户必装）

- **依赖版本范围加严**：typer / rich / pandas / numpy / pydantic / akshare / pyarrow / baostock
  全部加上 SemVer 上限，防止用户从 PyPI 安装时拉到未来不兼容的大版本。
  v0.0.4.3 ***REMOVED***溃就是这个原因（用户拿到 pandas 3.0 / typer 0.25 / rich 15
  这些跟当前代码不兼容的版本）。
- **升级走 force-reinstall**：`kan update` 之前用 `uv tool upgrade` / `pipx upgrade` /
  `pip install --upgrade`，遇到老的本地缓存 `.so` 文件不会重新下载，macOS
  Gatekeeper 会拒载老的缓存文件。现在统一改为 `--reinstall` / `--force` /
  `--force-reinstall`，每次升级都是完整重装。
- **升级后跑导入烟雾测试**：升级文件下载成功不代表装得起来。现在 `kan update`
  在升级成功后跑一次 `import kan; from kan import scanner, fetcher, watchlist`
  smoke test，import 失败会显示 "升级文件已下载但导入失败 · 建议手动 reinstall"。
- **scanner.py 模块改 lazy import**：把 pandas 从顶层 import 改为函数体内 lazy
  import，避免任意路径意外加载 pandas 时跳出 spinner 保护。
- **顶层 ImportError catch + 行动建议**：`kan` 主入口包了一层 ImportError 处理，
  装机不完整时不再抛 60+ 行 traceback，而是显示：
  ```
  ❌ kan 安装文件不完整 (...)
  这通常发生在 kan update 升级中途被打断 · 或上游 deps 版本错位。
  请运行：uv tool install manmankan --reinstall （或 pipx install manmankan --force）
  ```

### Fixed · 用户体验一致性

- **kan add 错误输入不再静默**：`kan add 999999`（无效代码）/ `kan add 不存在的名字`
  （未找到）/ `kan add 科技`（多匹配）以前是屏幕空白 + Exit 0 静默失败，现在
  显示错误信息并 exit 1。
- **kan info 涨跌符号一致性**：之前 "跌 1 天 · 累计 0.85%" 是正数 + 负方向语义
  冲突，现在跌显示 `▼0.85%`（绿）/ 涨显示 `▲0.85%`（红），跟 `kan trend` 命令
  的详情列对齐。
- **升级成功后建议开新终端**：`kan update` 完成时追加 "建议开新终端窗口跑下次命令 ·
  当前终端有旧进程缓存" 提示，避免同一 shell 进程 .pyc cache 残留导致的长尾问题。

### Security · 用户数据 + 发版门禁加固

- **用户数据文件权限收紧**：`~/.local/share/kan/` 目录 mode 0700，`watchlist.json` /
  `config.json` 文件 mode 0600。之前 mode 0644 在共享 macOS / 多账户 Linux 上
  其他用户可读取用户的自选股清单（金融持仓画像）。
- **CI workflow permissions 显式声明**：test.yml + release.yml 加 `permissions: contents: read`
  防 supply chain 攻击链（fork PR 中恶意 dep 借继承的 GITHUB_TOKEN 写仓库）。
- **CI 加 privacy scan job**：`bash scripts/check-privacy-leaks.sh` 作为必绿 job ·
  之前依赖本地 pre-commit hook（`--no-verify` 可绕开）。
- **CONTRIBUTING.md 明示 `git config core.hooksPath .githooks`**：贡献者必须激活
  本地 pre-commit hook 才能拦住隐私词泄漏。

### Added · CI 防回归 hard gate

- **release.yml 加 post-publish smoke matrix**：发版后 sleep 60s 等 PyPI CDN 同步，
  在 ubuntu/macos × uv/pip × python3.11/3.12 矩阵跑 clean install + `kan scan --help`
  等核心命令，验证 entry point + import chain。**直接挡住 v0.0.4.3 类***REMOVED*** ship**。
- **test.yml 加 tty-test job**：用 `script -q -c "..."` 在 PTY 下跑
  `tests/test_cli_silent_period.py`，覆盖之前 CI `-m "not tty"` 排除的真 wrapper 路径。

### Tests

- 新增 `_maybe_print_boot_banner` 4 个参数化测试：白名单 + TTY / 白名单外 /
  `--help` / `KAN_NO_BOOT_BANNER=1` env，覆盖所有分支。
- 新增 cold-start invariant: `import kan.scanner` 时 pandas/numpy 不应出现在
  sys.modules（subprocess 隔离验证）。

### Docs

- README 第 14 行版本横幅同步到 v0.0.4.4（v0.0.4.3 因***REMOVED***溃已 yank）。
- README 30 秒上手块前加 uv 安装提示（`curl -LsSf https://astral.sh/uv/install.sh | sh`）。
- README 加"故障排查 FAQ"段（装坏了 / 升级失败 → `uv tool install --reinstall` 引导）。

## [0.0.4.3] - 2026-05-12 [YANKED]

> ⚠️ **本版本已从 PyPI yank** · 用户端装机即崩（numpy C-extension macOS 代码签名 +
> typer / rich / pandas 版本错位 + 顶层 `import pandas` 跳出 spinner 保护）。
> 请直接升级到 v0.0.4.4：`uv tool install manmankan --reinstall`

### Fixed · 测试基线校准

- `tests/test_cli_silent_period.py` 改用真实 `kan` 入口测试（`os.execvpe`）。
  之前用 `python -c bootstrap` 启动跳过了 wrapper 和 entry point 开销，导致测试
  数据偏低。
- 测试基线从 200ms 调整为 400ms（200ms 保留为理想目标，真实 wrapper 路径
  受 Python 启动物理开销约束）。
- 新增 `scripts/measure_slo.py`，统一用真实 `kan` 命令测启动延迟。

### Performance · 启动反馈

- `kan add/scan/fetch/low/high/info/trend` 在 TTY 下先输出 `⏳ 启动中...` 到
  stderr，避免按回车后空屏。真实 wrapper 路径下首个可见反馈约 10-20ms。
- 支持 `KAN_NO_BOOT_BANNER=1` 关闭该早期提示。

## [0.0.4.2] - 2026-05-12

### Changed · 启动阶段反馈细化

- 数据命令启动分阶段提示：`⏳ 加载数据模块...` → `⏳ 检查缓存...` → `⏳ 拉取数据...`，
  让长 watchlist 用户的等待阶段更可见。
- `kan fetch` / `kan info` 的单只拉取也进入 stderr spinner。
- 批量自动更新进度条文案改为 `⏳ 拉取数据 · 最近: <名称>`。

### Fixed · 数据源切换可见化

- A 股代码表主源 baostock 失败时显式提示正在切换 akshare 备用源，避免首次
  `kan add` 因 fallback 变慢而看起来无解释。

### Docs

- 新增 `docs/reviews/v0.0.4.md` 记录启动反馈实测数据。

## [0.0.4.1] - 2026-05-12

### Fixed · 启动反馈覆盖全数据命令

- `kan fetch` / `kan low` / `kan high` / `kan info` / `kan trend` 在加载
  `fetcher` / `scanner` / `render` 等数据模块前先显示 stderr spinner，避免按
  回车后到第一帧输出之间空屏。
- 测试覆盖扩展到上述命令的首帧延迟。

## [0.0.4.0] - 2026-05-12

### Fixed · 数据命令启动反馈缺失

- `kan/fetcher.py` 顶层不再 import `akshare` / `pandas`，改为函数体内按需加载，
  避免 `kan` 启动时一次性付掉数据模块全部加载成本。
- 新增 `_with_heavy_imports_spinner(console, message)` 统一封装，在重模块加载前
  打开 `console.status(...)` 避免空屏。
- `kan scan` 入口用 stderr spinner 包住 `fetcher` / `scanner` / `render` 等模块的
  按需加载，首次反馈从约 500-700ms 提前到 200ms 内。

### Docs

- 新增 `docs/reviews/v0.0.3.md` 记录 v0.0.3 启动反馈实测和遗漏分析。

### Docs

- 新增 `docs/reviews/v0.0.3.md` 记录 v0.0.3 启动反馈审计和漏修原因。

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
- `kan add` 用户视角：按回车后 0 启动反馈 · ⏳ 加载提示立即可见

**实测收益**（首次添加股票场景）：
- 冷启动 启动反馈 ~10s → 0s（spinner 立即可见）
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

[Unreleased]: https://github.com/piklen/manmankan/compare/v0.0.4.7.1...HEAD
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
