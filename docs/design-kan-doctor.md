# 设计稿 · kan doctor + 熔断器持久化 + 系统代理诊断

> 状态：📐 设计稿 · 下一批 patch 落地（TD-2 + TD-3 + TD-4）
> 来源：设计评审 · 3 个开放问题已确认

---

## 背景

v0.0.1 已知痛点：
- 用户 macOS 系统代理被东财 push2his 服务端反爬 ban，但用户层无诊断手段
- fetcher.py 模块级 `_eastmoney_ok` 三态变量进程内不持久化 → 每次冷启动重新探测 5s
- 三源 fallback 透明性不够 · 用户不知道当前数据来自哪源

按熵减原则，verbose flag 被砍（kan doctor 承包诊断）。

---

## A. 新文件清单

| 文件 | 职责 |
|---|---|
| `kan/circuit.py` | 三态熔断器持久化模块。`Circuit` 类 + 模块级单例 + `get(source)` / `set_ok(source)` / `set_down(source)` API。内部 `threading.Lock` + 原子写（temp file → `os.replace`）。读时带文件级缓存避免每次 `_fetch_*` 都 IO。 |
| `kan/doctor.py` | `kan doctor` 实现。子模块函数：`check_proxy()`、`probe_sources()`（用 `urllib.request` HEAD + 3s timeout）、`load_circuit_state()`、`pkg_versions()`、`cache_stats()`。返回 dataclass，由 `cli.py` 渲染 Rich Table。 |
| `tests/test_circuit.py` | 持久化往返、过期、并发写、损坏 JSON 自愈。 |
| `tests/test_doctor.py` | proxy mock、source probe 全 mock（不打真实网络）、Table 渲染 smoke。 |

---

## B. 修改文件清单

### `kan/paths.py`
加 `CIRCUIT_PATH = BASE_DIR / "circuit.json"`（注意是 `BASE_DIR` 不是 `DATA_DIR`，跟 `WATCHLIST_PATH` 同级，避免被 `kan fetch --force` 误删）。

### `kan/fetcher.py`
- 删 模块级 `_eastmoney_ok`、相关 `global` 写入
- `_fetch_eastmoney` 改用 `circuit.get("eastmoney")` / `circuit.set_down("eastmoney")` / `circuit.set_ok("eastmoney")`
- baostock / sina / tencent 也接入（baostock 失败也熔断 5min,避免反复 login 卡）

### `kan/cli.py`
- 注册 `@app.command("doctor")`，body 调 `kan.doctor.run()` 渲染
- help_cmd 中文速记加一行 `kan doctor`

---

## C. 核心数据结构

### `circuit.json` schema（多源 + 软过期，过期后自动 retry 一次）

```json
{
  "version": 1,
  "sources": {
    "baostock":  {"state": "ok",   "ts": 1715300100, "ttl": 86400},
    "sina":      {"state": "ok",   "ts": 1715300050, "ttl": 86400},
    "eastmoney": {"state": "down", "ts": 1715300000, "ttl": 300, "reason": "RemoteDisconnected"},
    "tencent":   {"state": "unknown"}
  }
}
```

- 状态 enum：`"ok" | "down" | "unknown"`
- `now - ts > ttl` → 视为 unknown，允许探测
- TTL 默认：
  - **down = 300s**（5min）：代理修复后用户 5min 内自动恢复
  - **ok = 86400s**（1d）：避免每次都信但不长期信
- 可被环境变量 `KAN_CIRCUIT_DOWN_TTL` 覆盖（power user）

### `kan doctor` Rich Table 三段

```
┌─ 环境 ─────────────────────────────────────┐
│ Python    3.11.15                          │
│ kan       0.0.1                            │
│ akshare   1.18.60                          │
│ baostock  0.9.10                           │
│ pandas    2.x                              │
└────────────────────────────────────────────┘

┌─ 网络 ────────────────────────────────────────────────────────┐
│ 源          | 探测 | 熔断状态 | TTL 剩余                      │
│ baostock    | ✅   | ok       | 23h 57min                    │
│ sina        | ✅   | ok       | 23h 56min                    │
│ eastmoney   | ❌   | down     | 4min 32s · RemoteDisconnected │
│ tencent     | ✅   | unknown  | -                            │
│ 系统代理    | ⚠️   | HTTP off / SOCKS off                    │
└──────────────────────────────────────────────────────────────┘

┌─ 数据 ──────────────────────────────────┐
│ cache 目录   ~/.local/share/kan/data/    │
│ 文件数       172                         │
│ 总大小       4.2 MB                      │
│ watchlist    172 只                      │
└─────────────────────────────────────────┘
```

---

## D. 测试范围

### `test_circuit.py`（≥6 条）
- 空文件读 → unknown
- 写后读回
- TTL 过期回退 unknown
- 并发 50 线程写不损坏（用 ThreadPoolExecutor）
- 损坏 JSON 自动重建
- `tmp_path` monkeypatch `CIRCUIT_PATH` 隔离

### `test_doctor.py`（≥5 条）
- mock `urllib.request.urlopen` 模拟 ok/timeout/refused
- mock `subprocess.run` 模拟 `scutil --proxy`
- env var `HTTPS_PROXY` 检测
- circuit.json 缺失/存在两态
- CliRunner smoke `kan doctor` 返回 0

### `test_fetcher.py` 已有 3 条 `_eastmoney_ok` 测试需改写为 `circuit.get()` mock（保持原意图）

---

## E. 已知坑

1. **并发写**：`fetch_batch` 5 线程都可能首次触发 `set_down("eastmoney")`。解法：模块级 `threading.Lock` + 原子替换 + write-coalescing（同状态写不重复落盘，比较 state+ts 桶化到秒）
2. **CI 网络 mock**：`probe_sources()` 必须把 `urlopen` 注入而非硬编码 import，方便 `monkeypatch.setattr(doctor, "_probe", fake)`；CI 不联外网
3. **macOS only**：`scutil` 仅 Darwin。`check_proxy()` 用 `sys.platform == "darwin"` 分支；Linux/WSL 走 `HTTP_PROXY`/`HTTPS_PROXY` env；Windows 暂返回 "未实现"
4. **降级路径**：`circuit` 持久化路径不可写时（只读 FS / 容器），降级到内存模式而非崩溃（`try: write; except OSError: warn once`）
5. **doctor 不能触发 fetch**：探测用裸 HTTP HEAD，不调 `fetch_kline`，避免 doctor 本身污染 circuit / cache

---

## F. 已确认的 3 个开放问题

| 问题 | 决定 |
|---|---|
| down TTL 默认多久？ | **5min** |
| `kan doctor` 是否带 `--fix` 子选项？ | 待实现时讨论 |
| verbose 默认行为？ | **不引入 verbose**（kan doctor 承包诊断） |

---

## 实施顺序（下一批 patch）

1. `kan/paths.py` 加 `CIRCUIT_PATH`
2. `kan/circuit.py` 新建 + 测试
3. `kan/fetcher.py` 接入 circuit
4. `kan/doctor.py` 新建 + 测试
5. `kan/cli.py` 注册 doctor 命令 + help 速记
6. parquet 加 `_source` 列(同 patch 解决 TD-1)
7. CHANGELOG + roadmap 更新

预估工时：3-4h（含测试 + 实测）

---

*最后更新：2026-05-10*
