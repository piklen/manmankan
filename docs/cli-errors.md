# CLI 错误输出规范

manmankan 的用户面错误信息保持三段式：

```text
❌ 问题本身
   为什么不能继续 / 缺什么条件
   例: kan <command> ...
```

约束：

- 必须说明失败原因，不只给退出码。
- 面向用户的修复提示必须包含 `例:` 和可复制命令。
- `--format json` 的错误用 `ok:false` + `error.code/message/hint`，`hint` 同样保留 `例:`。
- 不输出买卖建议、推荐、强弱判断、token 原文、endpoint 查询参数等敏感或误导信息。

当前自动化重点覆盖 `kan find`：filter grammar、pool 互斥、`--all` 约束、`--fields` / `--compact` 约束、缺数据与空交集路径。
