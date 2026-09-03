# 中国用户快速开始

这份文档首先面向普通 A 股用户：目标是在国内常见网络环境下打开本地选股研究工作台，完成规则运行、候选复看、数据更新和持仓查看。CLI、JSON、AI / MCP 接入放在后续进阶章节。

`manmankan` 是本地工具:不需要 manmankan 账号,不向 manmankan 服务上传自选和持仓,不做云同步或遥测。查询行情时会向所选数据源发送股票代码;配置 TuShare 时,token 只发送到你配置的数据源。持仓成本、股数和现金不会发送。工具只提供行情数据坐标和用户显式规则命中结果,不提供买卖建议、评级、目标价或涨跌预测。

## 1. 最短可用路径

```bash
uv tool install manmankan
kan web
```

浏览器会打开只监听本机的趋势发现页。可以先按行业/题材、收盘连续/阳线连续、方向和天数查看板块趋势，复核近日日涨跌后点击“用本板块选股”；网页只带入对应成分股，不会自动添加选股条件。也可以直接进入 Screen 工作台，选择自选、持仓、全市场、行业、题材或自定义代码池，再添加客观条件并点击“保存并运行”；结果右侧可核对实际值、阈值、来源和数据日。把需要继续核对的对象加入候选池，或建立 3–10 股对比组。

如果浏览器没有自动打开，请复制终端刚打印的完整地址。地址带有本次启动随机生成的会话凭证，站内页面会保留访问状态；不要把完整地址发给别人，直接手输 `127.0.0.1` 也不会绕过保护。“市场与数据”页可更新默认池或全市场，进度和部分失败会写入 SQLite；首次更新可能需要数十秒到数分钟，后续同日运行会复用缓存。

开发者或自动化脚本要验证安装和 JSON 契约,再运行:

```bash
kan --version
KAN_NO_UPDATE_CHECK=1 kan help
KAN_NO_UPDATE_CHECK=1 kan screen filters --format json
NO_COLOR=1 KAN_NO_UPDATE_CHECK=1 kan find --codes 600519,000858 --format json --dry-run
KAN_NO_UPDATE_CHECK=1 kan scan --codes 600519,000858 --periods 5,20,60,180 --format json
```

`kan screen filters` 发现新版稳定条件契约；`kan find --dry-run` 只验证兼容入口、JSON envelope、免责声明、退出码和查询计划，不拉行情；`kan scan` 才验证真实日 K 数据路径。完整 Screen CLI 见 [`selection-workbench.md`](selection-workbench.md)。

旧版本已有 `config.json / watchlist.json / positions.json` 时，新版会在接管前保留 `.vnext-backup`。可用 `kan workspace status` 查看状态，完整回滚手册见 [`workspace-migration.md`](workspace-migration.md)。

### 日涨跌幅历史复核

想知道一只股票过去下跌或上涨到某个幅度之后，当天最后怎么收盘，可以直接运行：

```bash
kan range 600519
```

不需要先录入持仓、成本或阈值。默认对照近 **5/15 个完整交易日**和 **75/85/90/95 四档**；单股与批量都完整展示，同一档位的两个周期紧挨着。

按三个问题读表：

1. **到了什么幅度？** 例如 `-3% / 19.40元`：若本次参考收盘为 20 元，下降 3% 折算为 19.40 元。这是算术示例，不是价格判断；日涨跌幅相对前收，不是持仓盈亏。
2. **过去有多少天到过？** `2/5天` 就是 5 个样本日中有 2 天到过该幅度。
3. **这些天怎么收盘？** `收回 1/2次（50%）` 表示那 2 天中有 1 天收盘高于下跌线；`收涨` 则是收盘高于当日前收，不能与收回次数相加。上涨表对应的是收盘是否守住上涨线，收盘等于线也算守住。

`95%档` 是历史幅度的分位估计，不是“未来95%的时候不会越过”；只有 5 个交易日，也不会变成 100 次实验。每档下方的“未越”表示本窗口实际没有越过该幅度的天数比例，恰好到线也会计入触及，因此未越与到过不一定相加为 100%。短窗口包含在长窗口内，并非两组独立验证。

已经有自己想核对的幅度，再填进去：

```bash
kan range 600519 --down 3 --up 7
kan range --codes 600519,000858 --down 3 --up 7
kan range 600519 --periods 10,30 --levels 80,92.5
```

`--down 3` 表示核对下跌 3%，`--up 7` 表示核对上涨 7%；数字仅演示输入，可替换，两个方向都接受显式 `0`。输出会先回答你输入的幅度在每个窗口中到过几天、后来怎么收盘，再给历史档位对照。若显示 `0/5 天到过；无触及样本`，表示无从统计触及后的结果，**不是以后不可能到达**。有 `1/1次（100%）` 时也只能读作一例。

