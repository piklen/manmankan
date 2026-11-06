# 本地研究与个人资料

当前产品从市场观察进入趋势条件和历史证据；计算与交互契约见
[趋势与研究](trend-research.md)，架构见[当前架构](architecture.md)。

## 用户操作与保存边界

| 操作 | 保存内容 | 行情行为 |
|---|---|---|
| 浏览市场、核对趋势 | 不自动保存研究 | 使用同一截止日的本地事实，保留缺失分母 |
| 保存筛选 | 名称与 `TrendSearchQuery` | 不读行情、不创建历史研究 |
| 核对历史 | `StudyQuery`、运行摘要、事件与当次行情证据 | 完整范围、明确观察窗口，结果自动留存 |
| 管理个人池 | 自选、持仓来源、人工候选与笔记 | 成员管理不扫描行情；覆盖率在观察结果中呈现 |
| 更新数据 | 持久任务与行情缓存 | 明确范围；部分失败与中断可见 |

候选状态与笔记由用户明确修改。查询命中不会自动把股票加入个人池，刷新行情不会改写人工状态。
已有候选的来源、加入时间和其他列表的笔记保持原样。

## 当前程序入口

- 趋势条件：CLI `kan trend`、MCP `kan_trend`、Python `search_trends`，HTTP `/api/v1/trends/search`。
- 保存筛选：Web、TUI 与 Python `save_trend_search`；HTTP `/api/v1/trends/saved`。
- 历史研究：CLI `kan study`、Python `run_study`，HTTP `/api/v1/studies` 系列。
- 财务、估值等一次查询：`kan find`；公司证据包：`kan research` / MCP `kan_research`。
- 严格日线交集：[`kan ohlc`](ohlc-screen.md)，全部条件由用户明确填写。
- 板块原生指数与复看：`kan board trend` 和 `kan.api` 的 `query_board_trends`、`query_board_pulse`、`create_board_review`、`study_board_history`。这些 Python 研究函数没有同名 Web 页面或 HTTP 路由。

HTTP 的实际资源以 `/api/v1/openapi.json` 为准；前端类型从这一契约生成。
MCP 实际工具以 `tools/list` 或 `kan schema --section mcp --format json` 为准。

## 状态与历史资产

SQLite 保存用户状态、命名条件、研究索引和任务；Parquet 保存行情与研究事实。
旧 Screen 执行、AI parse/plan、对比组执行和相关 CLI/MCP 入口已移除。
已有数据库中的旧规则、运行、对比组、复看记录和候选来源引用原样保留；升级不执行删除、重写或清空。
需要查看这些历史原始记录时，可在数据库副本上使用对应历史版本；当前版本不重新解释旧执行协议。

个人配置、凭据、自选、持仓与现金的迁移/回滚方式见
[本地状态迁移](workspace-migration.md)。不把旧备份覆盖到已经修改的用户资产上。
