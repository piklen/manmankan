# 慢慢看 · manmankan

> A 股自选股 CLI · **不告诉你买什么 · 只帮你找到符合条件的**
> 多周期位置百分位 · 共振信号 · 用户主导的条件筛选 · 100% 本地。

[![License: Parity 7.0.0](https://img.shields.io/badge/License-Parity_7.0.0-orange.svg)](https://paritylicense.com/versions/7.0.0.html)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/manmankan.svg)](https://pypi.org/project/manmankan/)
[![PyPI downloads](https://img.shields.io/pypi/dm/manmankan.svg)](https://pypi.org/project/manmankan/)
[![Tests](https://github.com/piklen/manmankan/actions/workflows/test.yml/badge.svg)](https://github.com/piklen/manmankan/actions/workflows/test.yml)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](https://github.com/piklen/manmankan/releases)

慢慢看是一个**纯命令行**的 A 股自选股位置工具。它把你的自选股在 3 / 5 / 7 / 10 / 15 / 30 / 60 / 90 / 120 / 180 日窗口内的**位置百分位**一屏显示,并标出同时触及多个低点(或高点)的**共振信号**。它只呈现客观的价格位置数据——是否据此操作,由你自己判断。

<details>
<summary><b>🌐 English summary</b></summary>

**manmankan** (慢慢看) is a pure command-line tool for China A-share investors who track their own watchlists. It shows where each stock currently sits within its 3 / 5 / 7 / 10 / 15 / 30 / 60 / 90 / 120 / 180-day price range — a "position percentile" — and flags stocks that touch lows (or highs) across multiple timeframes as resonance signals (`×N`).

It deliberately stops there: **no buy/sell advice, no ratings, no price targets, no "AI stock picking."** Just objective price-position data, fully local — no login, no account, no telemetry. Data is delayed end-of-day K-line from the AKShare ecosystem (baostock primary). `pip install manmankan` · Python 3.11+ · [Parity Public License 7.0.0](LICENSE) · A-share only (no HK / US / futures).
</details>

> **当前 v0.0.6.7**(Alpha · API 在 1.0 前可能调整)· `uv tool install manmankan` 即装即用
> **100% 本地** · 不登录 · 不上传自选 · 不推送 · 不遥测 · 数据存 `~/.local/share/kan/`(XDG 规范)
> **延时数据** · 盘后批量拉取前复权日 K 线 · 不适合分钟级短线
> **许可** · 个人散户日常自用完全免费;商业使用见 [许可证](#许可证)

---

## 目录

- [这是给谁用的](#这是给谁用的)
- [安装](#安装)
- [30 秒上手](#30-秒上手)
- [真实输出](#真实输出)
- [三个「同时」](#三个同时)
- [核心命令](#核心命令)
- [脚本化使用](#脚本化使用)
- [数据 · 缓存 · 隐私](#数据--缓存--隐私)
- [设计哲学](#设计哲学)
- [风险与法律免责](#风险与法律免责)
- [路线图](#路线图)
- [文档导航](#文档导航)
- [故障排查 FAQ](#故障排查-faq)
- [开发](#开发)
- [许可证](#许可证)

---

## 这是给谁用的

| 你是 | 慢慢看解决的问题 |
|---|---|
| **A 股长线 / 技术派散户**(月级别周期) | 一屏看完所有自选股的 10 周期位置 + 共振信号,不用逐只切换 |
| **不信「AI 选股」黑箱的玩家** | 只给客观位置百分位,不给评级 / 目标价 · 算法开源可审 |
| **隐私敏感 / 不愿登录 broker app 的人** | 完全本地 · 无账号 · 无推送 · `kan uninstall` 一键清 |
| **量化 / 自动化爱好者** | CLI + parquet 缓存可直读 · JSON 快照按日归档 · 可脚本调用 |

**不适合**:T+0 短线投机者(数据延时,日 K)、港股 / 美股 / 期货用户(仅 A 股)、期待 AI 给出买卖结论的人(合规红线说不)。

---

## 安装

要求 Python 3.11+。推荐用 [uv](https://docs.astral.sh/uv/),隔离环境 + 全局可用,不会撞 [PEP 668](https://peps.python.org/pep-0668/):

```bash
uv tool install manmankan
kan --version
```

<details>
<summary><b>第一次用命令行?零基础两步装好(mac / Windows)</b></summary>

**Mac / Linux** — 打开「终端」(Terminal),粘贴回车:

```bash
curl -LsSf https://raw.githubusercontent.com/piklen/manmankan/main/scripts/install.sh | bash
```

**Windows** — 打开 PowerShell,粘贴回车:

```powershell
powershell -c "irm https://raw.githubusercontent.com/piklen/manmankan/main/scripts/install.ps1 | iex"
```

> 脚本会自动装 uv + manmankan 并验证。看到 ✅ 即成功;装好后打开**新**终端窗口(PATH 才生效)。
> 安全敏感用户可先下载脚本审阅再跑(`curl -L ... > install.sh`),每版 release notes 公布 SHA256。

</details>

<details>
<summary><b>其他安装方式(pipx / pip / 源码)</b></summary>

```bash
# pipx
pipx install manmankan

# 标准 pip(必须在虚拟环境内 · 现代发行版默认禁止全局 pip)
python3 -m venv ~/.kan-venv && source ~/.kan-venv/bin/activate && pip install manmankan

# 从源码
git clone https://github.com/piklen/manmankan.git && cd manmankan && uv sync && uv run kan --version
```

> 没装 uv?一行装好:`curl -LsSf https://astral.sh/uv/install.sh | sh`
> 镜像源同步最新 PyPI 版本约需数日,装不到最新版时加 `--index-url https://pypi.org/simple/` 直连。

</details>

---

## 30 秒上手

```bash
uv tool install manmankan           # 一行装好
kan add 600519 茅台 601318          # 代码 / 名称混搭
kan scan                            # 一屏看完位置 + 共振信号
kan find --pos 180:lt:5 --limit 5   # 按你的规则筛:180 日位置 < 5%
kan find --codes 600519,000858 --gain 30:gt:10  # 任意代码池里筛
```

第一次跑会有两次「看起来卡住」的时刻,**都是正常的**:

- **首次 `kan add`**:拉一次全市场 A 股代码-名称表(5–15s)· 之后 7 天内秒级响应。
- **首次 `kan scan`**:多源并发拉取自选股 K 线(30 只约 1–2 分钟,180 天日 K)· 之后只补增量。

进度条都是真实的——失败会跳过单只继续跑,Ctrl-C 可中断,已拉数据自动保存、下次续传。装坏了跑 `uv tool install manmankan --reinstall`,详见 [§故障排查](#故障排查-faq)。

---

## 真实输出

> 以下为真实终端输出格式,数据为占位演示(指数仅用于示意,**不构成任何形式的推荐**)。

```
慢慢看 · 自选股位置扫描 · 低点模式 · 数据截止 05-10 收盘 · 16:05 拉取
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━┓
┃股票              ┃    现价 ┃  3日 ┃  5日 ┃  7日 ┃ 10日 ┃ 15日 ┃ 30日 ┃ 60日 ┃ 90日 ┃ 120日 ┃ 180日 ┃共振 ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━┩
│沪深300 000300    │ 3960.20 │ [2%] │ [3%] │ [3%] │ [3%] │ [3%] │ [5%] │ [5%] │ 10%  │  15%  │  18%  │ ×6  │
│中证500 000905    │ 5690.50 │ [0%] │ [0%] │ [0%] │ [1%] │ [1%] │ [1%] │  3%  │  8%  │  12%  │  16%  │ ×8  │
└──────────────────┴─────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴───────┴───────┴─────┘

  [x%] = 触及低点(≤5%)· 0% = 区间最低 · 越低越接近 N 日最低价 · ×N = 同时触及 N 个周期低点
⚠️ 创新低 ≠ 见底 · 创新高 ≠ 顶 · 历史价格不预示未来 · 仅供参考,不构成投资建议
```

`[x%]` 带方括号高亮 = 触及低点(≤5% 区位)· `×N` = 共振次数,越大表示同时触及越多周期的低点。窄屏时自动选周期子集,共振列始终显示。`kan info <代码>` 看单只全周期详情,`kan trend` 看连续涨跌看板。

---

## 三个「同时」

现有工具每次只能按**单一周期**筛选,看 30 只自选股谁最接近低点要逐只切换。慢慢看的差异化是三个「同时」:

1. **同时多周期** — 10 个周期一屏(3/5/7/10/15/30/60/90/120/180 日)
2. **同时多自选** — 横向比较「我的股谁最接近低点」,按共振优先排序
3. **同时标共振** — 「某股同时触及 10 + 60 + 120 日低点」= `×3`,**只是参考,不是信号**

---

## 核心命令

> 慢慢看自带中文速记。忘了用法随时跑 **`kan help`**(= `kan` = `kan --help`)。下面只列每组的核心用法。

**自选股 / 分组**

```bash
kan add 600519 茅台 601318     # 代码 / 名称混搭 · 批量
kan remove 茅台 五粮液         # 移除 · 批量
kan list                       # 查看自选(--all 看所有组)
kan import stocks.csv          # CSV 批量导入(上限 10 MB)
kan export > watchlist.csv     # 导出自选为 CSV(--all 含 group 列)
kan clear                      # 清空(带确认)

kan group create 持仓          # 建组 · 每组独立扫描
kan group list                 # 列所有组(标 default + 股数)
kan group default 持仓         # 切换默认组
kan add 600519 --group 持仓    # 加股票到指定组
kan move 600519 自选 持仓      # 跨组移动单股
```

> 同一只股票可同时在多组 · 老 `watchlist.json` 自动迁移到 `自选` 组,老命令零感知。`scan / low / high / trend / fetch / find` 全支持 `--group`。

**位置扫描 `kan scan`**

```bash
kan scan                       # 全景扫描 10 周期(低点模式 · 默认)
kan scan --codes 600519,000858 # 只扫描指定代码池
kan scan 600519,000858         # 同上,适合临时查 1-N 只
kan scan --high                # 高点模式
kan scan -S                    # 只显示有共振信号的股票
kan scan --diff                # 增量模式 · 显示与上次扫描的变化
kan scan --exclude-st          # 排除 ST / *ST
```

> 排序:共振次数降序 → 各周期位置百分位(低点模式升序 / 高点模式降序)· scan 行内联 PE、近 5 日主力净额、10/20 日线、近 20 日低价和除权除息标记(有数据时显示)· 终端窄屏时自动选周期子集,共振列始终显示。

**单周期筛选 / 单只详情 / 连续涨跌**

```bash
kan low 30 60 120              # 谁在 30/60/120 日低点(≤5%)· 多周期一次看
kan high 30                    # 谁在 30 日高点(≥95%)
kan info 600519               # 单只全周期位置 + 现价 + 连续涨跌 + 共振 + 标记
kan history 600519            # 单只位置百分位历史回溯(-p 切周期 · 纯离线读每日快照)
kan trend --down 5 --latest 7 # 连跌 ≥5 天 + 展示近 7 天(--up / --candle 可组合)
```

> 周期范围 2–360 天;`kan trend` 的 N 范围 2–30 天。`kan history` 纯离线,只覆盖曾在自选、且当天跑过 `kan scan` 的股票(读 `snapshots/` 每日快照)。

**条件筛选 `kan find`**(用户主导)

```bash
kan find --pos 180:lt:5                       # 180 日位置 < 5%
kan find --resonance low:gte:3                # 低点共振 ≥ 3 个周期
kan find --pos 60:lt:10 --resonance low:gte:2 # 多条件(filter 间 AND)
kan find --industry 半导体 --pos 180:lt:10    # 行业池里筛(也支持 --hot / --theme / --group)
kan find --codes 600519,000858 --pos 180:lt:20 # 自定义代码池筛选
printf "600519\n000858\n" | kan find --codes - --gain 30:gt:10
kan find --all --up-days gte:3 --format json   # 全市场截面 + K 线预计算裸值筛
kan find --all --pe lt:20 --format json --compact # 低字段量 JSON + 数据可用性统计
kan find --industry 半导体 --format json --fields code,name,price,context.positions,valuation.pe_ttm
kan find --pos 180:lt:5 --limit 20            # 输出条数上限(默认 50)
```

> 语法:`--pos PERIOD:OP:VAL`(PERIOD ∈ 3/5/7/10/15/30/60/90/120/180,OP ∈ lt/lte/gt/gte/eq/ne)· `--resonance low|high:OP:VAL` · `--exclude-st`。`kan find` 是**用户主导的条件筛选器**:规则由你显式指定,**无内置 preset、无评分、无评级、无推荐**,只返回符合你规则的股票。JSON schema、数据来源和缺数据语义见 [`docs/find.md`](docs/find.md);合规细则见 [`docs/compliance.md` §7](docs/compliance.md)。

**行业 / 热榜 / 题材**

```bash
kan scan --industry 半导体     # 扫某申万行业全成分股 · 自选股 ⭐ 高亮
kan scan --hot rank            # 东财人气榜(rank)· 也支持 surge 飙升榜
kan scan --theme AI应用        # 扫某题材全成分股
kan scan --theme AI应用 --only-watchlist   # 只看自选 ∩ 题材
kan theme search 数据要素      # 模糊搜题材名(theme list 列清单)
kan theme trend --min-streak 1 --sort latest # 题材连涨/连跌榜 · 看刚启动题材
kan board rank --kind industry --by moneyflow # 行业板块主力净额榜
kan board rank --kind theme --by pos -p 60    # 题材板块 N 日位置榜(N=3-180)
```

> `--industry` / `--hot` / `--theme` 三者互斥 · `--only-watchlist` 需配合其一。题材分类来自上游数据源口径,不是慢慢看的判断。

股票池选择口径:

- `kan scan/low/high/trend/fetch` 默认看自选股 default 组,`--group` 切换自选分组。
- `kan scan --codes` / `kan scan <codes>` 接外部候选代码池,只输出指定代码,不写入自选扫描快照。
- `--industry` / `--theme` / `--hot` 会把池切到对应行业 / 题材 / 热榜;`--only-watchlist` 取自选交集。
- `kan find --codes` 接外部候选代码池;`kan find --all` 是全市场截面池,不是所有命令的通用 `--all` 分组。

**导出 / 数据 / 配置 / 维护**

```bash
kan scan --format md|json      # 导出格式(scan / low / high / info / trend / compare / history 支持)
kan fetch --force              # 强制刷新缓存(通常 scan 会自动更新)
kan config set tushare-token <TOKEN>   # 接 TuShare Pro 作为顶档日 K 源(可选)
kan completion install         # 安装 shell 补全(zsh/bash/fish/powershell · 首次跑命令时自动装)
kan update                     # 检查并升级(--check 只查 · --yes 跳过确认)
kan uninstall                  # 删除所有本地数据 + 输出软件包卸载命令
```

> 未配 token 时行为不变;配置后 TuShare Pro 优先,`TUSHARE_TOKEN` / `TUSHARE_ENDPOINT` 环境变量可临时覆盖。
> 关闭自动行为:`KAN_NO_UPDATE_CHECK=1`(更新检查)· `KAN_NO_COMPLETION_AUTOINSTALL=1`(补全自装)。

---

## 脚本化使用

除 CLI 外,慢慢看提供稳定的 **`kan.api`** 入口,适合写脚本 / cron / notebook:

```python
from kan.api import WatchlistSet, ThemeSet, HotRankSet, IndustrySet   # 四类股票集合
from kan.api import scan, low, high, trend, fetch                     # 五个 verb(任何集合都可接受)

hits = low(WatchlistSet(), periods=[60])      # 自选股 60 日低位
for period, stocks in hits.items():
    for r, pr in stocks:
        print(r.symbol, r.name, f"{pr.position_pct:.1%}")
```

也支持自定义股票集合(鸭子类型,无需继承)、`from_flags()` 按 CLI flag 风格构造,以及注入自定义 K 线数据源(`register_kline_source()` · 适配器 + 责任链 · 按 priority 自动 fallback)。

> **完整 API 文档(全部符号 + 示例 + 自定义数据源约定)是 [`kan/api.py`](kan/api.py) 文件头的 docstring** —— 它是公开 contract 的 SOT。`kan.core.*` 内部模块可能小版本重构,脚本请只 import `kan.api`。

---

## 数据 · 缓存 · 隐私

**数据源**:盘后批量拉取前复权日 K 线,走统一 `KlineSourceChain`(适配器 + 责任链,按 priority 排序、同档并发 race)。主路径 baostock(独立服务器、免熔断),其次东财 / 新浪,配置 TuShare Pro token 后顶档优先。东财 push2his 对国内多 IP 段长期 ban,故 baostock 推为主路径([akshare #6092 / #6148 / #7011](https://github.com/akfamily/akshare/issues/6092))。

> ⚠️ **AKShare 数据条款**:[AKShare](https://github.com/akfamily/akshare) 数据「仅限学术研究用途」。本工具继承此限制,**仅供个人研究 / 教育用途,不得用于商业产品 / SaaS / 二次分发**。数据可用性依赖上游,不保证持续可用。

**缓存生命周期**:

| 数据 | 存放 | 生命周期 |
|---|---|---|
| 日 K 线 | `~/.local/share/kan/data/<code>.parquet` | 当日 fresh · 跨天自动刷 · `--force` 强刷 |
| 代码-名称表 | `~/.local/share/kan/stock_names.json` | 7 天 |
| 自选股 | `~/.local/share/kan/watchlist.json` | 永久 · 原子写 · 明文可手编 |
| 扫描快照 | `~/.local/share/kan/snapshots/<日期>.json` | 240 天(`scan --diff` 用) |

**跨板块涨跌停**:`kan scan` / `kan trend --latest` 自动标记,按板块差异化——主板 ±10% / 创业板 · 科创板 ±20% / 北交所 ±30% / ST · *ST ±5%(2026-07-06 起 ±10%,来自交易所公告,代码内置自动切换)。

**隐私**:完全本地运行,**不上传任何用户数据**。不登录、不注册、不上传自选、不向第三方推送查询行为、不做遥测。装过早期版本(`~/.kan/`)首次启动会自动迁移到 XDG 路径。详见 [`SECURITY.md`](SECURITY.md)。

---

## 数据能力边界

慢慢看当前定位是**本地行情位置 + 用户主导筛选器**。它可以把自选、行业、题材、热榜、全市场或外部传入的代码池接到同一组位置 / 共振 / 量价 / 资金 / 技术 / 部分基本面过滤上,适合做流水线里的数据过滤环节。

已覆盖:多周期位置、共振、关键价位(10/20 日线、近 20 日低价)、涨幅、连阳、成交量、估值裸值(PE/PB/PS/股息率)、ROE/净利增速/营收增速、主力净额、RSI/MACD/KDJ/均线/ATR/BOLL、连板、筹码、股东户数/十大流通/北向季度代理、除权除息事件标记。

明确不覆盖:完整财报数据库、公告解读、分红登记日 / 除息日 / 派息日流程、实时行情、港美股、目标价、评级、策略 preset。股息相关提供 `dv_ttm` 股息率裸值与 scan 除权除息事件标记;完整分红日历请组合交易所公告、公司公告或其它专业数据源。

---

## 设计哲学

> **位置感知入口 ≠ 买卖决策出口。**

慢慢看严格定位为**行情数据展示工具**,不包含任何买卖建议、评分评级、策略推荐。每次输出强制带风险提示,措辞严守「位置 / 区间 / 触及」的客观语言。

**「位置百分位」** = `(当前价 − N 日最低) / (N 日最高 − N 日最低) × 100`,即当前价在 N 日波动区间内的相对位置:`0%` = N 日最低,`100%` = N 日最高,`[≤5%]` = 触及低点(数学定义,非信号)。跌出 N 日新低时位置重置为新一天的 0%,只是算法重置,不代表任何含义。

**共振 `×N`** 表示同时触及 N 个周期的低 / 高点。它告诉你的是「这只股票当前价位在多个时间窗口看都接近极值」;它**不告诉**你这是不是底、是不是机会、该不该买。要不要行动,完全取决于你自己的研究 / 风险承受 / 资金情况。详见 [`docs/compliance.md`](docs/compliance.md)。

---

## 风险与法律免责

**本工具仅供个人研究学习使用,不构成任何投资建议。** 使用者应独立判断行情数据,自行承担投资决策的全部风险。

- 不推荐任何具体股票 · 不预测涨跌 · 不给目标价 · 不提供任何形式的投资指导
- 历史价格数据仅供参考,不预示未来表现 · **创新低 ≠ 见底 · 创新高 ≠ 顶**
- 开发者**不持有证券投资咨询资质**,非持牌投资顾问;本工具不构成荐股 / 投顾 / 信号服务
- README 截图中的指数 / 示例代码仅用于演示功能,**不构成任何形式的推荐与评级**
- 用户使用本工具产生的任何投资行为与开发者无关

**A 股市场有风险,投资需谨慎。**

---

## 路线图

近期候选(优先级,非发版号):`kan alert` 价格提醒 · 指数基准对照(个股弱 vs 大盘弱)· 成交量异动识别。

完整路线图、「不在路线图」(明确不做的方向,如实时推送 / AI 选股 / 目标价预测)见 [`docs/roadmap.md`](docs/roadmap.md)。版本号遵循 PEP 440 四段格式,日常发布累加最后一段(patch)。

---

## 文档导航

| 文档 | 用途 |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更记录(Keep a Changelog 格式) |
| [`docs/compliance.md`](docs/compliance.md) | 合规红线 / 关键词黑名单 / 强制文案(贡献代码前必读) |
| [`docs/find.md`](docs/find.md) | `kan find` 数据来源 / JSON schema / 缺数据语义 |
| [`docs/roadmap.md`](docs/roadmap.md) | 路线图 / 不在路线图 |
| [`kan/api.py`](kan/api.py) | Python API 完整 docstring(脚本化使用 SOT) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 开发环境 / 代码风格 / 公开输出语言规范 / Commit 规范 |
| [`SECURITY.md`](SECURITY.md) | 漏洞报告(Private Vulnerability Reporting) |

---

## 故障排查 FAQ

**`kan` 装完跑不起来 / 抛 ImportError** — 多半是升级中途被打断。按你的安装方式强制重装:

```bash
uv tool install manmankan --reinstall    # uv 装的
pipx install manmankan --force           # pipx 装的
pip install --force-reinstall manmankan  # pip 装的
```

**`kan` 命令找不到(command not found)** — uv:确认 `~/.local/bin` 在 PATH;pipx:跑 `pipx ensurepath` 后重启终端;macOS Homebrew Python 用户改用 uv tool。

**网络 / 数据源连不上** — 慢慢看默认把数据源域名并入 `no_proxy` 绕过本机代理直连。全部源失败多半是网络问题,可临时去代理重试:

```bash
unset HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY && kan add 600519
```

> 若你的网络**必须走代理**才能出网,用 `export KAN_KEEP_PROXY=1` 关掉自动绕过。

更多问题请提 [GitHub Issues](https://github.com/piklen/manmankan/issues)。

---

## 开发

```bash
git clone https://github.com/piklen/manmankan.git && cd manmankan
uv sync                          # 安装依赖(含 dev)
uv run pytest                    # 跑测试
uv run ruff check kan/           # lint
git config core.hooksPath .githooks   # 启用 pre-commit(禁词扫描 + lint)
```

贡献前请读 [`CONTRIBUTING.md`](CONTRIBUTING.md):公开档案语言规范(中性词 · 不带 AI 工具签名)、合规红线(无买卖建议 / 无评级)、Commit 规范。

---

## 许可证

[Parity Public License 7.0.0](LICENSE) · 附 [Attribution Rider (NOTICE)](NOTICE) · © 2026 piklen

**非商业使用**(个人 / 学术 / 评估 / 非营利)免费,衍生作品须同 license 公开(copyleft)· **商业使用**(销售产品 / 付费服务 / SaaS / 嵌入商业产品)须先获作者书面授权 · 详见 [NOTICE](NOTICE)。衍生作品须在 README 显著位置标注 "Based on manmankan (https://github.com/piklen/manmankan)"。数据源使用另需遵守 [AKShare 数据限制](https://github.com/akfamily/akshare)。

Bug / 功能反馈走 [GitHub Issues](https://github.com/piklen/manmankan/issues) 或 [Discussions](https://github.com/piklen/manmankan/discussions)。