顶部同时给出数据截止日、来源、参考收盘和有效样本数；折算价不是实时价、历史事件价或成交保证，跨日需要重算。日 K 不能还原盘中先后、水下持续时间或实际成交。收盘中位、最高至收盘回落、数据剔除明细可用 `--format json` 复核。批量按输入顺序展示，不排序、不代选档位、不生成交易动作。

## 2. Windows / PowerShell 首跑样本

PowerShell 不能用 `KAN_NO_UPDATE_CHECK=1 kan ...` 这种 Bash 写法，环境变量要先写进 `$env:`。如果你要复制 JSON，建议同时打开 `NO_COLOR` 和 `PYTHONUTF8`：

```powershell
uv tool install manmankan
kan --version
$env:KAN_NO_UPDATE_CHECK = "1"
$env:PYTHONUTF8 = "1"
$env:NO_COLOR = "1"
kan find --codes 600519,000858 --format json --dry-run
```

观察台请在另一个 PowerShell 窗口单独运行 `kan web`；该命令会持续占用前台，按 `Ctrl+C` 才会退出。

脱敏后的实测输出形态应接近：

```text
Installed 1 executable: kan
kan <version>
```

```json
{
  "ok": true,
  "command": "find",
  "mode": "query_plan",
  "dry_run": true,
  "rule": {
    "pools": ["codes:2"],
    "filters": []
  },
  "disclaimer": "候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · 不构成任何形式的推荐或建议 · 用户自行评估"
}
```

`$env:PYTHONUTF8 = "1"` 用来避免部分 Windows 终端在输出中文或 `≠`、`·` 这类符号时触发编码错误。保留这行没有副作用。

## 3. PyPI 下载慢

如果访问 PyPI 慢，可以临时指定镜像：

```bash
uv tool install manmankan --index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
```

如果你希望 `uv` 长期使用镜像，可以在用户级配置里设置索引。TUNA 的 PyPI 帮助页给出的 `uv` 配置形态是：

```toml
# macOS / Linux: ~/.config/uv/uv.toml
# Windows: %AppData%\uv\uv.toml
[[index]]
url = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/"
default = true
```

参考：

