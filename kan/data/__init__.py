"""kan.data · 数据获取层 (各数据源 + 抓取调度 + 自更新)。

- fetcher: K 线抓取主路径 (akshare / baostock / tushare 三源 fallback)
- sources: data source 工厂 / 探测 / 优先级
- tushare: TuShare Pro 数据源 (可选 · 需 token)
- boards: 行业 / 概念板块成分股
- hot: 东方财富热榜
- updater: 自动升级检查
"""
