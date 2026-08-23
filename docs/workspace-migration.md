# 工作台 SQLite 迁移与回滚

vNext 把需要事务和版本关系的本地状态放入 `workspace.sqlite3`。行情缓存仍是 Parquet；迁移不会把行情大表塞进 SQLite，也不会上传任何数据。

## 1. 存储位置

默认目录是 `$XDG_DATA_HOME/kan/`，未设置时为 `~/.local/share/kan/`：

| 数据 | 当前存储 |
|---|---|
| Screen、规则版本、ScreenRun、成员、候选池、对比组、每日板块复看、任务 | `workspace.sqlite3` |
| 配置、自选、持仓、现金 | SQLite `workspace_state`；旧 JSON 作为迁移输入/回滚出口 |
| K 线、全市场截面和其他行情缓存 | `data/` 下 Parquet 与既有缓存文件 |
| 原始 JSON 备份 | `config.json.vnext-backup`、`watchlist.json.vnext-backup`、`positions.json.vnext-backup` |

目录会尽量收紧为 `0700`，数据库和备份文件为 `0600`。SQLite 使用 WAL、外键和 `synchronous=FULL`；连接只做短事务，供 CLI 与本地 Web 跨进程共享。

## 2. 首次升级会发生什么

标准 XDG 路径上的 `config / watchlist / positions` 在首次读取时按 namespace 懒迁移：

1. 先用原有代码读取并校验 JSON。
2. 如果原文件存在且还没有备份，复制为不可覆盖的 `.vnext-backup`。
3. 在一个 SQLite 事务内写入校验后的 payload、来源 hash、migration record 和 backend 标记。
4. 后续读写该 namespace 使用 SQLite。

显式传入自定义 JSON 路径的测试或嵌入调用继续走 JSON，不会被全局接管。迁移不删除原 JSON；备份一旦存在也不会被后续运行覆盖。

如果希望在升级后立即迁移三类状态，而不是等各页面首次读取：

```bash
kan workspace status
kan workspace migrate
kan workspace status --format json
```

`migrate` 可重复运行；它更新相同 namespace，不会追加重复记录，也不会覆盖最初备份。

## 3. 如何验证

终端输出只报告 backend、已迁移 namespace 和备份路径，不回显 token、自选内容、持仓金额或其他状态值：

```text
工作台状态后端: sqlite
SQLite 命名空间: config, watchlist, positions
原始备份:
  · .../config.json.vnext-backup
  · .../watchlist.json.vnext-backup
  · .../positions.json.vnext-backup
```

建议核对：

- `kan workspace status` 显示 `sqlite`。
- `kan web` 的设置页显示状态后端为 SQLite。
- 自选分组、持仓股数、成本和现金与升级前一致。
- `kan screen list`、候选池和任务可以跨进程重开后继续读取。

不要手工编辑 SQLite、WAL 或 SHM 文件；需要机器可读诊断时使用 `--format json`。

## 4. 回滚到 JSON

```bash
kan workspace rollback --yes
kan workspace status
```

回滚顺序是：

1. 把 SQLite 中当前的 `config / watchlist / positions` 原子导出到对应 JSON，包含迁移后的修改。
2. 删除这三个 namespace 的 SQLite 副本和 migration record。
3. 把用户状态 backend 切为 `legacy`。

因此回滚不会拿旧备份覆盖迁移后的修改。`.vnext-backup` 仍保留最初升级前的证据。Screen、ScreenRun、候选、对比、每日板块复看和任务仍保存在 SQLite 中；回滚只切换原有三类用户状态，因为旧版本本来不认识 vNext 领域对象。每日复看使用现有 `workspace_state` 的独立 namespace，不提高 `PRAGMA user_version`，旧程序会安全忽略。

再次运行 `kan workspace migrate` 会从当前 JSON 重新接管并切回 SQLite。

## 5. 中断与恢复

- JSON 备份在 SQLite 事务前创建；事务失败不会留下“已迁移”记录。
- SQLite schema 用 `PRAGMA user_version` 递增升级；高于当前程序支持的版本会明确拒绝打开，避免旧程序误写新 schema。
- Web 进程重启时，遗留 `queued / running` 任务会标为 `interrupted`，不会伪装成成功。
- 市场刷新已经写入的 Parquet 保持有效；重新发起任务会复用新鲜缓存。

如果数据库文件本身损坏，不要删除原文件。先退出 `kan web`，保留 `workspace.sqlite3*` 和 `.vnext-backup`，再用 `kan workspace status` 收集非敏感错误并通过项目支持渠道反馈。
