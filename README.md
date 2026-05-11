# 慢慢看 · manmankan

> A 股自选股「位置感」CLI · **不告诉你买什么，只告诉你它现在站在哪**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/manmankan.svg)](https://pypi.org/project/manmankan/)
[![PyPI downloads](https://img.shields.io/pypi/dm/manmankan.svg)](https://pypi.org/project/manmankan/)
[![Tests](https://github.com/piklen/manmankan/actions/workflows/test.yml/badge.svg)](https://github.com/piklen/manmankan/actions/workflows/test.yml)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](https://github.com/piklen/manmankan/releases)

慢慢看是一个**纯命令行**的 A 股自选股位置感工具。它把电商「慢慢买」的「先看历史价位再决策」迁移到股市:把你 30 只自选股在 3、5、7、10、15、30、60、90、120、180 日窗口内的位置百分位**一屏显示**,把「同时触及多个低点」标成共振信号,然后**闭嘴**——剩下的判断,你自己做。

> 📦 **当前版本 v0.0.4.4**(Alpha · 装机修复 + 7 角色总部 review) · `pip install manmankan` 即装即用 · API 在 1.0 前可能调整。
>
> ⚠️ **v0.0.4.3 已从 PyPI yank**(用户端***REMOVED***) · 老用户请 `uv tool install manmankan --reinstall` 升 v0.0.4.4。
>
> 🔒 **100% 本地** · 不要登录 · 不上传自选 · 不推送 · 不广告 · 数据存 `~/.local/share/kan/`(XDG 规范)。
>
> 📡 **数据延时** · 盘后批量拉取前复权日 K 线 · 不适合分钟级短线。

---

## 目录

- [这是给谁用的](#这是给谁用的)
- [30 秒上手](#30-秒上手)
- [真实输出](#真实输出)
- [三个「同时」差异化](#三个同时差异化)
- [安装](#安装)
- [核心命令](#核心命令)
- [Shell 命令补全](#shell-命令补全)
- [数据源 · 缓存 · 涨跌停](#数据源--缓存--涨跌停)
- [数据 / 隐私](#数据--隐私)
- [设计哲学](#设计哲学)
- [不会做什么](#不会做什么)
- [风险与法律免责](#风险与法律免责)
- [路线图](#路线图)
- [文档导航](#文档导航)
- [故障排查 FAQ](#故障排查-faq)
- [开发](#开发)
- [许可证](#许可证)

---

## 这是给谁用的

| 你是 | 慢慢看解决你的什么问题 |
|---|---|
| **A 股长线 / 技术派散户**(30+ 自选 · 月级别周期) | 一屏看完所有自选股的 10 周期位置 + 共振信号,不用切来切去 |
| **拒绝黑箱 / 不信「AI 选股」的玩家** | 只给客观位置百分位,不给「评级 / 目标价 / 必涨」· 算法开源可审 |
| **隐私敏感 / 不愿登录 broker app 的人** | 完全本地 · 没账号 · 没推送 · 没广告 · `kan uninstall` 一键彻底清 |
| **量化 / 自动化爱好者** | CLI + parquet 缓存可直读 · JSON 快照按日归档 · 脚本能调 |

**这工具不适合**:T+0 短线投机者(数据延时,日 K)、不会用终端的小白(先得装 Python)、期待 AI 选股结论的人(合规红线说不)、港股 / 美股 / 期货用户(仅 A 股)。

---

## 30 秒上手

> 💡 **没装 uv?** 一行装好: `curl -LsSf https://astral.sh/uv/install.sh | sh` ([uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/))

```bash
uv tool install manmankan          # 一行装好(推荐)
kan add 600519 茅台 601318          # 名称 / 代码混搭
kan scan                            # 一屏看完位置 + 共振信号
```

> 装坏了? 跑 `uv tool install manmankan --reinstall` (或 `pipx install manmankan --force`) ·
> 详见 [§故障排查 FAQ](#故障排查-faq)

第一次跑会有两次「看起来卡住」的时刻,**这是正常的**:

- **首次 `kan add`**:拉一次全市场 A 股代码-名称表(5-15s,baostock 主源)。之后 7 天内秒级响应。
- **首次 `kan scan`**:先显示「加载数据模块 / 检查缓存 / 拉取数据」阶段提示,再自动多源拉取自选股 K 线数据(并发 5)。30 只股票约 1-2 分钟,180 天日 K。之后只补今天的增量。

**进度条都是真实的**——失败会跳过单只继续跑,Ctrl-C 可中断,已拉到的数据已保存,下次 `kan scan` 自动续。

---

## 真实输出

> 以下是真实终端输出格式,数据为占位演示(三大指数仅用于示意,**不构成任何形式的推荐**)。

### `kan scan` · 全景多周期位置扫描

```
慢慢看 · 自选股位置扫描 · 低点模式 · 2026-05-10 14:30 更新
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━┓
┃股票              ┃    现价 ┃  3日 ┃  5日 ┃  7日 ┃ 10日 ┃ 15日 ┃ 30日 ┃ 60日 ┃ 90日 ┃ 120日 ┃ 180日 ┃共振 ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━┩
│沪深300 000300    │ 3960.20 │ [2%] │ [3%] │ [3%] │ [3%] │ [3%] │ [5%] │ [5%] │ 10%  │  15%  │  18%  │ ×6  │
│上证50  000016    │ 2670.10 │ [3%] │ [4%] │ [4%] │  9%  │ 10%  │ 14%  │ 18%  │ 20%  │  22%  │  25%  │ ×4  │
│中证500 000905    │ 5690.50 │ [0%] │ [0%] │ [0%] │ [1%] │ [1%] │ [1%] │  3%  │  8%  │  12%  │  16%  │ ×8  │
└──────────────────┴─────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴───────┴───────┴─────┘

  [x%] = 触及低点(≤5%) · 0%=区间最低 · 越低=越接近 N 日最低价

⚠️ 创新低 ≠ 见底 · 创新高 ≠ 顶 · 历史价格不预示未来 · 仅供参考,不构成投资建议
```

**怎么读这张表**:`[x%]` 带方括号 + 高亮 = 触及低点(≤5% 区位)。`×N` = 共振次数,数字越大,这只股票同时触及越多周期的低点。窄屏时自动选周期子集,共振列始终显示。

### `kan info 600519` · 单只详情

```
慢慢看 · 贵州茅台 600519 · 2026-05-10 14:30 更新
  现价 1680.50 · 跌3天 · 累计 -2.45%

┏━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┓
┃周期 ┃    最低 ┃    最高 ┃   位置 ┃
┡━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━┩
│ 3日 │ 1670.00 │ 1715.00 │  23%   │
│ 5日 │ 1670.00 │ 1740.00 │  15%   │
│30日 │ 1610.00 │ 1820.00 │  33%   │
│180日│ 1450.00 │ 1820.00 │  62%   │
└─────┴─────────┴─────────┴────────┘

  低点共振 ×0 · 高点共振 ×0
```

### `kan trend --down 5 --latest 7` · 连跌看板

```
慢慢看 · 连续涨跌看板 · 收盘价口径 · 连跌≥5天 · 2026-05-10 更新
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓
┃股票              ┃   现价 ┃ 连续 ┃  累计 ┃ 05-10  ┃ 05-09  ┃ 05-08  ┃ 05-07  ┃ 05-06  ┃ 05-05  ┃ 04-30  ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩
│示例A   600xxx    │  12.30 │跌7天 │ -8.5% │ ▼1.20% │ ▼0.85% │ ▼1.50% │ ▼2.10% │ ▼1.20% │ ▼0.95% │ ▼0.70% │
│示例B   000xxx    │  35.60 │跌5天 │ -4.2% │ ▼0.50% │ ▼0.85% │ ▼1.10% │ ▼0.95% │ ▼0.80% │ ▲0.30% │ ▲0.45% │
└──────────────────┴────────┴──────┴───────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
```

涨停 / 跌停按板块差异化判定:主板 ±10% / 创业板 / 科创板 ±20% / 北交所 ±30% / ST ±5%(2026-07-06 起 ±10%)。

---

## 三个「同时」差异化

现有工具(东方财富选股器、富途、i 问财等)每次只能按**单一周期**条件筛选,要看 30 只自选股谁最接近低点要切来切去。慢慢看的差异化 = 三个「同时」:

1. **同时多周期** — 10 个周期一屏(3/5/7/10/15/30/60/90/120/180 日),不用切
2. **同时多自选** — 横向比较「我的 30 只股谁最接近低点」,排序自动按共振优先
3. **同时标共振** — 「某股同时触及 10 日 + 60 日 + 120 日低点」=  `×3` 标记,**只是参考,不是信号**

---

## 安装

要求 Python 3.11+。如果你 Python < 3.11,用 [uv](https://docs.astral.sh/uv/) 一行装好:

```bash
uv python install 3.11
```

> 镜像源(清华 / 阿里等)同步最新 PyPI 版本约需数日。装不到最新版时加 `--index-url https://pypi.org/simple/` 直连官方源。

### 推荐:`uv tool install`(隔离环境 + 全局可用)

```bash
uv tool install manmankan
kan --version
```

uv 自带依赖管理,不需要自己建 venv,不会撞 [PEP 668](https://peps.python.org/pep-0668/)。**这是 macOS Homebrew Python 用户最稳的路径**。已验证 macOS / Linux。

### `pipx` 路径

```bash
# 没装 pipx? 先装: brew install pipx (macOS) · apt install pipx (Linux)
pipx install manmankan
kan --version
```

### 标准 `pip`(必须在虚拟环境内)

⚠️ **macOS Homebrew Python / Debian 12+ / Ubuntu 23+ 等现代发行版默认禁止全局 `pip install`** —— [PEP 668](https://peps.python.org/pep-0668/) 安全机制。直接 `pip install manmankan` 会报 `error: externally-managed-environment`。

```bash
python3 -m venv ~/.kan-venv
source ~/.kan-venv/bin/activate
pip install manmankan
kan --version
# 退出 venv: deactivate
# 下次用 kan 前: source ~/.kan-venv/bin/activate
```

> 或直接用上面的 **`uv tool install`** —— 一行搞定,不需要折腾 venv。

### 从源码

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync
uv run kan --version
```

---

## 核心命令

> 慢慢看自带中文速记。任何时候忘了用法跑 **`kan help`**(或 `kan` / `kan --help`,三者等价)即可。下面只列每个命令的核心用法 + 一个例子。

### 自选股管理

```bash
kan add 600519 茅台 601318     # 代码 / 名称混搭 · 批量
kan remove 茅台 五粮液         # 代码 / 名称都行 · 批量
kan list                       # 查看自选列表(末尾显示总数)
kan import stocks.csv          # CSV 批量导入(每行一个代码 · 上限 10 MB)
kan clear                      # 清空(带确认)
```

### 位置扫描 `kan scan`

```bash
kan scan                       # 全景扫描 10 周期(低点模式 · 默认)
kan scan --high                # 高点模式
kan scan -S                    # 只显示有共振信号的股票(--signal)
kan scan --diff                # 增量模式 · 显示与上次扫描的变化
kan scan --exclude-st          # 排除 ST/*ST 股票
```

**排序规则**:
- 低点模式:共振次数降序 → 3 日位置百分位升序 → 5 日 → ... → 180 日(越接近低点越靠前)
- 高点模式:共振次数降序 → 3 日位置百分位降序 → 5 日 → ... → 180 日(越接近高点越靠前)
- 终端宽度 < 130 列时自动选周期子集(100/90/80/70 列各档),共振列始终显示

### 单周期低/高点筛选

```bash
kan low 60                     # 谁在 60 日低点(≤5%)?
kan low 30 60 120              # 多周期一次看
kan high 30                    # 谁在 30 日高点(≥95%)?
```

> 周期范围 2-360 天 · 多周期空格分隔。

### 单只详情 `kan info`

```bash
kan info 600519                # 全周期位置 + 现价 + 连续涨跌 + 共振 + ST/涨跌停标记
```

### 连续涨跌看板 `kan trend`

```bash
kan trend                      # 默认看板(不筛选)
kan trend --down               # 只看连跌 ≥ 3 天(默认值)
kan trend --down 5             # 只看连跌 ≥ 5 天
kan trend --up 5               # 只看连涨 ≥ 5 天
kan trend --latest 7           # 展示近 7 天涨跌详情
kan trend --candle             # 阳线阴线口径(默认是收盘价 vs 前日收盘)

kan trend --down 5 --latest 7 --candle    # 任意组合
```

> N 范围 2-30 天 · `--latest` 展示日期数会按终端宽度自动收缩。

### 数据管理

```bash
kan fetch                      # 拉取数据(通常不需要 · scan 自动更新)
kan fetch --force              # 强制刷新(忽略今日已更新的缓存)
kan fetch 600519 000858        # 只拉指定股票
```

### 自动更新

```bash
kan update                     # 检查并升级到最新版本(默认带确认)
kan update --yes               # 跳过确认(脚本 / CI 用)
kan update --check             # 仅检查不升级
```

> 💡 任意 `kan` 命令运行后会自动检查 PyPI 最新版本(主命令完成后才查 · 不阻塞)。
> 首次发现新版本会询问是否「以后自动升级」(y / n / skip):
> - 选 **y** → 后续自动调对应包管理器升级(uv tool / pipx / pip)
> - 选 **n** → 不再自动升级 · 仅每周一次 hint
> - 选 **skip** → 下次启动再问
>
> 想关闭这个自动行为:`export KAN_NO_UPDATE_CHECK=1` 后再跑。
> daily cache:同一天再启动跳过网络请求,3s timeout 失败静默不影响主命令。

### 卸载

```bash
kan uninstall                  # 删除所有本地数据 + 输出软件包卸载命令(默认带确认)
kan uninstall --yes            # 跳过确认(脚本 / CI 用)
kan uninstall --keep-data      # 只看包卸载命令 · 不删数据
```

> `kan uninstall` **不会**自动删软件包本身(chicken-and-egg · `kan` 无法删自己运行的进程)。它会自动检测安装方式(`uv tool` / `pipx` / `pip` / `venv`)后提示对应卸载命令。

---

## Shell 命令补全

```bash
kan completion install         # 自动检测当前 shell · 安装补全脚本
kan completion install zsh     # 显式指定 shell(zsh / bash / fish / powershell)
```

支持 zsh / bash / fish / powershell。**安装后 `kan s<Tab>` → `kan scan`,`kan trend --<Tab>` → 列出所有 flag**。

> 💡 慢慢看在你**第一次跑任意 `kan` 命令时会自动安装补全**(只跑一次 · 标记文件防重复 · 非 TTY 环境跳过)。
> 想关闭这个自动行为:`export KAN_NO_COMPLETION_AUTOINSTALL=1` 后再跑。

---

## 数据源 · 缓存 · 涨跌停

### 4 源 fallback K 线拉取

数据来自 [AKShare](https://github.com/akfamily/akshare) 体系,但慢慢看做了**多源 fallback** 防单源失效:

```
fetch_kline(symbol) →
  1. baostock (独立服务器 · 免熔断 · 主路径 · 实测最稳)
  2. 新浪    (akshare.stock_zh_a_daily · 免登录 · 数值精度跟 baostock 对齐)
  3. 东财    (akshare.stock_zh_a_hist · push2his 对部分 IP 段持续封禁,常 fail)
  4. 腾讯    (akshare.stock_zh_a_hist_tx · 仅价格可信 · amount 字段板块语义不一致已 drop)
```

设计依据:akshare GitHub Issue [#6092](https://github.com/akfamily/akshare/issues/6092) / [#6148](https://github.com/akfamily/akshare/issues/6148) / [#7011](https://github.com/akfamily/akshare/issues/7011) / [#6214](https://github.com/akfamily/akshare/issues/6214) —— 东财 push2his 对国内多个 IP 段长期 ban,实测 retry 4 次 5s 间隔无效(持续不是间歇性)。把 baostock 推到主路径,东财降到第三。

> 📡 **使用延时数据 · 不涉及实时行情** · 盘后批量拉取前复权日 K 线。

> ⚠️ **AKShare 数据使用条款**:[AKShare 官方声明](https://github.com/akfamily/akshare) 数据 "仅限学术研究用途(Academic Research Only)"。本工具继承此限制,**仅供个人研究 / 教育用途,不得用于商业产品 / SaaS / 二次分发**。

> ⚠️ **数据可用性依赖上游**:AKShare 与各数据源策略变更可能导致接口失效,本工具不保证数据持续可用。

### 缓存生命周期

| 数据 | 存放 | 生命周期 | 备注 |
|---|---|---|---|
| 日 K 线 | `~/.local/share/kan/data/<code>.parquet` | 当日 mtime = fresh | 跨天自动刷 · `--force` 强刷 |
| A 股代码-名称表 | `~/.local/share/kan/stock_names.json` | 7 天 | baostock(5s)主拉 · akshare(16s)兜底 |
| 自选股 | `~/.local/share/kan/watchlist.json` | 永久 | 原子写(.tmp + replace) |
| 扫描快照 | `~/.local/share/kan/snapshots/<日期>.json` | 240 天 | `kan scan --diff` 用 |

CSV 导入大小上限 10 MB(防误传超大文件 OOM)。

### 跨板块涨跌停规则

`kan scan` 与 `kan trend --latest` 自动标记涨跌停,按板块差异化:

| 板块 | 代码段 | 涨跌停限制 |
|---|---|---|
| 沪市主板 | `6xx` (除 688/689) | ±10% |
| 深市主板 | `000xxx` | ±10% |
| 创业板 | `300xxx` | ±20% |
| 科创板 | `688xxx / 689xxx` | ±20% |
| 北交所 | `8xx / 4xx` | ±30% |
| **ST / *ST** | 任意板块 | **±5%(2026-07-06 之前) → ±10%(之后)** |

ST 涨跌停切换日 2026-07-06 来自沪深北交易所 2026-04 公告,代码内置自动切换。

---

## 数据 / 隐私

慢慢看是 self-hosted CLI · 完全本地运行 · **不上传任何用户数据到远端**。

### 存储路径(XDG Base Directory 规范)

| 目录 | 路径 | 说明 |
|---|---|---|
| 数据根 | `$XDG_DATA_HOME/kan/` 或 `~/.local/share/kan/` | 所有数据存这 |
| K 线缓存 | `~/.local/share/kan/data/` | 每只股票一个 parquet |
| 自选股 | `~/.local/share/kan/watchlist.json` | 明文 JSON · 你可手编 |
| 扫描快照 | `~/.local/share/kan/snapshots/` | `--diff` 模式用 |

### Legacy 路径自动迁移

如果你装过早期版本,数据可能在 `~/.kan/`。**新版本首次启动会自动迁移到 XDG 路径**(stderr 提示 · `kan --version` 等纯查询命令保持 stdout 干净 · 旧目录可手动 `rm -rf ~/.kan/` 清掉)。

### 不会发生的事

- ❌ 不要登录 / 注册账号
- ❌ 不上传你的自选股
- ❌ 不向任何第三方推送你的查询行为
- ❌ 不做任何遥测 / analytics
- ❌ 不联网更新自动安装其他东西

详见 [`SECURITY.md`](SECURITY.md)。

---

## 设计哲学

> **位置感知入口 ≠ 买卖决策出口。**

慢慢看严格定位为**行情数据展示工具**,不包含任何买卖建议、评分评级、策略推荐。每次输出都强制带风险提示,措辞严守「位置 / 区间 / 触及」的客观语言。

### 共振 ×N 怎么用

`×N` 表示同时触及 N 个周期的低/高点(例如同时是 30 日 + 60 日 + 120 日低点 = `×3`)。**这只是一个客观计数**:

- ✅ 它告诉你的是:**这只股票当前价位在多个时间窗口看都接近极值**
- ❌ 它**不告诉**你的是:这是不是底 / 这是不是机会 / 该不该买

短周期(3/5/7 日)与长周期(120/180 日)同时触及,只是数学上的事实。要不要据此行动,完全取决于你自己的研究 / 风险承受 / 资金情况。

### 「位置」的语义边界

「位置百分位」= `(当前价 - N 日最低) / (N 日最高 - N 日最低) × 100`,即当前价在 N 日波动区间内的相对位置:

- `0%` = N 日最低
- `100%` = N 日最高
- `[≤5%]` 标记 = 触及低点(数学定义,非信号)
- `[≥95%]` 标记 = 触及高点(同上)

跌出 N 日新低时,位置百分位会变成新一天的 0%——这只是算法重置,不代表「再创新低」必然意味着什么。

详见 [`docs/compliance.md`](docs/compliance.md)。

---

## 不会做什么

慢慢看在路线图中**明确拒绝**以下方向(避免引入合规风险或脱离工具定位):

- ❌ **实时行情推送** — CLI 工具不适合 · 用 broker app
- ❌ **AI 选股 / 评级 / 信号订阅** — 合规红线
- ❌ **多账户体系 / 云同步** — 单机工具不需要
- ❌ **移动端 App** — H5 已能覆盖未来需求
- ❌ **个股目标价 / 涨跌预测** — 不在能力边界,也不在使命范围

详见 [`docs/roadmap.md`](docs/roadmap.md) 的「不在路线图」段。

---

## 风险与法律免责

**本工具仅供个人研究学习使用,不构成任何投资建议。** 使用者应当独立判断行情数据,自行承担投资决策的全部风险。

- 本工具不推荐任何具体股票
- 不预测涨跌、不给目标价
- 不提供任何形式的投资指导
- 历史价格数据仅供参考,不预示未来表现
- **创新低 ≠ 见底 · 创新高 ≠ 顶**

**核心声明**:

- 本工具开发者**不持有任何证券投资咨询资质**,非持牌投资顾问
- 本工具**不构成荐股 / 投顾 / 信号服务**任何形式
- 用户使用本工具产生的任何投资行为**与开发者无关**
- README 截图中出现的指数/示例代码仅供演示位置扫描功能,**不构成任何形式的推荐与评级**

**A 股市场有风险,投资需谨慎。**

如需将本工具用于商业目的或二次开发,请遵守 [MIT 协议](LICENSE) 并自行确保合规(特别是 [AKShare 数据使用限制](https://github.com/akfamily/akshare))。

---

## 路线图

下一批 patch 三件套(优先级 P0):

1. **`kan alert` 价格提醒**(寄生 `scan` 数据通路 · 阈值穿越 / 涨跌幅超阈值 · 走系统通知中心)
2. **指数基准对照**(自选股扫描时同步给上证 / 深证 / 创业板 / 沪深 300 同周期位置 · 判断「个股弱还是大盘弱」)
3. **Markdown / JSON 输出**(`--format md|json` · 让脚本能调)

完整路线图 + 已知技术债 + 跨板块交易单位备忘见 [`docs/roadmap.md`](docs/roadmap.md)。

> **版本节奏**:patch 累加(`v0.0.1 → v0.0.2 → ...`),不偏好 minor 跨越。

---

## 文档导航

| 文档 | 用途 |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更记录(Keep a Changelog 格式) |
| [`docs/compliance.md`](docs/compliance.md) | 合规红线 / 关键词黑名单 / 强制文案 |
| [`docs/roadmap.md`](docs/roadmap.md) | 路线图 / 架构评审结论 / 三源一致性 / 不在路线图 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 开发环境 / 代码风格 / 公开输出语言规范 / Commit 规范 |
| [`SECURITY.md`](SECURITY.md) | 漏洞报告(Private Vulnerability Reporting) |
| [`AUTHORS.md`](AUTHORS.md) | 贡献者列表 |

---

## 故障排查 FAQ

### kan 装完跑不起来 / `kan scan` 抛一堆 ImportError

通常发生在 `kan update` 升级中途被打断 · 或上游 deps 版本错位。**统一修复**: 强制重装。

```bash
# 你装 kan 用的是哪种工具? 选对应命令:
uv tool install manmankan --reinstall      # uv tool 装的
pipx install manmankan --force             # pipx 装的
pip install --force-reinstall manmankan    # pip 装的
```

如果还不行 · 先彻底卸载再装:

```bash
uv tool uninstall manmankan && uv tool install manmankan
```

### `kan update` 显示已升级但下次还崩

v0.0.4.3 已知问题 · v0.0.4.4 已修复(升级后自动 import smoke test 验证)。如果你还在 v0.0.4.3 · 用上面的命令强制升 v0.0.4.4。

### `kan` 命令找不到 (command not found)

- **uv tool 装的**: 检查 `~/.local/bin` 在 PATH 里
- **pipx 装的**: 跑 `pipx ensurepath` · 重启终端
- **pip --user 装的**: 检查 `python -m site --user-base`/bin 在 PATH 里
- **macOS Homebrew Python**: 可能装到了系统 Python · 改用 uv tool

### 网络 / 数据源连不上

manmankan 主用 baostock · 失败自动 fallback 到 akshare。**两个都失败**通常是网络代理问题:

```bash
unset HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY  # 临时去代理试
kan add 600519                                    # 重试
```

### 想完全卸载 + 删除数据

```bash
uv tool uninstall manmankan       # 卸载程序
rm -rf ~/.local/share/kan         # 删除数据(自选股 + K 线缓存)
```

更多问题请提 [GitHub Issues](https://github.com/piklen/manmankan/issues)。

---

## 开发

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync                       # 安装依赖(含 dev)
uv run pytest                 # 跑测试(目前 164 个)
uv run pytest --cov=kan       # 带覆盖率
uv run ruff check kan/        # lint
```

**贡献前请读 [`CONTRIBUTING.md`](CONTRIBUTING.md)**:

- 公开档案语言规范(中性词 · 不带 AI 工具签名)
- 合规红线(无买卖建议 / 无评级)
- Pre-commit hook 启用:`git config core.hooksPath .githooks` 自动跑 36 禁词扫描

---

## 许可证

[MIT](LICENSE) © 2026 piklen

欢迎自由使用、修改、商用与二次开发(注意 AKShare 数据使用限制)。

Bug / 功能反馈走 [GitHub Issues](https://github.com/piklen/manmankan/issues) 或 [Discussions](https://github.com/piklen/manmankan/discussions)。
