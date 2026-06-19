---
name: 🐛 Bug 上报
about: 报告慢慢看的 bug · 中文优先
title: "[Bug] "
labels: bug
assignees: ""
---

## 现象

<!-- 你看到了什么？最好贴 terminal 完整输出（敏感信息脱敏）-->

## 最小 smoke

请先跑下面两条，并贴完整输出。它们不拉行情，只验证安装、入口、JSON envelope 和免责声明。

macOS / Linux:

```bash
KAN_NO_UPDATE_CHECK=1 kan --version
NO_COLOR=1 KAN_NO_UPDATE_CHECK=1 kan find --codes 600519,000858 --format json
```

Windows / PowerShell:

```powershell
kan --version
$env:KAN_NO_UPDATE_CHECK = "1"
$env:PYTHONUTF8 = "1"
$env:NO_COLOR = "1"
kan find --codes 600519,000858 --format json
```

## 复现步骤

1.
2.
3.

## 期望行为

<!-- 你认为应该是什么样？ -->

## 环境

- 操作系统（macOS / Linux / Windows）：
- Python 版本（`python --version`）：
- manmankan 版本（`kan --version`）：
- 终端宽度（列数 · 影响表格渲染）：
- 终端类型（iTerm / Terminal.app / Windows Terminal / VS Code 等）：

## 数据相关

- 你跑的命令：
- `kan find --codes ...` 是否正常：
- `kan scan --codes ...` 是否正常：
- 自选股池大小（`kan list | wc -l`）：约 N 只
- 数据是今天的吗（看 `kan scan` 标题"X 更新"）？
- 是否配置 TuShare token（只填“已配 / 未配”，不要贴 token）：
- 是否使用代理（只填“直连 / 代理 / 公司内网”，不要贴代理账号）：

## 脱敏示例

可以贴：

```text
TUSHARE_TOKEN=<redacted>
HTTPS_PROXY=http://<redacted>@proxy.example:7890
config path: /Users/<user>/... 或 C:\Users\<user>\...
持仓：约 N 只，金额已脱敏
```

不要贴真实 token、代理账号、完整本机路径、真实持仓金额或账户截图。

## 其他线索

<!-- 截图 / 异常 traceback / 你的推测。不要贴 token、私有路径、真实持仓金额或代理账号。 -->
