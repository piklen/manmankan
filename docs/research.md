# 研究证据包

`ResearchRequest → ResearchBundle` 将明确股票代码的行情、估值与财务等事实整理成可引用的研究材料。CLI、Python 和 MCP 调用同一个服务，不调用模型、不预置筛选规则、不读取个人持仓或现金。

## 使用

```bash
kan research 600519
kan research 600519 000858 --format json
kan research 600519 --dimensions market,valuation,technical --format json
kan research 600519 --dimensions market --format json
kan research 600519 --dimensions fundamentals --refresh --format json
```

一次接受 1–20 个明确代码，保持输入顺序；重复代码归一化后去重。默认请求 `market,valuation,fundamentals`，另有 `moneyflow,technical,sentiment,chip,shareholder`。各维度独立按需取数：单独请求 `fundamentals` 不拉行情，请求 `market` 才获取历史行情并输出 20/60/180 日位置与区间涨跌；不足窗口返回 `null`。

`--refresh` 跳过所请求维度的缓存，重新获取数据。财务缓存最多复用24小时，过期后下次查询自动检查来源；旧缓存首次使用时补取公告日。同一报告期存在多次披露时取公告日最新的一条。该机制按查询触发，不需要后台调度。

```python
from kan.api import ResearchRequest, build_research_bundle

bundle = build_research_bundle(ResearchRequest(
    codes=["600519"],
    dimensions=["fundamentals"],
    refresh=True,
))
print(bundle.model_dump_json())
```

MCP 工具 `kan_research` 使用相同请求字段，并发布严格的 `ResearchRequest` / `ResearchBundle` schema。通过 `kan schema --section commands --format json` 和 MCP `tools/list` 发现入口。

## 证据与状态

| 字段 | 语义 |
|---|---|
| `bundle_id` | 请求与证据引用的内容标识；生成时间不参与计算 |
| `generated_at` | 本次组织材料的 UTC 时间，不能当作数据日期 |
| `expected_trade_date` | 本次检查对应的最新完整交易日 |
| `subjects[].evidence_refs` | 指向本包 `evidence[].evidence_ref`，不指向远端网页或已持久化数据库记录 |
| `evidence[].source` | 现有数据服务提供的来源标签；未知为 `null` |
| `data_date` | 该维度真实数据日，不用包的生成时间填充 |
| `report_period` | 财务报告期；不是公告日 |
| `announcement_date` | 财务来源返回的公告日；未取得时为 `null` |
| `fetched_at` | 财务使用本地缓存成功写入的 UTC 时间，命中缓存不更新；行情沿用现有缓存时间标记，其他维度未保留时为 `null` |
| `facts` | 明确字段、中文名称、值、单位、必要的交易日窗口 |
| `missing_fields` | 请求字段中没有有效值的项目；0 和缺失有不同含义 |
| `errors` | 股票取数或指标补充失败；只描述失败阶段，不返回原始异常或凭据 |

新鲜度分为 `fresh / stale / unknown / unavailable`。日频数据的 `fresh` 表示有来源且数据日与预期一致。财务的 `fresh` 表示来源在24小时内检查过，且报告期、公告日均已取得；它不表示今天披露，也不能证明上游没有漏掉新公告。缺少披露时间的财务和股东数据保留 `unknown`。终端统一显示“已核对”，并列出各自时间口径。

没有源交易日的日频指标行不进入证据，避免旧转换器把查询日补成数据日。新鲜度不能证明数值、复权基准或模型结论正确。

`status=complete` 表示请求字段齐全且所有证据达到对应维度的新鲜度要求；`partial` 表示存在缺失、陈旧、未知日期或部分失败；所有请求维度均无可用事实时为 `unavailable`。`ok` 表示取数/编排没有报告执行错误，因此可以同时出现 `ok=true,status=partial`。CLI 参数错误退出 2，执行错误退出 1，成功返回但质量不完整退出 0；MCP 的 `isError` 与执行错误对应。批量部分失败仍保留成功股票及证据；行情失败也保留已取得的财务等指标。

已知单位的金额统一成元：市值与主力净额从万元换算；比例保持百分数，PE/PB 等保持倍数。`sentiment.fd_amount` 的上游文档未明确单位，保留原值并标记“源单位未核实”，不乘入猜测的系数。`sentiment.limit` 同时保留 U/D/Z 事件类型。筹码成本属于上游估算，不代表真实账户持仓成本。

## AI 使用顺序与边界

1. 根据明确研究问题选择代码和维度，先读较小事实包。
2. 核对逐维度日期、来源、缺失及限制；需要更多指标时显式补取维度。
3. 引用包内证据时使用原始 `evidence_ref`；不能把“引用存在”当成“它证明了某个判断”。
4. 保留事实与解释的区别；没有对应证据时明确缺口，不用模型补造数值或替换计算。

本入口尚未接入公告正文、新闻、现金流量表、完整研究会话或成交复盘。财务已支持公告日与按需刷新；股东数据仍沿用90日缓存，可显式刷新。行情沿用现有前复权缓存，尚未在本入口验证跨除权基准一致性。上游缺数和历史复权仍是后续数据建设事项。

研究包不自动保存、不调用 LLM，不等于完成了 AI 判断或交易计划。`kan find` / `kan screen` 负责条件执行，`kan range` 提供历史日内范围事实；这些入口的计算继续由各自已有服务负责。
