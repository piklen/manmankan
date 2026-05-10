# 安全策略

慢慢看（manmankan）是 self-hosted A 股自选股 CLI 工具 · 完全本地运行 · 不上传任何用户数据到远端。

## 漏洞报告

请通过 GitHub Private Vulnerability Reporting (PVR) 提交：

  https://github.com/piklen/manmankan/security/advisories/new

**勿在 public issue 中披露漏洞** —— 这违反 CVD（Coordinated Vulnerability Disclosure）原则。

预期响应：
- 7 天内首次回复
- 30 天内提供修复方案或 ETA
- 严重漏洞按 CVSS 3.1 评级 · 适用时申请 CVE

## 范围

报告以下类别的安全问题受欢迎：

- 仓内 Python 代码漏洞（命令注入 / 路径遍历 / 反序列化等）
- 直接依赖的安全问题（akshare / typer / rich / pandas / pydantic 等）
- AKShare 数据源响应被恶意注入导致的本地代码执行风险
- CSV import 路径校验缺失（已知技术债 · 可补充其他攻击向量）

## 不在范围内

- 用户的本地数据隐私（self-hosted CLI · 用户自管 `~/.local/share/kan/` 目录）
- 第三方数据源（AKShare / 新浪 / 东方财富）的合规问题（请联系数据源方）
- A 股市场行为 / 盘面数据本身（不是工具问题）
- 用户自己跑 `kan import` 时引入的恶意 CSV 文件（CLI 工具用户对自己的输入负责 · 路径校验在路线图）

## 已知非漏洞

- `~/.local/share/kan/watchlist.json` 是明文 JSON · 这是设计 · 不是漏洞（CLI 工具数据完全自管）
- `~/.local/share/kan/data/*.parquet` 缓存可被本机用户读取 · 这是设计

## 公开披露

修复发布后 · 我们鼓励 reporter 在 advisory 中公开漏洞细节 · 帮助生态了解和防范。

---

*Last updated: 2026-05-10*
