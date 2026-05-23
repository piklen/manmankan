# 路线图

> 当前发布候选 **v0.0.5.0**。本路线图列出**用户面新功能候选**，按优先级分组；
> 内部技术债清理（重构 / 测试覆盖 / CI 加固）不进本表，仅记录在 CHANGELOG 中。
>
> **版本节奏**：patch 累加（v0.0.X → v0.0.X+1），不偏好 minor 跨越。
> P0 / P1 / P2 是**优先级分组**，不等于发版号。具体哪批 patch 装哪个功能视开发进度而定。

---

## P0 候选（下批新功能优先级）

### 1. 价格提醒 `kan alert`（寄生 scan 数据通路）

- 复用 `kan scan` 数据通路，不另起调度，避免重复拉数据。
- 触发条件：阈值穿越（low/high）、N 周期位置突破、涨跌幅超阈值。
- 输出走通知中心（macOS osascript / 邮件兜底）。

### 2. 指数基准对照

- 自选股扫描时同步给出 上证 / 深证 / 创业板 / 沪深 300 同周期位置。
- 用于判断"是个股弱还是大盘弱"，避免误判机会。

### 3. ~~成交量异动~~ → ✅ v0.0.5.0 已落地

成交量识别从 2 档扩为 5 档对称(明显放大 / 温和放大 / 量能平稳 / 温和萎缩 / 明显萎缩 · 边界 2.0/1.5/0.67/0.5)。
后续如有真实数据反馈,边界微调可走 patch。前置 TD-1 `_source` 列仍未落地,跨源 volume 单位差异在 v0.0.6 一并处理。

---

## P1（P0 稳定后启动）

- **分组标签**：`Stock.groups` 字段已在 schema 预埋，P1 接 CLI（`kan add --group 核心仓`、`kan scan --group xxx`）。
- **`kan history` 历史位置回溯**：`snapshots/YYYY-MM-DD.parquet` 按日归档已预埋，P1 加查询命令。

---

## P2（远期）

- H5 可视化页面（位置热力图 + 趋势曲线）。
- 行业热力图（板块维度位置聚合）。

---

## v0.0.5.0 节奏复盘

本版没动 P0 候选(`kan alert` / 指数基准对照),转向做了**热榜扫描 + TuShare Pro + 题材扫描 + 5 档成交量** 4 大主题。原因:

- 散户日常诉求"今日散户在讨论什么"(hot rank) 比"价格提醒"高频
- 题材 / 行业 扫描补全"多源标的发现"三种模式(industry / hot / theme),散户工具面完整度优先
- TuShare Pro 是低工作量高价值 add(配 token 即用)· 帮重度用户提速
- 5 档成交量识别是"知道为啥买卖"产品愿景里异动识别拼图之一

P0 候选 1+2 推到 v0.0.6 minor。

## 架构评审结论

### 已落地

- **Markdown / JSON 输出**:v0.0.5.0 支持 `scan / low / high / info / trend / compare --format md|json`
- **东方财富热榜扫描**:`--hot rank|surge` 5 命令 + `--only-watchlist`(v0.0.5.0)
- **TuShare Pro 数据源**:`kan config` + 自写 HTTP client(v0.0.5.0)
- **题材位置扫描**:9 命令 `--theme` + `kan theme list/search` 发现入口(v0.0.5.0)
- **5 档对称成交量识别**:scan/info 表(v0.0.5.0)

### 暂不做

- **cli.py 拆分**：v0.0.3 已完成（1512 → 44 行八文件拆分），不再讨论。

### 拒绝过度工程

以下方案在评审中被明确否决，避免引入复杂度：

- 数据源工厂模式（当前 4 源 if-chain 足够清晰）
- DAL 数据访问层（parquet 直读够用）
- 独立 API 层（CLI 即 API）
- SQLite 替换 parquet（无并发写入需求）
- 事件总线（订阅者就一个，没必要）

判断标准：**当前痛点没出现就不引入抽象**。

---

## 已知技术债

