# manmankan 架构愿景

> 撰写日期：2026-06-04 · 描述目标架构和设计原则，不等同于当前实现状态。

---

## 一、定位：三层架构中的"数据中间层"

manmankan 处于原始数据源和 AI Agent 之间，是一个**不做数据源、不做 AI——只在中间做数据翻译层**的工具。

```
┌─────────────────────────────────────────────────────────┐
│                    Layer 3: AI 分析层                     │
│  LLM / 外接 AI  ·  推理  ·  自然语言  ·  决策                 │
│  (用户自己的 LLM / 外接 AI 分析工具)                       │
├─────────────────────────────────────────────────────────┤
│                 ★ Layer 2: 数据中间层 ★                    │
│                     manmankan 在这里                      │
│  筛选  ·  位置语义  ·  共振检测  ·  合规包装  ·  低 token   │
│  输出: CLI 表格 (给人) + JSON (给 AI) + MCP (给 Agent)     │
├─────────────────────────────────────────────────────────┤
│                 Layer 1: 数据基础设施                       │
│  tushare / akshare / baostock / Wind / iFinD / ...       │
│  裸数据  ·  字段多  ·  噪音大  ·  AI 直接消费成本高          │
└─────────────────────────────────────────────────────────┘
```

**为什么需要中间层？**

原始数据源（tushare 等）的问题：
- 字段多（几十个）、命名不一致、AI 需要大量 token 理解 schema
- 没有"位置""共振"等语义概念——只有裸价格，没有坐标
- 没有筛选 DSL——AI 需要写 Python 代码来过滤
- 没有合规包装——裸数据直接给 AI 有"荐股"合规风险

manmankan 做的事：
- 数据筛选 → 减少 token
- 语义增强 → 加入"位置百分位""共振""板块资金排名"等 AI 可以直接理解的概念
- 合规包装 → 输出自带 `disclaimer`，数据不带方向性
- 多源聚合 → tushare/akshare/baostock 自动 fallback，AI 不用关心数据从哪来

---

## 二、Source 模型：多市场扩展的架构基础

manmankan 的核心抽象是 **Source**（数据源适配器）——每个市场或数据类别是一个独立的 Source。

```
manmankan
  │
  ├── Source: ashare (当前实现)
  │     ├── DataProvider: akshare (K线/行业/概念)
  │     ├── DataProvider: tushare (PE/PB/资金流)
  │     ├── DataProvider: baostock (K线备选)
  │     └── DataProvider: adata (题材位置)
  │
  ├── Source: usstock (远期)
  │     ├── DataProvider: yfinance
  │     └── DataProvider: alpha_vantage
  │
  ├── Source: hkstock (远期)
  │     └── DataProvider: akshare (港股)
  │
  └── Source: crypto (远期)
        └── DataProvider: coingecko / cryptocompare
```

**设计原则**：
- 每个 Source 实现统一接口：`fetch()` / `scan()` / `info()` / `find()`
- Source 之间完全解耦——usstock 挂了不影响 ashare
- 每个 Source 可以有多个 DataProvider，通过责任链 fallback
- 新增市场 = 实现一个新 Source，不改核心逻辑

**当前状态**：Source 抽象尚未在代码中实现（v0.0.6.9 的 data/ 层直接耦合了 akshare/tushare）。提取 Source 接口是中期架构目标，不阻塞当前功能迭代。

---

## 三、AI 消费设计

manmankan 的每个命令都同时考虑两种输出形态：

### 3.1 人类消费（终端）

- Rich 表格、颜色、emoji、对齐
- `kan scan` 默认终端表格
- `kan history` ASCII K 线图

### 3.2 AI 消费（JSON）

所有数据查询命令（`scan` / `find` / `info` / `history` / `board rank` / `trend`）支持 `--format json`：

```json
{
  "ok": true,
  "schema_version": 1,
  "rule": {"pos": {"180": "lt:10"}},
  "results": [...],
  "data_availability": {"pe": false, "moneyflow": true},
  "stats": {"total": 23, "returned": 23},
  "disclaimer": "..."
}
```

