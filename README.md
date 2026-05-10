# 慢慢看 · manmankan

> A 股自选股「位置感」工具 · 看清你的股票正站在历史价格的哪个位置

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/manmankan.svg)](https://pypi.org/project/manmankan/)
[![Tests](https://github.com/piklen/manmankan/actions/workflows/test.yml/badge.svg)](https://github.com/piklen/manmankan/actions/workflows/test.yml)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](https://github.com/piklen/manmankan/releases)

慢慢看是一个 A 股自选股**位置感数据工具**，把电商「慢慢买」的"看历史价位再决策"心智迁移到股票场景，提供 N 日（3/5/7/10/15/30/60/90/120/180 日）新低 / 新高扫描。

> **我们告诉你位置坐标，不告诉你应该做什么。**

> 📦 **v0.0.1 首次公开发布**（Alpha）· `pip install manmankan` 即装即用 · API 接口可能在 1.0 前调整 · 镜像源（清华 / 阿里等）同步约需数日，如装不到最新版请用 `--index-url https://pypi.org/simple/` 直连官方源。
>
> 🔒 **数据隐私**：所有数据存储在本地（`~/.local/share/kan/` · XDG 规范）· 工具不上传任何用户数据 · 详见 [`SECURITY.md`](SECURITY.md)。

---

## 为什么做这个

现有工具（东方财富选股器、富途、i问财等）每次只能按**单一周期**条件筛选，用户需反复切换查看。慢慢看的差异化 = **三个"同时"**：

1. **同时展示多周期** — 10 个周期一屏，不用切来切去
2. **同时覆盖自选池** — 横向比较"我的 30 只股谁最接近低点"
3. **同时标记共振** — "某股同时触及 10 日 + 60 日 + 120 日低点"= 强信号高亮

---

## 截图

```
慢慢看 · 指数位置扫描 · 低点模式 · 2026-05-09 更新
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━┓
┃指数              ┃    现价 ┃  3日 ┃  5日 ┃  7日 ┃ 10日 ┃ 15日 ┃ 30日 ┃ 60日 ┃ 90日 ┃ 120日 ┃ 180日 ┃共振 ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━┩
│沪深300 000300    │ 3960.20 │ [2%] │ [3%] │ [3%] │ [3%] │ [3%] │ [5%] │ [5%] │ 10%  │  15%  │  18%  │ ×6  │
│上证50  000016    │ 2670.10 │ [3%] │ [4%] │ [4%] │  9%  │ 10%  │ 14%  │ 18%  │ 20%  │  22%  │  25%  │ ×4  │
│中证500 000905    │ 5690.50 │ [0%] │ [0%] │ [0%] │ [1%] │ [1%] │ [1%] │  3%  │  8%  │  12%  │  16%  │ ×8  │
└──────────────────┴─────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴───────┴───────┴─────┘

[x%] = 触及低点(≤5%) · 0%=区间最低 · 越低=越接近 N 日最低价

⚠️ 示例使用三大指数演示位置扫描功能 · 截图数据为占位演示 · 实际数据以 `kan scan` 实时输出为准
⚠️ 创新低 ≠ 见底 · 创新高 ≠ 顶 · 历史价格不预示未来 · 仅供参考，不构成投资建议
```

---

## 安装

要求 Python 3.11+。如果你 Python < 3.11，用 [uv](https://docs.astral.sh/uv/) 一行装好：
```bash
uv python install 3.11
```

### 推荐：uv tool install（隔离环境 + 全局可用 · 已验证 macOS / Linux）

```bash
uv tool install manmankan
kan --version
```

> uv 自带依赖管理 · 不需要自己建 venv · 不会撞 [PEP 668](https://peps.python.org/pep-0668/)。这是 macOS Homebrew Python 用户最稳的路径。

### pipx 路径（如果已装 pipx）

```bash
# 如果未装 pipx · 先装：brew install pipx (macOS) · 或 apt install pipx (Linux)
pipx install manmankan
kan --version
```

### 标准 pip（必须在虚拟环境内）

⚠️ **macOS Homebrew Python / Debian 12+ / Ubuntu 23+ 等现代发行版默认禁止全局 `pip install`** —— [PEP 668](https://peps.python.org/pep-0668/) 安全机制。直接 `pip install manmankan` 会报 `error: externally-managed-environment`。

正确做法：先建 virtualenv 再装。

```bash
python3 -m venv ~/.kan-venv
source ~/.kan-venv/bin/activate
pip install manmankan
kan --version
# 退出 venv: deactivate
# 下次用 kan 前: source ~/.kan-venv/bin/activate
```

> 或直接用上面的 **`uv tool install`** —— 一行搞定，不需要折腾 venv。

### 从源码

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync
uv run kan --version
```

---

## 快速开始

```bash
# 1. 添加自选股
kan add 600519 000858 601318

# 2. 扫描位置（首次会自动拉取数据）
kan scan

# 3. 查看连续涨跌看板
kan trend
```

输入 `kan help`（或 `kan` / `kan --help`）查看完整中文命令速记，三者等价。

---

## 命令速记

### 自选股管理

```bash
kan add 600519 000858     # 添加自选股
kan add 茅台              # 支持名称搜索
kan remove 600519         # 移除自选股
kan remove 茅台 五粮液    # 支持批量移除
kan list                  # 查看自选列表（末尾显示总数）
kan import stocks.csv     # CSV 批量导入
kan clear                 # 清空自选列表
```

### 位置扫描

```bash
kan scan                  # 全景扫描 10 周期（低点模式）
kan scan --high           # 全景扫描 10 周期（高点模式）
kan scan -S               # 仅显示有共振信号的股票
kan scan --diff           # 显示与上次扫描的变化
kan scan --exclude-st     # 排除 ST/*ST 股票
```

> 在终端宽度 < 130 列时自动选择周期子集 · 共振列始终可见（终端宽度自适应）

> 排序：共振优先（×N 多的在前）→ 同共振按 3 日 → 5 日 → ... → 180 日 字典序 tie-break

### 低点/高点筛选

```bash
kan low 60                # 谁在 60 日低点？
kan low 30 60 120         # 多周期一次看
kan high 30               # 谁在 30 日高点？
```

### 单只详情

```bash
kan info 600519           # 单只股票全周期位置 + 涨跌 + 共振
```

### 连续涨跌看板

```bash
kan trend                 # 默认看板（不筛选）
kan trend --down          # 只看连跌 ≥ 3 天（默认值）
kan trend --down 5        # 只看连跌 ≥ 5 天
kan trend --up            # 只看连涨 ≥ 3 天（默认值）
kan trend --up 5          # 只看连涨 ≥ 5 天
kan trend --latest 7      # 展示近 7 天走势详情
kan trend --candle        # 阳线阴线口径

# 任意组合
kan trend --down 5 --latest 7 --candle
```

> `--latest` 表头终端宽度自适应 · 不再截断

> N 范围：2-30 · 阈值合并到 `--down N` / `--up N`（不提供独立 `--streak` 选项）

### 数据管理

```bash
kan fetch                 # 拉取数据（通常不需要，scan 自动更新）
kan fetch --force         # 强制刷新
```

### 卸载

```bash
kan uninstall              # 删除所有本地数据 + 输出软件包卸载命令（默认确认 + 列大小）
kan uninstall --yes        # 跳过确认（脚本 / CI 用）
kan uninstall --keep-data  # 只看包卸载命令 · 不删数据
```

> `kan uninstall` **不会**自动删软件包本身（kan 无法删自己运行的进程）· 它会自动检测安装方式（uv tool / pipx / pip / venv）后提示你运行对应卸载命令（如 `uv tool uninstall manmankan`）。

---

## 设计哲学

> **位置感知入口 ≠ 买卖决策出口。**

慢慢看严格定位为**行情数据展示工具**，不包含任何买卖建议、评分评级、策略推荐。每次输出都强制带风险提示，措辞严守"位置 / 区间 / 触及"。

详见 [`docs/compliance.md`](docs/compliance.md)。

---

## 数据源

数据来自 [AKShare](https://github.com/akfamily/akshare)（开源 A 股数据接口），盘后批量拉取前复权日 K 线，本地 Parquet 缓存。**使用延时数据，不涉及实时行情。**

⚠️ **数据使用条款**：AKShare 官方声明数据 "仅限学术研究用途（Academic Research Only）"（[详见 AKShare GitHub](https://github.com/akfamily/akshare)）。本工具继承此限制，**仅供个人研究 / 教育用途，不得用于商业产品 / SaaS / 二次分发**。

⚠️ **数据可用性**：数据可用性依赖 AKShare 与上游网站，上游策略变更可能导致接口失效，本工具不保证数据持续可用。

---

## ⚠️ 法律免责声明

本工具仅供个人研究学习使用，**不构成任何投资建议**。使用者应当独立判断行情数据，自行承担投资决策的全部风险。

- 本工具不推荐任何具体股票
- 不预测涨跌、不给目标价
- 不提供任何形式的投资指导
- 历史价格数据仅供参考，不预示未来表现

**核心声明**：

- 本工具开发者**不持有任何证券投资咨询资质**，非持牌投资顾问
- 本工具**不构成荐股 / 投顾 / 信号服务**任何形式
- 用户使用本工具产生的任何投资行为**与开发者无关**
- 截图中出现的指数仅供演示位置扫描功能，**不构成任何形式的推荐与评级**

**A 股市场有风险，投资需谨慎。**

如需将本工具用于商业目的或二次开发，请遵守 [MIT 协议](LICENSE) 并自行确保合规（特别是 AKShare 数据使用限制）。

---

## 开发

```bash
# 安装开发依赖
uv sync

# 运行测试
uv run pytest

# 代码检查
uv run ruff check kan/
```

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可证

[MIT](LICENSE) © 2026 piklen

本项目采用 MIT 协议，欢迎自由使用、修改、商用与二次开发。如对本工具有 bug / feature 反馈，请走 [GitHub Issues](https://github.com/piklen/manmankan/issues) 或 [Discussions](https://github.com/piklen/manmankan/discussions)。