- [TUNA PyPI 镜像帮助](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)
- [uv package indexes](https://docs.astral.sh/uv/concepts/indexes/)
- [uv environment variables](https://docs.astral.sh/uv/reference/environment/)

注意：不要把个人或公司内网镜像配置提交到本仓库的 `pyproject.toml`。项目级配置会影响所有贡献者和 CI；本地网络问题应放在用户级 `uv.toml` 或一次性命令参数里解决。

## 4. 行情源和网络代理

常见现象要分开判断：

| 现象 | 更可能的原因 | 先试什么 |
|---|---|---|
| `uv tool install` 慢 | Python 包下载慢 | 指定 PyPI 镜像 |
| `kan find --codes ... --dry-run` 可用，但 `kan scan ...` 慢或失败 | 行情数据源网络 / 限流 / 本地代理 | 稍后重试，或检查代理 |
| `kan find --all --pe ...` 报缺数据 | 需要 TuShare token 或积分权限 | 配置 TuShare token |
| `--all` 报 `tushare_data_contract_error` | 配置的 TuShare endpoint 返回了明显不完整的全市场响应 | 切回官方 endpoint，或检查兼容 endpoint 的 TuShare 契约实现 |
| `kan` 每次退出前卡在版本检查 | PyPI update check 慢 | 设置 `KAN_NO_UPDATE_CHECK=1` |

默认情况下，`manmankan` 会尽量让公开行情源直连，避免系统代理把行情请求带偏。如果你的网络必须走代理才能访问数据源，可显式保留代理：

```bash
KAN_KEEP_PROXY=1 kan scan --codes 600519,000858
```

如果你只想验证 JSON 输出，不想受颜色控制码影响：

```bash
NO_COLOR=1 KAN_NO_UPDATE_CHECK=1 kan find --codes 600519,000858 --format json --dry-run
```

## 5. TuShare 配置

不配置 TuShare 也能跑自选、行业、题材、外部代码池的 K 线位置类能力。以下能力通常需要 TuShare token 或上游权限：

- `kan find --all`
- 估值、资金、技术、筹码、股东、相对强度等截面维度
- 部分板块 / 指数对照数据

查看当前配置：

```bash
kan config get
```

配置 token：

```bash
kan config set tushare-token <你的_token>
```

如需自定义 HTTPS 端点：

```bash
kan config set tushare-endpoint https://api.tushare.pro
```

也可以用环境变量临时覆盖：

```bash
TUSHARE_TOKEN=<你的_token> kan find --all --pe lt:20 --format json --compact
```

不要把 token 贴到 issue、日志、截图或文档里。`kan config get` 会 mask token；`KAN_DEBUG=1` 也会做脱敏，但公开反馈前仍应人工检查。

## 6. 读懂 `data_unavailable`

`data_unavailable` 表示当前命令依赖的数据维度没有形成可用证据。它不是安装失败，也不是“没有符合条件的股票”。先看 `error.message` 判断缺的是哪类数据，再决定是配置 TuShare、换更小的代码池，还是去掉对应 filter。

小代码池 ROE 取数缺少财务数据时，JSON 形态类似：

```bash
NO_COLOR=1 KAN_NO_UPDATE_CHECK=1 \
  kan find --codes 600519,000858 --roe gt:10 --fields @core,@fundamentals --format json
```

```json
{
  "ok": false,
  "command": "find",
  "error": {
    "code": "data_unavailable",
    "message": "当前候选池缺少财务数据，无法执行 --roe filter",
    "hint": "例: kan config set tushare-token <你的_token>；或去掉对应 filter"
  },
  "schema_version": "0.0.6.8",
  "disclaimer": "候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · 不构成任何形式的推荐或建议 · 用户自行评估"
}
```

全市场估值截面不可用时，常见形态是：

```bash
NO_COLOR=1 KAN_NO_UPDATE_CHECK=1 kan find --all --pe lt:20 --format json --compact
```

```json
{
  "ok": false,
  "command": "find",
  "error": {
    "code": "data_unavailable",
    "message": "全市场截面无数据",
    "hint": "估值/量价/资金/行业分位依赖 tushare；例: kan config set tushare-token <你的_token>"
  },
  "schema_version": "0.0.6.8",
  "disclaimer": "候选 ≠ 买入信号 · 工具仅返回符合您设置规则的股票数据 · 不构成任何形式的推荐或建议 · 用户自行评估"
}
```

如果命令返回 `ok:true` 但某些字段是 `null`，说明这只影响对应维度，不等于整条命令失败。公开反馈时贴 envelope 即可，不要贴 token、私有路径、代理账号或账户截图。

## 7. 中国开发者贡献路径

```bash
git clone https://github.com/piklen/manmankan.git
cd manmankan
uv sync --frozen --all-groups --all-extras
KAN_NO_UPDATE_CHECK=1 uv run kan --help
KAN_NO_UPDATE_CHECK=1 uv run kan examples --format json
KAN_NO_UPDATE_CHECK=1 uv run kan fields list --format json
KAN_NO_UPDATE_CHECK=1 uv run kan mcp install --dry-run --format json
uv run pytest -q -m "not network and not tty"
uv run ruff check kan/ tests/
bash scripts/check-privacy-leaks.sh
```

`kan examples --format json`、`kan fields list --format json` 和 `kan mcp install --dry-run --format json` 用于确认机器可读 examples、字段 / preset 清单和 MCP 注册预览；都不拉行情，也不写 MCP 配置，适合先验证 AI / 自动化入口，再决定是否跑真实行情或完整测试。

如果依赖下载慢，优先使用用户级 `uv.toml` 或一次性 `--index-url`，不要改仓库的依赖配置。

贡献前先读：

- [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- [`AGENTS.md`](../AGENTS.md)
- [`docs/compliance.md`](compliance.md)
- [`docs/mcp.md`](mcp.md)

## 8. 反馈问题时请带上这些信息

- 操作系统：Windows / macOS / Linux / WSL
- Python 版本：`python --version`
- 安装方式：`uv tool` / `pipx` / venv / 源码
- 命令：完整贴出，不要省略参数
- 是否配置 TuShare token：只说“已配 / 未配”，不要贴 token
- 是否走代理：只说“直连 / 代理 / 公司内网”，不要贴代理账号
- 错误输出：优先贴 `NO_COLOR=1` 后的完整文本或 JSON envelope

可以贴的脱敏形态：

```text
TUSHARE_TOKEN=<redacted>
HTTPS_PROXY=http://<redacted>@proxy.example:7890
config path: /Users/<user>/... 或 C:\Users\<user>\...
持仓：约 N 只，金额已脱敏
```

不要贴真实 token、代理账号、完整本机路径、真实持仓金额或账户截图。

安全漏洞不要开公开 issue，按 [`SECURITY.md`](../SECURITY.md) 走 GitHub Private Vulnerability Reporting。
