# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] - 2026-05-10

### Added · 首次公开发布

**位置扫描** `kan scan`
- 多周期位置扫描（3/5/7/10/15/30/60/90/120/180 日）
- `--high` 高点模式 / `-S --signal` 仅显示有共振信号 / `--diff` 增量模式
- `--exclude-st` 排除 ST/*ST
- 多周期共振信号自动高亮（×N 标记）
- 终端宽度自适应（130+ 列 10 周期 · 100 列 6 周期 · 80 列 4 周期 · 共振列始终可见）

**筛选模式**
- `kan low N [N2 ...]` / `kan high N [N2 ...]` 触及阈值筛选（≤5% 低点 / ≥95% 高点 · 支持多周期）

**连续涨跌看板** `kan trend`
- `--latest N` 近 N 天走势
- `--down N` / `--up N` 筛选连续涨/跌（N 范围 2-30）
- `--candle` 阳线阴线口径
- 涨跌停自动标记
- 跨板块差异化涨跌停限制（按 2026-07-06 政策日期切换）

**单只详情**
- `kan info <代码>` 全周期位置 + 涨跌 + 共振统计

**自选股管理**
- `kan add` 支持代码 + 名称搜索 + 批量
- `kan remove` 支持名称 + 批量
- `kan list` / `kan import` / `kan clear`
- `kan uninstall` 一次清数据 + 输出包卸载命令（自动检测 uv tool / pipx / pip）

**数据层**
- 多源 K 线 fallback：`baostock → 新浪 → 东财 → 腾讯`
- 本地 Parquet 缓存（`~/.local/share/kan/data/` · XDG 规范）
- 7 天 A 股代码-名称缓存 + 自动过期更新
- `kan fetch [--force]` 手动刷新

**Shell 集成**
- `kan completion install [shell]` 一键启用 zsh / bash / fish / powershell 命令前缀补全
- 任意命令首次启动自动启用补全（`KAN_NO_COMPLETION_AUTOINSTALL=1` 可关闭 · 非 TTY 跳过）

**合规与隐私**
- 强制风险提示 + 关键词黑名单（无买卖建议 / 无目标价 / 无评级）
- 所有数据本地存储 · 不上传任何用户数据
- `CONTRIBUTING.md` + `SECURITY.md` + 公开输出语言纪律

[Unreleased]: https://github.com/piklen/manmankan/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/piklen/manmankan/releases/tag/v0.0.1
