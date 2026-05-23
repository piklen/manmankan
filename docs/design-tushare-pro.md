# TuShare Pro 数据源接入 · 设计方案

> 状态：设计完成 · 待实施（v0.0.5.0）· 分支 `feat/v0.0.5-tushare-pro`
> 最后更新：2026-05-23

## 1. 背景与目标

`kan` 当前 K 线数据 fallback 链：

```
baostock → akshare (东财+新浪并发) → 腾讯
```

三档全部免费、无需账号。但有两个痛点：

1. **稳定性**：baostock 周期性间歇不可用；akshare 三个分支均依赖第三方端点漂移（参 GitHub Issue #6092/#6148/#7011/#6214），整体可用性 ~99%。
2. **数据深度**：现有源仅日 K，无法扩展财务/分钟/复权因子等。

**TuShare Pro** 是付费 / 积分制 SaaS（[tushare.pro](https://tushare.pro)），鼠鼠付费即得：高稳定性 API、覆盖更广的金融数据宇宙、可控延迟。本功能为接入第一步 —— **仅日 K**，对齐现有 fetcher 能力。

### 目标

- 允许鼠鼠配置 **token + 端点** 两项后，让 TuShare Pro 顶替 baostock 作为 fetch_kline 主路径
- 未配 token 时 **零行为变化**（pure additive，零回归风险）
- 端点支持替换为自部署镜像 / 反代（默认 `http://api.tushare.pro`），不绑定官方 host
- 引入轻量配置子命令 `kan config`，未来其他配置项（如 `auto_update`）可平滑迁移

## 2. 非目标（明确不做）

- **官方 SDK 依赖**：不引入 `tushare` Python 包。SDK `DataApi` 把端点写死在私有 class 属性 `__http_url`，构造函数不接受自定义 URL，要替端点只能 monkey-patch 私有名。自写 ~50 行 HTTP client 反而更干净。
- **TuShare Pro 其它接口**：本轮只做 `daily`（日 K）。financial / minute / realtime / fund / future 留待后续，沿用同一 client 接口扩展即可。
- **多 token 轮换 / 负载均衡**：单 token 单端点，YAGNI。
- **HTTP/HTTPS 代理（HTTPS_PROXY 那种）**：用户原话"代理地址"指 API 端点替换，不是网络层代理。后者通过系统环境变量已天然支持，无需额外配置。
- **migrate auto_update 字段名**：保持 `auto_update` 当前 schema 不动，新字段 `tushare_token` / `tushare_endpoint` 共存。

## 3. 架构定位

```
fetch_kline(symbol, days, force):
  ├── 缓存命中 → 直接返回 (不变)
  ├── 若 _resolve_tushare_config() 拿到 token：
  │     └── _fetch_tushare(symbol, start)  ← 新增 · 顶优先
  ├── _fetch_baostock(symbol, start)
  ├── _fetch_via_akshare(symbol, start)       # 东财+新浪并发
  └── _fetch_tencent(symbol, start)
```

**关键不变量**：未配 token → tushare 分支跳过 → 走原路径，所有现有测试（479 通过）行为不变。

## 4. 文件改动清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `kan/tushare_pro.py` | **新增** | `_fetch_tushare()` + `_resolve_config()` + 自写 HTTP client (~80 行) |
| `kan/config.py` | 改 | `DEFAULT_CONFIG` 加 `tushare_token: None` + `tushare_endpoint: None` |
| `kan/fetcher.py` | 改 | `fetch_kline()` 头部插入 tushare 优先分支；source 名 `"tushare"` |
| `kan/cli_config_cmds.py` | **新增** | `kan config` typer subcommand 组（get / set / unset） |
| `kan/cli.py` | 改 | 末尾 import 新模块触发命令注册 |
| `kan/circuit_breaker.py` | 不动 | 复用，传入 `"tushare"` 作 source 名 |
| `tests/test_tushare_pro.py` | **新增** | 单元：mock requests POST；端点回退；token 优先级；env 覆盖；错误码处理 |
| `tests/test_config.py` | 改 | 新字段 default + load/save 兼容性 |
| `tests/test_cli_config.py` | **新增** | `kan config get/set/unset` 行为 + mask 显示 + env 提示 |
| `tests/test_fetcher.py` | 改 | tushare 优先 dispatch 1 例 + 未配 token 时路径不变 1 例 |
| `CHANGELOG.md` | 改 | v0.0.5.0 新条目 |
| `docs/design-tushare-pro.md` | **新增** | 本文档 |
| `docs/plan-tushare-pro.md` | **新增** | writing-plans 产出（下一步） |

总计：**4 改 6 新**。

## 5. 配置层

### 5.1 config.json schema 扩展

```json
{
  "auto_update": null,
  "last_check_date": null,
  "latest_seen_version": null,
  "last_hint_date": null,
  "tushare_token": null,        // 新 · 字符串或 null
  "tushare_endpoint": null      // 新 · null=用内置默认 http://api.tushare.pro
}
```

向后兼容（缺字段自愈，沿用 `config.py` 现有 load() 健壮性）；向前兼容（未知字段忽略，旧版 kan 读新配置不报错）。

### 5.2 解析优先级（高 → 低）

```
TUSHARE_TOKEN env    > config["tushare_token"]    > 无（关 tushare 分支）
TUSHARE_ENDPOINT env > config["tushare_endpoint"] > "http://api.tushare.pro"
```

由 `kan/tushare_pro.py::_resolve_config() -> tuple[str | None, str]` 集中处理，返回 `(token, endpoint)`，token 为 None 时上游跳过 tushare 分支。

### 5.3 端点 URL 校验

- 必须 `http://` 或 `https://` 前缀
- 空字符串 / 仅空格视为未配置
- 不做 DNS 解析（运行时 HTTP 错由 _fetch_tushare 兜底，回 fallback 链）

## 6. HTTP client（自写）

### 6.1 协议

TuShare Pro 单端点，全 POST JSON：

```http
POST {endpoint}/
Content-Type: application/json

{
  "api_name": "daily",
  "token": "<user-token>",
  "params": {"ts_code": "600519.SH", "start_date": "20250101"},
  "fields": "trade_date,open,high,low,close,vol,amount"
}
```

响应：

```json
{"code": 0, "msg": "", "data": {"fields": ["trade_date","open",...], "items": [["20250102","1500.0",...], ...]}}
```

`code != 0` 即视为业务错误（无权限 / 积分不足 / 限流），转 None 触发 fallback。

### 6.2 实现细节

- **股票代码归一化** `_normalize_symbol_to_ts(symbol)`：
  - `60xxxx` / `68xxxx` → `.SH`（上证主板 / 科创板）
  - `00xxxx` / `30xxxx` → `.SZ`（深证主板 / 创业板）
  - `8xxxxx` / `4xxxxx` / `9xxxxx` → `.BJ`（北交所 / 新三板精选）
  - 其他 6 位数字默认 `.SZ`（防御性回退）
- **超时**：30 秒（与 baostock/akshare 体感对齐）
- **重试**：单次重试，仅 429 / 5xx；4xx（除 429）不重试
- **字段映射**：`trade_date → date`，`vol → volume`，其他直名；归一化后交 `_normalize_kline(df, source="tushare")` 收口
- **Circuit breaker**：`circuit_breaker.is_down("tushare")` 检查 + `record("tushare", ok=...)`，复用现有机制

## 7. CLI 接口

### 7.1 命令组

```
kan config get                              # 列所有非默认字段；token mask
kan config set <key> <value>                # 设字段
kan config unset <key>                      # 清字段（回 None）
```

支持的 key（封闭集合，typer Enum）：
- `tushare-token`
- `tushare-endpoint`

注：使用短横线连字符（CLI 习惯），内部映射回下划线（Python 习惯）。

### 7.2 `kan config get` 输出

```
$ kan config get
tushare_token: ***xyz9   (set via config)
tushare_endpoint: <default: http://api.tushare.pro>

# env 覆盖时：
$ TUSHARE_TOKEN=foo kan config get
tushare_token: ***o     (set via TUSHARE_TOKEN env, overriding config)
tushare_endpoint: <default: http://api.tushare.pro>
```

- token 永远只显示末 4 位前补 `***`（少于 4 位全 mask 成 `***`）
- 未配置的字段不列（精简输出），但 endpoint 始终显示默认值（用户常想确认）
- env 覆盖时显式提示，避免"为什么 config set 不生效"困惑

### 7.3 `kan config set` 校验

| 字段 | 校验 |
|---|---|
| `tushare-token` | 去首尾空格；空串报错 `❌ token 不能为空`，exit 2 |
| `tushare-endpoint` | 必须 `http://` / `https://` 前缀；否则报错 `❌ 端点需以 http(s):// 开头`，exit 2 |

成功后输出：`✅ 已保存 tushare_token (***xyz9) 到 ~/.local/share/kan/config.json`

### 7.4 `kan config unset` 行为

设回 `None`，atomic 写入。已为 None 时输出 `ℹ️ tushare_token 已是默认值，无需清除`。

## 8. 安全 / 隐私

- token 永不出现在：日志、异常 message、circuit_breaker 状态、parquet 缓存元数据
- `kan config get` 是唯一 token 出口，必 mask
- `config.json` 已 `chmod 0o600`（沿用现有 `_atomic_write_json` 机制）
- HTTP 请求体里的 token 仅传给用户配置的 endpoint；自定义端点是用户自主选择，不做警告（鼠鼠知道自己在干什么）
- 错误处理时记得过滤：若 _fetch_tushare 异常抛出，message 里不能含 token（即便用户配错也不要在 traceback 里泄漏）

## 9. 测试策略

| 层 | 工具 | 覆盖项 |
|---|---|---|
| 单元 - tushare_pro | pytest + `monkeypatch` mock `requests.post` | POST 体格式（含 ts_code 规则）、字段映射、code≠0 返回 None、超时返回 None、429 重试、token 不在异常文本 |
| 单元 - config | 现有 test_config.py 扩展 | 新字段 default；load 缺字段自愈；save 写入 |
| 单元 - CLI | typer.testing.CliRunner | `kan config get` 空 / 已配 / env 覆盖 三态；`set` 校验失败；`unset` 幂等；mask 正确 |
| 集成（可选） | env-gated `KAN_TUSHARE_INTEGRATION=1` + 真 token | 实际 POST 到 tushare.pro 拉一只票；默认 skip，CI 不跑 |
| 回归 | 全 479 现有测试 | 不能挂；未配 token 时 fetcher 行为零变化 |

**TDD 顺序**：每一文件改动先红测后绿实现。tushare_pro 模块从最小测起（`_normalize_symbol_to_ts` → `_resolve_config` → `_fetch_tushare`）。

## 10. 合规

- TuShare Pro 只多了"数据来源"，**输出风险话术、`_source` 列、scan 行为、合规红线全部不变**
- 任何场景下不通过 TuShare Pro 拉数据后给出"建议/预测/目标价"
- `_source: tushare` 写入 parquet，便于未来跨源数值差异溯源

## 11. 关键 trade-off 记录

| 决策 | 选项 | 选了 | 理由 |
|---|---|---|---|
| 代理语义 | 端点替换 / HTTP proxy / 都做 | **端点替换** | 鼠鼠原话"默认官方但可自定义"语义对齐端点；HTTP proxy 已经能通过系统 env var 实现 |
| Fallback 位置 | 顶优先 / baostock 后 / 最末 / 显式 --source | **配 token 即顶优先** | 付费用户期望付费源被使用；未配 token 时零变化保证安全 |
| 配置 UX | `kan config` 子命令 / env-only / 手改 json | **`kan config` 子命令组** | 后续其他配置项可平滑迁移；env 仍可覆盖兼顾 CI |
| HTTP client | 自写 / SDK + monkey-patch / SDK + 子类 | **自写 ~80 行** | SDK 端点硬编码；自写无 transitive deps；风格与 fetcher.py 现有源一致 |
| 字段范围 | 仅 daily / 全 API | **仅 daily** | YAGNI；与现有 fetcher 能力对齐；扩展时复用同一 client |

## 12. 后续工作（不在本轮）

- TuShare Pro 其它接口接入（`daily_basic` 估值指标、`income` 财务、`fund_holding` 持仓）
- `kan config` 迁移 `auto_update` 进新命令组（当前由 `kan check-update --yes/--no` 隐式触发，可平移）
- 多端点轮换 / 自动切换镜像
- `kan doctor` 命令检查 token 有效性 + 积分余额