**设计原则**：
- 合法 JSON 是硬要求——AI 不应该需要 try/except 来消费 manmankan 输出
- 错误用 `{"ok": false, "error": {"code": "...", "message": "...", "hint": "..."}}` 信封，不是裸 traceback
- `data_availability` 告诉 AI 哪些字段可能缺失（如 PE），避免 AI 基于空数据做判断
- `schema_version` 保证向后兼容——AI 可以根据版本号适配解析逻辑
- 字段白名单 `--fields @core,@valuation` 让 AI 只要求需要的数据，节省 token

### 3.3 Agent 消费（MCP + Skills.md）

- **Skills.md**：`skills/manmankan-skill.md` 是给 AI Agent 的能力清单——Agent 读到就知道所有命令、参数和典型用法
- **MCP Server**：`kan mcp serve` 在 CLI 契约上提供 stdio MCP；`kan mcp install` 负责注册到常见用户级客户端配置
- **退出码语义**：0=成功，非 0=具体错误类别，Agent 不需要解析 stderr

---

## 四、数据管道

```
用户命令 (CLI / MCP / API)
       │
       ▼
┌──────────────────┐
│  命令解析层 (CLI)  │  typer · 参数校验
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  服务层 (Service) │  业务逻辑 · 筛选条件编译 · 合规注入
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  数据层 (Data)    │  Source 路由 · DataProvider 责任链 · 缓存管理
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  渲染层 (Render)  │  终端表格 / JSON / Markdown
└──────────────────┘
```

**关键设计决策**：

- **服务层**（`kan/service/`）正在从 CLI 层向下抽取——核心业务逻辑不应与 typer 命令耦合
- **数据层**（`kan/data/`）使用责任链模式——依次尝试多个 DataProvider，第一个成功即返回
- **缓存层**（`kan/infra/`）基于 XDG 规范，增量更新策略
- **渲染层**（`kan/render/`）终端和 JSON 走不同 code path，互不污染

---

## 五、演进路线

```
现在 (v0.0.6.9)          近期 (下一批)           中期                    远期
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ CLI + JSON 输出  │    │ + MCP Server    │    │ + Source 接口抽象 │    │ 多市场支持       │
│ 位置扫描         │ →  │ + JSON 契约稳定 │ →  │ + 首个非A股Source│ →  │ 社区数据源生态   │
│ 筛选 DSL         │    │ + PE/资金流补齐 │    │ + Hub 策展目录   │    │ "manmankan 协议" │
│ 自选股管理       │    │ + Skills.md能力 │    │ + DataProvider   │    │ A 股 AI 数据标准 │
│ 分组管理         │    │ + 周期 2-360   │    │ + 本地 Web 可视化│    │                  │
│                  │    │ + 量能 filter  │    │                  │    │                  │
└─────────────────┘    └─────────────────┘    └──────────────────┘    └──────────────────┘
```

详见 [`docs/roadmap.md`](roadmap.md)。

---

## 六、设计原则

1. **数据原值优先**：manmankan 输出裸数据而非判断。位置百分位是原值，"低位"是 AI 自己的解读。唯一例外是公开阈值的分类标签（如 <20%=低位区），且阈值透明可查。

2. **优雅降级**：一个数据源挂了 → 其余字段照常返回 + 失败的标为 `null`。全有或全无是不可接受的。

3. **低上下文成本**：默认输出不应超过 AI 上下文窗口的合理比例。AI 可以按需索取更多字段，但不能被无关数据淹没。

4. **本地优先**：零云依赖、零遥测、本地 SQLite/Parquet 存储。AI 不依赖外部服务即可消费数据。

5. **合规红线硬编码**：输出不含"推荐""看好""低估""目标价"等词。免责声明自动注入，不由命令调用者选择。

6. **开放生态**：manmankan 是开放协议的一部分——任何 LLM 都可以消费，不被特定 AI 厂商锁定。MCP 是开放标准，Skills.md 是开放格式。

---

*最后更新：2026-06-04 · 与 `README.md` / `roadmap.md` / `compliance.md` 互为补充*
