# 多窗口并行开发

> 用 git worktree 在多个终端窗口并行推进 manmankan 开发的隔离与编排方法。
> 铁律:**worktree 隔离文件冲突 · 契约先行消解语义冲突 · 串行 merge 防集成事故 —— 三者缺一不可。**

## 适用场景

一次推进 **≥ 2 个互相独立的 workstream** 时,开多个 worktree 并行加速。
典型:一个 minor 功能拆成数据层 / 逻辑 / CLI / 测试多块。

不适用:
- 改动 < 100 行 / 单文件修补 —— 并行协调开销 > 收益,顺序做即可
- 强线性依赖、切不出独立 lane 的任务 —— 并行度为 0

## 角色

| 角色 | 职责 | 不做 |
|---|---|---|
| **协调端**(维护者,main checkout 上) | 写 spec、定契约、切 lane、串行 merge、跑集成测试、收尾清理 | 不写业务代码 |
| **并行端**(N 个,各一个 worktree) | 认领 1 条 lane、只在 lane 内实现、自测、开 PR | 不碰 lane 外文件、不改契约、不并发 merge |

规模:**2 个并行端起步**,跑顺再加。

## 隔离三件套

每个并行端启动时,三层隔离都要做:

| 层 | 隔离什么 | 做法 |
|---|---|---|
| 1 · 文件 | 代码文件不互相覆盖 | `git worktree add`(每个并行端一个) |
| 2 · 依赖 | 各 worktree 的 venv 独立 | 进 worktree 跑 `uv sync` |
| 3 · 运行时 | 不抢共享的用户数据目录 | 各 worktree `export XDG_DATA_HOME=$PWD/.xdg` |

**第 3 层最易漏。** manmankan 跑起来会往 `$XDG_DATA_HOME/kan/` 写 watchlist、parquet 缓存、snapshots(见 `kan/paths.py`)。多个 worktree 同时跑 `kan scan` 做验证,会抢同一个用户数据目录 —— 一个写 watchlist,另一个读到脏数据。`kan/paths.py` 支持 `XDG_DATA_HOME` 覆盖,每个 worktree 设独立的就隔离开了。

worktree 还要注意:
- worktree 只带 tracked 文件 —— `.venv` 是 gitignored,不会跟过去 → 进 worktree 先 `uv sync` 重建(uv 全局 cache,几秒)
- pre-commit hook 不自动激活 → 每个 worktree 跑 `git config core.hooksPath .githooks`(隐私扫描 + ruff lint)

## kan/ 的 lane 切分

`kan/` 包已按命令域模块化,天然能切出文件白名单两两不重叠的 lane:

| lane | 文件白名单 | 对应测试 |
|---|---|---|
| scan 域 | `kan/cli_scan_cmds.py` `kan/scanner.py` | `tests/test_scan_cli.py` `tests/test_scanner.py` |
| watchlist 域 | `kan/cli_watchlist_cmds.py` `kan/watchlist.py` | `tests/test_watchlist*.py` |
| trend 域 | `kan/cli_trend_cmds.py` | `tests/test_trend_cli.py` |
| 数据层 | `kan/fetcher.py` `kan/trading_calendar.py` | `tests/test_fetcher.py` `tests/test_trading_calendar.py` |

**切 lane 铁律**:每条 lane 的文件白名单两两不重叠。两条 lane 编辑同一文件 = 必然 merge conflict,要么排队、要么先拆文件。

## hotspot 文件

worktree 防文件覆盖,防不了"两个并行端改同一个共享文件"的语义冲突。manmankan 的 hotspot:

- `kan/app.py` `kan/cli.py` —— 命令注册
- `kan/models.py` —— 共享数据模型
- `kan/config.py` —— 全局配置
- `pyproject.toml` `uv.lock` —— 依赖 / 版本号
- `CHANGELOG.md` —— 变更日志

规则:
1. 一个 sprint 内,每个 hotspot 文件**最多一条 lane 能碰**
2. 多条 lane 都要改的共享文件 → 收进 **Lane 0** 先做完
3. **`CHANGELOG.md`**:并行端一律不碰,各自写进 PR 描述,协调端 merge 后统一补

## 流程 · 6 步(契约先行)

