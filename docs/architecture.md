# manmankan 架构愿景

> 撰写日期：2026-06-04 · 描述目标架构和设计原则，不等同于当前实现状态。

---

## 一、定位：一个事实层,两个产品出口

manmankan 的底层仍是行情数据翻译层,但产品不再以 AI Agent 为中心组织。用户优先级是硬约束:

1. **普通 A 股散户是唯一第一用户**:本地 Web 是默认产品入口,先回答今天发生了什么、数据是否可信、自己的股票处于什么位置。
2. **AI / 开发者是第二用户**:CLI、JSON、Python API 与 MCP 是高级出口,机器契约继续保持稳定,但不决定普通用户的首屏和术语。

两个出口必须复用同一套 service/domain 事实,不得复制位置计算、数据新鲜度或持仓逻辑。

```
┌─────────────────────────────────────────────────────────┐
│             Layer 3: 产品出口                              │
│  第一出口:本地 Web(今日 / 自选 / 持仓 / 找股票 / 数据设置)   │
│  第二出口:CLI / JSON / Python API / MCP                    │
├─────────────────────────────────────────────────────────┤
│                 ★ Layer 2: 数据中间层 ★                    │
│                     manmankan 在这里                      │
│  筛选  ·  位置语义  ·  共振检测  ·  合规包装  ·  低 token   │
│  输出:可复用的扫描 / 新鲜度 / 持仓 / 筛选结果                │
├─────────────────────────────────────────────────────────┤
│                 Layer 1: 数据基础设施                       │
│  tushare / akshare / baostock / Wind / iFinD / ...       │
│  裸数据  ·  字段多  ·  噪音大  ·  AI 直接消费成本高          │
└─────────────────────────────────────────────────────────┘
```

**为什么仍需要中间层？**

原始数据源（tushare 等）的问题：
- 字段多（几十个）、命名不一致,普通用户和 AI 都不应直接理解上游 schema
- 没有"位置""共振"等语义概念——只有裸价格，没有坐标
- 没有稳定的筛选和位置语义,每个出口都会重复实现
- 没有一致的中性表达,Web、CLI 和 AI 出口容易产生不同口径

manmankan 做的事：
- 数据筛选 → 普通用户先看到少而关键的事实,机器调用也减少无关字段
- 语义增强 → 加入"位置百分位""共振""板块资金排名"等可复核概念
- 中性包装 → 输出自带 `disclaimer`,所有出口不带方向性结论
- 多源聚合 → tushare/akshare/baostock 自动 fallback,上层不关心数据来自哪里

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
  │     └── DataProvider: AkShare / 公开 HTTP (题材位置)
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

**当前状态**：Source 抽象尚未在代码中实现（当前 data/ 层直接耦合了 akshare/tushare）。提取 Source 接口是中期架构目标，不阻塞当前功能迭代。

---

## 三、产品出口设计

### 3.1 普通用户消费(本地 Web)

- 默认入口是 `kan web`,不要求用户先学习命令、周期参数或筛选 DSL。
- 今日页默认展示 30 / 60 / 180 日关键周期、数据截止日和上一份快照以来的变化。
- 自选、持仓、现金和筛选都能在 Web 内完成,失败状态必须包含恢复动作。
- 完整十周期表和高级等价 CLI 按需折叠,避免把工程能力直接铺到普通用户首屏。

### 3.2 终端消费(CLI)

- Rich 表格、颜色、emoji、对齐
- `kan scan` 默认终端表格
- `kan history` ASCII K 线图

### 3.3 AI / 脚本消费(JSON)

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

### 3.4 Agent 消费(MCP + Skills.md)

- **Skills.md**：`skills/manmankan-skill.md` 是给 AI Agent 的能力清单——Agent 读到就知道所有命令、参数和典型用法
- **MCP Server**：`kan mcp serve` 在 CLI 契约上提供 stdio MCP；`kan mcp http` 提供本机 Streamable HTTP endpoint；`kan mcp install` 负责注册到常见用户级客户端配置
- **退出码语义**：0=成功，非 0=具体错误类别，Agent 不需要解析 stderr

---

## 四、数据管道

```
用户入口 (Web / CLI / MCP / API)
       │
       ▼
┌──────────────────┐
│  入口适配层         │  FastAPI / typer / MCP · 参数校验
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

- **入口适配层**(`kan/web/`、`kan/cli/`、`kan/mcp/`)只做交互、参数校验和序列化,不复制业务计算
- **服务层**（`kan/service/`）承载所有出口复用的业务事实,核心逻辑不与 FastAPI、typer 或 MCP 耦合
- **数据层**（`kan/data/`）使用责任链模式——依次尝试多个 DataProvider，第一个成功即返回
- **缓存层**（`kan/infra/`）基于 XDG 规范，增量更新策略
- **快照隔离**:CLI diff/history 与 Web 每日概览使用独立命名空间;Web 只在全部候选到达正常交易日时按行情截止日写入版本化快照
- **本地 Web 安全边界**:只监听回环地址;每次启动签发随机会话,页面导航保留会话参数、API 使用会话请求头、SSE 使用会话参数;写请求继续叠加 Host / Origin / 自定义头检查
- **渲染层**（`kan/render/`）终端和 JSON 走不同 code path，互不污染

---

## 五、演进路线

```
现在                         近期 (下一批)          中期                    远期
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ 本地 Web 日常闭环│    │ 首用与复看验证  │    │ + Source 接口抽象 │    │ 多市场支持       │
│ CLI + JSON 输出  │ →  │ 错误恢复与可用性│ →  │ + 首个非A股Source│ →  │ 社区数据源生态   │
│ 位置扫描 / 筛选  │    │ + JSON 兼容维护 │    │ + Hub 策展目录   │    │ "manmankan 协议" │
│ 自选 / 持仓管理  │    │ + Skills.md同步 │    │ + DataProvider   │    │ 开放数据标准     │
│ MCP stdio/http   │    │                  │    │                  │    │                  │
└─────────────────┘    └─────────────────┘    └──────────────────┘    └──────────────────┘
```

详见 [`docs/roadmap.md`](roadmap.md)。

---

## 六、设计原则

1. **数据原值优先**：manmankan 输出裸数据而非判断。位置百分位是原值，"低位"是 AI 自己的解读。唯一例外是公开阈值的分类标签（如 <20%=低位区），且阈值透明可查。

2. **优雅降级**：一个数据源挂了 → 其余字段照常返回 + 失败的标为 `null`。全有或全无是不可接受的。

3. **渐进披露**：普通用户默认只看关键事实,完整周期和高级参数按需展开；AI 默认输出不超过上下文窗口的合理比例。

4. **本地优先**：零云依赖、零遥测、本地 SQLite/Parquet 存储。普通用户无需账号,AI 也不依赖外部服务即可消费数据。

5. **合规红线硬编码**：输出不含"推荐""看好""低估""目标价"等词。免责声明自动注入，不由命令调用者选择。

6. **开放生态**：manmankan 是开放协议的一部分——任何 LLM 都可以消费，不被特定 AI 厂商锁定。MCP 是开放标准，Skills.md 是开放格式。

---

*最后更新：2026-07-10 · 与 `README.md` / `roadmap.md` / `compliance.md` 互为补充*
