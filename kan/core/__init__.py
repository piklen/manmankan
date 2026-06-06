"""kan.core · 核心抽象 / 模型 / 算法层。

- stock_set: StockSet 抽象 (自选 / 热榜 / 题材 / 行业 …) — 一切可被 verb 操作的对象
- verbs: trend / scan / low / high 统一入口 · 接受任何 StockSet
- pipeline: 多周期 / 多源数据编排
- scanner: 位置扫描 + 5 档量能识别
- models: dataclass / pydantic 数据模型
- calendar: 交易日历
"""
