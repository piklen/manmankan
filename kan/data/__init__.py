"""kan.data · 数据获取层 (各数据源 + 抓取调度 + 自更新)。

- fetcher: K 线抓取主路径 (akshare / baostock / tushare 三源 fallback)
- sources: data source 工厂 / 探测 / 优先级
- tushare: TuShare Pro 数据源 (可选 · 需 token)
- boards: 行业 / 概念板块成分股
- hot: 东方财富热榜
- updater: 自动升级检查
"""

# AkShare 导入期间会执行 ``from py_mini_racer import MiniRacer``。mini-racer
# 0.14+ 在 macOS 上是缺少 __init__.py 的命名空间包，因此库调用（不经过 kan
# console entry）也必须先补兼容属性；补丁只加载本地模块，不发起网络请求。
from kan.infra.finalizer_guard import patch_mini_racer_import

patch_mini_racer_import()