「数据层 → 逻辑 → CLI」是垂直依赖链,纯并行做不到。契约先行把依赖在设计阶段消解掉。

### Step 0 · 清场 + baseline(协调端)
清化石分支;main 上跑 `uv run pytest` + `uv run ruff check kan/`,确认全绿。这是 baseline —— 之后任何新失败都能归因到具体并行端,而非"本来就坏的"。

### Step 1 · 写 spec + 定契约(协调端)
列出跨 lane 共享的所有契约:`kan/models.py` 新增数据结构、跨层函数签名、`kan/config.py` 新配置项、新依赖。判断能否切**垂直切片**(每条 lane 是能独立测的完整切片):能 → 真并行;不能(强垂直依赖)→ 走 Lane 0。

### Step 2 · Lane 0 地基先行(协调端,串行)
把契约落成代码再 merge 进 main:共享数据结构、接口 stub(空实现 + 类型签名 + docstring)、新依赖。此后 main 上有了所有 lane 都依赖的地基,后续 lane 基于它开 worktree。

### Step 3 · 开 worktree(每个并行端)
基于 Lane 0 后的 main 开 worktree → 做完隔离三件套 → 跑一遍测试确认 worktree baseline 也绿。

### Step 4 · 并行实现
每个并行端只碰自己 lane 白名单内的文件;只填充 Lane 0 留下的 stub,**不改契约**(发现契约不对 → 停下回报协调端,契约一改全 lane 受影响);完成后 `uv run pytest` + `uv run ruff check kan/` 自测全绿 → 开 PR。

### Step 5 · 串行集成(协调端)
PR **一个一个 merge**,按依赖顺序(被依赖的先)。每 merge 一个,跑一次全测试 —— 新失败 = 刚 merge 的 PR 引入。**绝不并发 merge。**

### Step 6 · 收尾(协调端)
删 worktree、删分支(本地 + 远端)、统一补 `CHANGELOG.md`。

## 示例 · 给 `kan scan` 加 `--format md|json`

| 步 | 动作 |
|---|---|
| Step 1 契约 | 定 `Formatter` 接口(`render(data) -> str`)+ `--format` 参数枚举 |
| Step 2 Lane 0 | `kan/render.py` 抽出 `Formatter` 协议 + 把现有 terminal 输出改成第一个实现,merge |
| Step 3-4 并行 | lane A = markdown formatter(新文件)· lane B = json formatter(新文件)—— 两个并行端各写一个**新文件**,零重叠 |
| Step 5 | 两个 PR 串行 merge |

要点:契约(`Formatter` 接口)在设计阶段先定死,两个 formatter 并行端各自实现协议、互不依赖 —— 依赖被前移消解,运行阶段才是真并行。

## 护栏速查

| 风险 | 对策 |
|---|---|
| worktree 不带 `.venv` | 进 worktree 先 `uv sync` |
| 多 worktree 跑 manmankan 污染用户数据目录 | 各 worktree `export XDG_DATA_HOME=$PWD/.xdg` |
| 并发 git 命令损坏共享 `.git` metadata | git 写操作串行,一次一个 worktree |
| pre-commit hook 没激活 | 每个 worktree `git config core.hooksPath .githooks` |
| 公开输出隐私泄漏 | commit 前 `bash scripts/check-privacy-leaks.sh` |
| hotspot 语义冲突 | 一个 sprint 内每个 hotspot 文件只一条 lane 碰 |
| stale worktree 堆积 | Step 6 强制清理,定期 `git worktree prune` |

## 反模式

| 反模式 | 后果 |
|---|---|
| 跳过 Step 1 契约,直接并行 | 各并行端瞎猜接口,集成时语义冲突 |
| 并行端碰 lane 白名单外的文件 | merge conflict / 越权改动 |
| 并行端自行改契约不回报 | 契约失同步,其他 lane 全部跑偏 |
| 并发 merge 多个 PR | 集成事故无法归因 |
| 强线性依赖任务硬上并行 | 并行度为 0,只剩协调开销 |
| 小改动(< 100 行)也开 worktree 编排 | 过度工程,协调成本 > 收益 |
| sprint 结束不清 worktree / 分支 | 化石堆积,下次 worktree 命名撞车 |