| 编号 | 问题 | 修复方案 | 状态 |
|------|------|----------|------|
| TD-1 | 多源数据缓存未标注来源，回查无法判断哪条来自哪个源 | parquet 加 `_source` 列 | 🟡 待修 |
| TD-2 | 熔断器进程内态，每次启动重置，重复打挂源 | 落地 `circuit.json` 持久化（5min down TTL / 1d ok TTL） | 🟡 待修 |
| TD-3 | baostock 字符串 → numeric 用 `errors='coerce'` 静默丢 NaN | 改为严格化 + log NaN 数 | 🟡 待修 |

---

## 三源一致性 gap

| Gap | 优先级 | 内容 | 状态 |
|-----|--------|------|------|
| G1 | P0 | 腾讯 `amount` 字段语义跨板块不一致：主板 / 创业板 = 成交手数（÷100），科创板（688/689）= 成交股数（1:1）。**保守 drop amount 让 normalize 填 NaN** | ✅ 已修 |
| G2 | P1 | parquet 缺 `_source` 列 | 🟡 待修 (TD-1) |
| G3 | P1 | baostock 类型转换不够严格 | 🟡 待修 (TD-3) |
| G4 | P1 | 缺三源一致性测试 | ✅ 已加 (`tests/test_normalize_alignment.py` 10 条) |

---

## fallback 链路设计

```
fetch_kline(symbol) →
  1. baostock (独立服务器 · 免熔断 · 主路径)
  2. 新浪 (akshare.stock_zh_a_daily · 免登录 · 精度高)
  3. 东财 (akshare.stock_zh_a_hist · push2his 被部分 IP 段 ban · 实战常 fail)
  4. 腾讯 (akshare.stock_zh_a_hist_tx · 仅价格可信 · amount/volume 已 drop)
```

**根因依据**：akshare GitHub Issue
[#6092](https://github.com/akfamily/akshare/issues/6092) /
[#6148](https://github.com/akfamily/akshare/issues/6148) /
[#7011](https://github.com/akfamily/akshare/issues/7011) /
[#6214](https://github.com/akfamily/akshare/issues/6214) ·
实测 retry 4 次 5s 间隔无效（持续 ban 不是间歇性）。

---

## 跨板块交易单位备忘

| 板块 | 代码段 | 交易单位 | baostock volume 单位 | 腾讯 amount 字段实际值 |
|---|---|---|---|---|
| 沪市主板 | 6xx (除 688/689) | 1 手 = 100 股 | 股 | volume / 100（手）|
| 深市主板 | 000xxx | 1 手 = 100 股 | 股 | volume / 100（手）|
| 创业板 | 300xxx | 1 手 = 100 股 | 股 | volume / 100（手）|
| **科创板** | **688/689** | **最小 1 股递增** | 股 | **volume（股 · 1:1）** |
| 北交所 | 8xx | 100 股起步 | （未实测） | （未实测） |
| B 股 | 200/900 | 历史上 1 手 = 10 股 | （CLI 不支持） | （CLI 不支持） |

**判断**：腾讯 `stock_zh_a_hist_tx` 返回的所谓 `amount` 字段语义跨板块不可移植。
manmankan 既然只支持 A 股，安全策略是 drop 而非 board-aware 转换。

---

## 不在路线图（明确不做）

- **`kan doctor` 诊断命令**（旧 TD-3 已删除）——
  用户在 issue 中报告网络 / 数据源问题，维护者按需排查；命令本身不进核心 CLI。
  历史设计稿见 [`docs/archive/design-kan-doctor.md`](archive/design-kan-doctor.md)。
- **实时行情推送** — CLI 工具不适合，用 broker app。
- **AI 选股 / 评级 / 信号订阅** — 合规红线。
- **多账户体系 / 云同步** — 单机工具不需要。
- **移动端 App** — H5 已足够覆盖未来需求。
- **个股目标价 / 涨跌预测** — 不在能力边界，也不在使命范围。

---

*最后更新：2026-05-23*
