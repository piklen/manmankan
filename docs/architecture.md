# manmankan 当前架构与演进边界

> 当前实现 SOT · 2026-08-24。趋势发现与 Screen 领域细节见 [`selection-workbench.md`](selection-workbench.md)。

---

## 一、定位：一个 Python 事实核心，五个产品入口

manmankan 的底层仍是行情数据翻译层，但默认产品已经从“今日观察页”迁移为可复跑选股研究工作台。用户优先级是硬约束：

1. **普通 A 股用户是第一用户**：本地 Web 默认完成 Board Trend → Screen → Run → Candidate → Compare → 复看 diff。
2. **CLI / Python / HTTP / MCP 是同级适配器**：都执行同一个 Python application service，不复制筛选逻辑。
3. **AI 是 typed contract 的消费者**：可以解析明确阈值、规划、运行和解释证据，不能成为指标或候选计算真相源。

所有入口必须复用同一套 domain/service 事实，不得复制位置计算、数据新鲜度、排序、证据或持仓逻辑。

```
┌─────────────────────────────────────────────────────────┐
│             Layer 3: 产品入口                              │
│ React Web · Typer CLI · kan.api · FastAPI /api/v1 · MCP   │
├─────────────────────────────────────────────────────────┤
│                 ★ Layer 2: 数据中间层 ★                    │
│                     manmankan 在这里                      │
│ BoardTrendSnapshot · ScreenRun · 证据 / diff · 候选 / 对比   │
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
  │     └── DataProvider: TuShare Pro 优先 / AkShare THS + 东财 EM fallback (题材位置)
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

**当前状态**：A 股 K 线和截面指标已分别实现 `KlineSource` / `MetricsSource`
Protocol、provider 注册与责任链；市场级 `Source` 聚合及多市场路由尚未实现，
部分数据领域也仍直接调用具体 provider。后续扩展市场时应在现有领域 Protocol
之上补市场级路由，不重复建设已经落地的 provider 抽象。

---

## 三、产品出口设计

### 3.1 普通用户消费（React Web）

- 默认入口是 `kan web`，生产由 Python 同源托管预构建 SPA，不要求用户安装 Node 或运行第二个服务。
- 首页是趋势发现：行业/题材指数使用同一连续涨跌口径，选中板块后只把成分股池带入 Screen，不预置筛选条件。
- Screen 工作台继续负责保存/复制/版本化规则、运行、证据、历史与 diff；板块榜不建立第二套股票筛选器。
- 候选、对比、个股研究、市场数据、持仓和设置是独立页面，但都消费 `/api/v1` typed model。
- 开发期 TypeScript 类型从 OpenAPI 生成；React 不重算指标，也不直接访问 provider 或 SQLite。
- 旧 Jinja 模板和手写业务 JavaScript 已经删除；旧 `/api` 只作为暂时兼容层隐藏于 OpenAPI。

### 3.2 终端消费(CLI)

- `kan screen` 提供规则发现、保存、版本、恢复、执行与运行历史。
- `kan find / scan / history` 等原命令继续兼容，适合一次性查询。
- `--format json` 使用稳定 envelope，业务失败不泄漏 traceback。

### 3.3 Python / HTTP 消费

- `kan.api` 公开导出 Board Trend、Screen 类型和 application service；用户脚本不需要 import 内部 storage/service。
- FastAPI 只在 `/api/v1` 暴露 OpenAPI；`/boards/trends`、Screen 与其他资源都以 Pydantic 作为请求/响应 SOT，并生成 TypeScript 类型。
- Web 写请求叠加本机会话、Host、Origin 和自定义 header 检查。

### 3.4 AI / 脚本消费（JSON）

所有数据查询命令（`scan` / `find` / `info` / `history` / `board rank` / `board trend` / `trend`）支持 `--format json`：

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

### 3.5 Agent 消费（MCP + Skills.md）

- **Skills.md**：`skills/manmankan-skill.md` 是给 AI Agent 的能力清单——Agent 读到就知道所有命令、参数和典型用法
- **MCP Server**：`kan mcp serve` 提供 stdio；`kan mcp http` 提供本机 Streamable HTTP endpoint；`kan mcp install` 负责注册客户端。
- **Screen tools**：`kan_screen_parse / plan / run / get / explain` 直接调用 Python service，不 shell 到 CLI，也不允许任意 SQL/Pandas。
- **退出码语义**：0=成功，非 0=具体错误类别，Agent 不需要解析 stderr

---

## 四、数据管道

```
用户入口 (React Web / CLI / Python / HTTP / MCP)
       │
       ▼
