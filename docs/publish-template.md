# Publish manmankan 到 PyPI · 标准流程

> 适用于：v0.0.2 起的所有版本（含本身）。
> Trusted Publisher OIDC 已在 PyPI 后台配置完成 · 走 git tag 自动发布。

---

## 1. 工作机制

```
git tag v* → push → .github/workflows/release.yml 触发
  → ubuntu-latest runner
  → uv build (sdist + wheel)
  → pypa/gh-action-pypi-publish (Trusted Publisher OIDC · 无 token)
  → PyPI 上架
```

OIDC = GitHub Actions 用 short-lived id-token 向 PyPI 证明 repo + workflow 身份，
PyPI 后台「Trusted Publishers」中已关联 `piklen/manmankan` repo + `release.yml`，
所以 workflow 跑起来就能发布，不需要任何 secret / API token。

---

## 2. 发版 checklist（按版本号 vX.Y.Z 占位）

### 2.1 代码就绪

- [ ] `kan/__init__.py` 和 `pyproject.toml` 版本号一致 = `X.Y.Z`
- [ ] CHANGELOG.md 写好对应章节（Added / Changed / Fixed / Removed）
- [ ] `uv run pytest tests/ -x` 全绿
- [ ] `bash scripts/check-privacy-leaks.sh` 0 命中
- [ ] PR 合 main · main HEAD 是要发的 commit

### 2.2 打 tag + push

```bash
git checkout main
git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 2.3 看 workflow

```bash
gh run watch
# 或
gh run list --workflow=release.yml --limit 3
```

期望 26s 左右 success。

### 2.4 PyPI 验证（push tag 后 ~ 1 分钟）

```bash
curl -s https://pypi.org/pypi/manmankan/json | \
  python3 -c "import sys,json; print('latest:', json.load(sys.stdin)['info']['version'])"
# 期望: latest: X.Y.Z

pip install --upgrade manmankan
kan --version
# 期望: kan X.Y.Z
```

### 2.5 父仓库 submodule bump（如适用）

仅在父项目用 submodule 引用 manmankan 时执行：

```bash
cd <parent-repo>
git submodule update --remote manmankan
git checkout -b chore/bump-manmankan-vX.Y.Z
git add manmankan
git commit -m "chore: bump manmankan submodule to vX.Y.Z"
git push -u origin chore/bump-manmankan-vX.Y.Z
gh pr create
```

---

## 3. 失败排查

### 3.1 workflow 失败 · OIDC 报错

症状：workflow 跑到 publish step 失败 · 错误含 `trusted-publisher` / `id-token` /
`unauthorized` 关键字。

修：去 PyPI 后台 → manage/project/manmankan/settings/publishing → 确认 trusted
publisher 关联的 repo / workflow filename / environment 跟实际一致。

### 3.2 workflow 失败 · build 报错

症状：workflow 跑到 `uv build` 失败。

修：本地复现 `uv build` · 看是否 pyproject.toml 字段错 / 缺依赖 / 版本号冲突。

### 3.3 PyPI 已存在同版本

症状：`File already exists` 400 错误。

修：PyPI 不允许覆盖已发布版本 · 必须 bump 到下一个 patch（vX.Y.Z+1）重发。

### 3.4 凭据未就绪 · workflow 临时降级

仅当 Trusted Publisher 未配置完成的紧急场景（不应该是常态）：

```bash
export UV_PUBLISH_TOKEN=pypi-...  # project-scoped token from pypi.org/manage/account/token/
uv build
uv publish
```

> ⚠️ 这是 fallback · 不是默认流程 · 走完后立刻把 Trusted Publisher 配好回到 tag-trigger 路径。

---

## 4. 不可逆性 + 回滚

PyPI 不允许删除已发布版本。可以：

- **Yank**: 标记不推荐 · 老用户仍能装 · 新用户 `pip install manmankan` 跳过该版本。
  路径：`https://pypi.org/manage/project/manmankan/release/X.Y.Z/` → "Yank release"
- **Bump 重发**：发现严重问题立即 yank 旧版 + 修 bug + 发 vX.Y.Z+1 patch。

---

*runbook 模板 · 每次发版照此 checklist 走 · 不再为单个版本写 runbook。*