┌──────────────────┐
│  入口适配层         │  FastAPI / typer / MCP · 参数校验
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  服务层 (Service) │  板块趋势 · Screen 编排 · 证据 · diff · 任务
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 数据/状态层        │  provider 责任链 + Parquet · SQLite WAL repository
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  适配输出          │  React JSON / 终端 / JSON / Markdown / MCP
└──────────────────┘
```

**关键设计决策**：

- **领域层**（`kan/domain/`）定义严格 `BoardTrendQuery / BoardTrendSnapshot / ScreenSpec / ScreenRun / CandidateList / CompareSet / WorkspaceJob`，未知字段 fail-fast。
- **入口适配层**（`kan/web/`、`kan/cli/`、`kan/mcp/`、`kan/api.py`）只做交互、参数校验和序列化，不复制业务计算。
- **服务层**（`kan/service/`）承载板块趋势加载/过滤/排序以及 Screen 编排、证据、diff、AI plan 和任务，核心逻辑不与 FastAPI、Typer、React 或 MCP 耦合。
- **数据层**（`kan/data/`）使用责任链模式——依次尝试多个 DataProvider，第一个成功即返回
- **TuShare 兼容边界**:公开适配器只实现官方 TuShare 的请求与响应语义；用户配置的替代 endpoint 必须可替换地兼容该契约。仓库不加入某个中转服务专属的默认行数、分页或扩展字段逻辑；全市场响应会在缓存前做中立完整性校验，偏差作为数据契约错误暴露
- **缓存层**（`kan/infra/`）基于 XDG 规范，增量更新策略
- **状态层**（`kan/storage/workspace_db.py`）用 SQLite WAL 保存版本化/关系状态；配置、自选和持仓由可回滚 facade 接管；行情不迁入 SQLite。
- **持久任务**：ScreenRun 和默认池/全市场刷新共用 `WorkspaceJob` 与 SSE；启动恢复把遗留运行态标为 `interrupted`。
- **快照隔离**:CLI diff/history 与 Web 每日概览使用独立命名空间;Web 只在全部候选到达正常交易日时按行情截止日写入版本化快照
- **本地 Web 安全边界**:只监听回环地址;每次启动签发随机会话,页面导航保留会话参数、API 使用会话请求头、SSE 使用会话参数;写请求继续叠加 Host / Origin / 自定义头检查
- **渲染层**（`kan/render/`）终端和 JSON 走不同 code path，互不污染

---

## 五、演进路线

```
现在                         近期                   中期                    远期
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Screen 工作台    │    │ 真实用户复看验证│    │ + 市场级 Source  │    │ 多市场支持       │
│ React + /api/v1  │ →  │ 规则模板导入导出│ →  │ + 首个非A股Source│ →  │ 社区数据源生态   │
│ CLI/Python/MCP   │    │ 证据回放能力增强│    │ + point-in-time  │    │ 开放数据标准     │
│ SQLite 持久状态  │    │ 契约兼容维护    │    │   数据边界       │    │                  │
│ Parquet 行情缓存 │    │                  │    │                  │    │                  │
└─────────────────┘    └─────────────────┘    └──────────────────┘    └──────────────────┘
```

详见 [`docs/roadmap.md`](roadmap.md)。

---

## 六、设计原则

1. **数据原值优先**：manmankan 输出裸数据而非判断。位置百分位是原值，"低位"是 AI 自己的解读。唯一例外是公开阈值的分类标签（如 <20%=低位区），且阈值透明可查。

2. **优雅降级**：一个数据源挂了 → 其余字段照常返回 + 失败的标为 `null`。全有或全无是不可接受的。

3. **渐进披露**：普通用户默认只看关键事实,完整周期和高级参数按需展开；AI 默认输出不超过上下文窗口的合理比例。

4. **本地优先**：零云依赖、零遥测；工作台关系状态使用 SQLite WAL，行情与截面缓存使用 Parquet，原 JSON 状态有可验证备份和回滚。普通用户无需 manmankan 账号。

5. **合规红线硬编码**：输出不含"推荐""看好""低估""目标价"等词。免责声明自动注入，不由命令调用者选择。

6. **开放生态**：manmankan 是开放协议的一部分——任何 LLM 都可以消费，不被特定 AI 厂商锁定。MCP 是开放标准，Skills.md 是开放格式。

---

*最后更新：2026-08-23 · 与 `README.md` / `selection-workbench.md` / `roadmap.md` / `compliance.md` 互为补充*
