"""kan/terminal.py · rich table builder 单测。

测试断言 _columns 名 + _rows 内容 · 不依赖具体颜色 markup(那由 format_pct 单测保证)。

覆盖矩阵:
  scan_table:   normal / hot rank / board_index_row
  extreme_table: low / high / hot rank
  info_table:   single-stock (insufficient → Text dim) / industry (insufficient → "-")
  compare_table: basic / ST + 涨停 mark
  trend_table:  normal / latest 日期列 / hot rank
  scan_title:   self+cutoff/industry/hot/theme/signal_only
  trend_title:  self+cutoff / industry+candle
"""
import io
from datetime import date

import pandas as pd
from rich.console import Console
from rich.text import Text

from kan.core.models import (
    Board,
    BoardMeta,
    HotMeta,
    PeriodResult,
    StockScanResult,
    Theme,
    ThemeMeta,
)
from kan.core.pipeline import DataCtx, Freshness
from kan.core.scanner import TrendResult
from kan.render import terminal

# ── fixtures ──────────────────────────────────────────────────────────


def _period(period=30, *, insufficient=False, at_low=False, at_high=False, pct=50.0):
    return PeriodResult(
        period=period,
        n_low=10.0,
        n_high=20.0,
        position_pct=pct,
        at_low=at_low,
        at_high=at_high,
        insufficient=insufficient,
    )


def _stock(symbol="600519", name="贵州茅台", **kw):
    defaults = {
        "symbol": symbol,
        "name": name,
        "current_price": 15.0,
        "scan_date": date(2026, 5, 21),
        "periods": [_period(30), _period(60), _period(180)],
        "low_resonance": 0,
        "high_resonance": 0,
    }
    defaults.update(kw)
    return StockScanResult(**defaults)


def _stock_with_context(**kw):
    defaults = {
        "pe_ttm": 20.4,
        "moneyflow_5d_net_amount": 12345.0,
        "ma_10": 101.23,
        "ma_20": 98.76,
        "recent_low_20": 90.12,
    }
    defaults.update(kw)
    return _stock(**defaults)


def _freshness(cutoff=date(2026, 5, 21), fetched_at="2026-05-21 23:00:00"):
    return Freshness(
        data_cutoff=cutoff,
        fetched_at=fetched_at,
        expected_cutoff=date(2026, 5, 21),
        is_stale=False,
        phase="closed",
    )


def _ctx(meta=None, results=None, freshness=None):
    return DataCtx(
        targets=[],
        meta=meta,
        results=results or [],
        freshness=freshness or _freshness(),
    )


def _board_meta(name="半导体", code="801080"):
    return BoardMeta(
        board=Board(code=code, name=name, level=1, size=50),
        index_kline=pd.DataFrame(),
        constituents=[],
        highlight={"600519"},
    )


def _hot_meta():
    return HotMeta(
        list_name="东财人气榜",
        rank_map={"600519": 3, "000858": 7},
        highlight={"600519"},
    )


def _theme_meta(name="AI应用"):
    return ThemeMeta(
        theme=Theme(code="886108", name=name, source="ths"),
        index_kline=pd.DataFrame(),
        constituents=[],
        highlight={"600519"},
    )


def _trend(symbol="600519", name="贵州茅台", *, streak=2, pct=3.5, days=None):
    return TrendResult(
        symbol=symbol,
        name=name,
        current_price=15.0,
        streak=streak,
        streak_pct=pct,
        daily_changes=days or [
            ("2026-05-21", 1.2),
            ("2026-05-20", 2.3),
            ("2026-05-19", -0.5),
        ],
    )


def _hold_summary():
    from kan.core.positions import AccountView, PositionHealth, PositionsSummary, PositionView

    rows = [
        PositionView(
            symbol="600519",
            name="贵州 茅台",
            cost=1680.5,
            shares=100,
            price=1700,
            prev_close=1690.0,
            market_value=170000.0,
            cost_value=168050.0,
            weight_pct=69.96,
            daily_pnl=1000.0,
            daily_pnl_pct=0.59,
            total_pnl=1950.0,
            total_pnl_pct=1.16,
            positions={30: 20.0, 60: 50.0, 180: 80.0},
            price_source="realtime",
            price_status="ok",
        ),
        PositionView(
            symbol="000858",
            name="五粮液",
            cost=150.0,
            shares=200,
            price=None,
            prev_close=None,
            market_value=None,
            cost_value=30000.0,
            weight_pct=None,
            daily_pnl=None,
            daily_pnl_pct=None,
            total_pnl=-500.0,
            total_pnl_pct=-1.2,
            positions={30: None, 60: None, 180: None},
            price_source="close_cache",
            price_status="suspended",
        ),
        PositionView(
            symbol="000001",
            name="平安银行",
            cost=10.0,
            shares=100,
            price=10.0,
            prev_close=10.0,
            market_value=1000.0,
            cost_value=1000.0,
            weight_pct=0.41,
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            total_pnl=0.0,
            total_pnl_pct=0.0,
            positions={30: 10.0, 60: 20.0, 180: 30.0},
            price_source="realtime",
            price_status="ok",
        ),
    ]
    return PositionsSummary(
        results=rows,
        account=AccountView(
            cash=73000.0,
            total_market_value=171000.0,
            total_assets=244000.0,
            total_position_pct=70.08,
            daily_pnl=1000.0,
            total_pnl=1450.0,
        ),
        health=PositionHealth(
            high_count=1,
            low_count=1,
            middle_count=1,
            profit_count=1,
            loss_count=1,
            flat_count=1,
        ),
        price_mode="realtime",
        data_cutoff=date(2026, 6, 5),
        notes=["盈亏按裸价差计算，未计佣金/印花税。"],
    )


# ── scan_title ────────────────────────────────────────────────────────


def test_scan_title_self_low_with_cutoff():
    title = terminal.scan_title(_ctx(), high_mode=False)
    assert title.startswith("慢慢看 · 自选股位置扫描 · 低点模式")
    assert "数据截止 05-21 收盘" in title
    assert "拉取" in title


def test_scan_title_signal_only_appended():
    title = terminal.scan_title(_ctx(), high_mode=True, signal_only=True)
    assert "高点模式 · 仅信号" in title


def test_scan_title_industry_replaces_completely():
    """BoardMeta 分支 title 完全替换 · 不带 cutoff/fetched_at/仅信号 后缀。"""
    title = terminal.scan_title(
        _ctx(meta=_board_meta()), high_mode=False, signal_only=True,
    )
    assert title == "慢慢看 · 半导体 行业位置扫描 · 低点模式"
    assert "仅信号" not in title  # 板块模式无信号尾巴 · 字符级一致


def test_scan_title_hot_branch():
    title = terminal.scan_title(_ctx(meta=_hot_meta()), high_mode=False)
    assert title == "慢慢看 · 东财人气榜 位置扫描 · 低点模式"


def test_scan_title_theme_branch():
    title = terminal.scan_title(_ctx(meta=_theme_meta()), high_mode=True)
    assert title == "慢慢看 · AI应用 题材位置扫描 · 高点模式"


# ── scan_table ────────────────────────────────────────────────────────


def test_scan_table_basic_columns_and_row():
    table = terminal.scan_table(
        _ctx(),
        [_stock(low_resonance=2)],
        display_periods=[30, 60, 180],
        high_mode=False,
    )
    col_headers = [c.header for c in table.columns]
    assert col_headers == ["股票", "现价", "30日", "60日", "180日", "共振"]
    assert table.row_count == 1


def test_scan_table_context_columns():
    table = terminal.scan_table(
        _ctx(),
        [_stock_with_context()],
        display_periods=[30],
        high_mode=False,
        show_context=True,
    )
    col_headers = [c.header for c in table.columns]
    assert col_headers == [
        "股票", "现价", "PE", "5日主力(万)", "10日线", "20日线", "20日低",
        "除权除息", "30日", "共振",
    ]
    assert table.columns[2]._cells == ["20.4"]
    assert table.columns[3]._cells == ["12,345"]
    assert table.columns[4]._cells == ["101.23"]


def test_scan_table_hot_adds_rank_column_and_value():
    table = terminal.scan_table(
        _ctx(meta=_hot_meta()),
        [_stock(low_resonance=1), _stock(symbol="000858", name="五粮液")],
        display_periods=[30],
        high_mode=False,
    )
    col_headers = [c.header for c in table.columns]
    assert col_headers[0] == "榜"
    assert "股票" in col_headers
    # 第一列(榜)的两行值就是 rank_map 的 lookup
    assert table.columns[0]._cells == ["3", "7"]


def test_scan_table_with_board_index_row():
    """board_index_result 不为 None 时作为顶部行 + add_section · row_count +1。"""
    board_idx = _stock(symbol="801080", name="半导体", periods=[_period(30, pct=45)])
    table = terminal.scan_table(
        _ctx(meta=_board_meta()),
        [_stock()],
        display_periods=[30],
        high_mode=False,
        board_index_result=board_idx,
    )
    assert table.row_count == 2
    # 板块指数行在第一行 · 名称单元格含 🏛️
    assert "🏛️" in table.columns[0]._cells[0]


# ── extreme_table ─────────────────────────────────────────────────────


def test_extreme_table_low_columns():
    stock = _stock()
    hits = [(stock, _period(30, at_low=True, pct=2.5))]
    table = terminal.extreme_table(
        30, hits, "low",
        data_cutoff=date(2026, 5, 21), fetched_at="2026-05-21 23:00:00",
    )
    assert "低点 · 1 只触及" in table.title
    headers = [c.header for c in table.columns]
    assert headers == ["股票", "现价", "30日最低", "30日最高", "位置"]
    assert table.row_count == 1


def test_extreme_table_high_title_label():
    table = terminal.extreme_table(60, [], "high")
    assert "高点 · 0 只触及" in table.title
    # 无累积 cutoff/fetched_at 时无后缀
    assert "数据截止" not in table.title


def test_extreme_table_hot_adds_rank_column():
    stock = _stock()
    hits = [(stock, _period(30, at_low=True, pct=1.5))]
    table = terminal.extreme_table(
        30, hits, "low",
        is_hot=True, rank_map={"600519": 3}, highlight={"600519"},
    )
    headers = [c.header for c in table.columns]
    assert headers[0] == "榜"
    assert table.columns[0]._cells == ["3"]
    # 股票列含 ⭐
    assert "⭐" in table.columns[1]._cells[0]


def test_extreme_table_with_industry_reference():
    """BoardMeta + board_index_result 注入 reference 行 · 首行 🏛️ X 板块指数。"""
    stock = _stock()
    hits = [(stock, _period(30, at_low=True, pct=2.5))]
    board_idx = _stock(
        symbol="801080", name="半导体",
        periods=[_period(30, pct=42.0)],
    )
    table = terminal.extreme_table(
        30, hits, "low",
        board_index_result=board_idx, board_meta=_board_meta("半导体"),
    )
    assert table.row_count == 2  # reference + 1 hit
    # 首行(reference)股票列 = 🏛️ + 板块指数
    name_cell = table.columns[0]._cells[0]
    assert "🏛️" in name_cell
    assert "半导体" in name_cell
    assert "板块指数" in name_cell
    # reference 行的位置 cell 用普通字符串不带方括号 · 跟 hits 的 [pct%] 区分
    pos_col = table.columns[-1]
    assert pos_col._cells[0] == "42.0%"  # reference 行


def test_extreme_table_with_theme_reference_uses_kite_emoji():
    """ThemeMeta + board_index_result → 首行 🎯 X 题材指数。"""
    board_idx = _stock(
        symbol="886108", name="AI应用",
        periods=[_period(60, pct=78.5)],
    )
    table = terminal.extreme_table(
        60, [], "high",
        board_index_result=board_idx, board_meta=_theme_meta("AI应用"),
    )
    assert table.row_count == 1
    name_cell = table.columns[0]._cells[0]
    assert "🎯" in name_cell
    assert "AI应用" in name_cell
    assert "题材指数" in name_cell
    # 高点模式下 reference 行的位置 cell 也不带方括号
    assert table.columns[-1]._cells[0] == "78.5%"


def test_extreme_table_reference_with_empty_hits_keeps_row():
    """hits 空 + reference → row_count=1(只剩 reference) · 验证空结果时锚点仍在。"""
    board_idx = _stock(
        symbol="801080", name="半导体",
        periods=[_period(30, pct=15.0)],
    )
    table = terminal.extreme_table(
        30, [], "low",
        board_index_result=board_idx, board_meta=_board_meta("半导体"),
    )
    assert table.row_count == 1
    assert "🏛️" in table.columns[0]._cells[0]


def test_extreme_table_no_reference_backward_compat():
    """不传 reference 参数时表格行数 = hits 数(原行为保护)。"""
    stock = _stock()
    hits = [(stock, _period(30, at_low=True, pct=2.5))]
    table = terminal.extreme_table(30, hits, "low")
    assert table.row_count == 1  # 只有 hit · 没 reference 行


def test_scan_table_with_theme_meta_uses_kite_emoji():
    """背景: scan_table 题材路径首行从 🏛️ 改为 🎯 题材指数(跟 info --theme 对齐)。"""
    board_idx = _stock(
        symbol="886108", name="AI应用",
        periods=[_period(30, pct=55)],
    )
    table = terminal.scan_table(
        _ctx(meta=_theme_meta("AI应用")),
        [_stock()],
        display_periods=[30],
        high_mode=False,
        board_index_result=board_idx,
    )
    assert table.row_count == 2
    name_cell = table.columns[0]._cells[0]
    assert "🎯" in name_cell
    assert "题材指数" in name_cell
    assert "🏛️" not in name_cell  # theme 路径不再用 🏛️


def test_board_reference_label_helper_dispatches_by_meta_type():
    """_board_reference_label helper 单测 · 直接验 industry/theme 派发。"""
    label_industry = terminal._board_reference_label("半导体", _board_meta())
    label_theme = terminal._board_reference_label("AI应用", _theme_meta())
    label_hot = terminal._board_reference_label("东财人气榜", _hot_meta())
    label_none = terminal._board_reference_label("自选股", None)

    assert label_industry == "🏛️ 半导体 板块指数"
    assert label_theme == "🎯 AI应用 题材指数"
    # hot / None 用 industry 默认 · 实际 caller 不会把 hot 当 reference 喂进来
    assert label_hot == "🏛️ 东财人气榜 板块指数"
    assert label_none == "🏛️ 自选股 板块指数"


# ── hold_table ────────────────────────────────────────────────────────


def test_hold_table_formats_position_rows():
    table = terminal.hold_table(_hold_summary())

    assert table.title == "慢慢看 · 持仓总览 · 数据截止 06-05 · 现价口径 realtime"
    assert [c.header for c in table.columns] == [
        "股票", "现价", "成本", "今日盈亏%", "累计盈亏%", "累计盈亏额",
        "市值", "仓位%", "30日", "60日", "180日",
    ]
    assert table.row_count == 3
    assert table.columns[0]._cells[0] == "💰 贵州茅台 600519"
    assert table.columns[1]._cells[0] == "1700"
    assert table.columns[2]._cells[0] == "1,680.5000"
    assert table.columns[3]._cells[0].plain == "+0.59%"
    assert table.columns[3]._cells[0].style == "red"
    assert table.columns[4]._cells[1].plain == "-1.20%"
    assert table.columns[4]._cells[1].style == "green"
    assert table.columns[5]._cells[2].plain == "+0.00"
    assert str(table.columns[0]._cells[1]).endswith(" 停牌")
    assert table.columns[1]._cells[1] == "-"
    assert table.columns[7]._cells[1] == "-"


def test_hold_table_mask_hides_sensitive_values():
    table = terminal.hold_table(_hold_summary(), mask=True)

    assert table.columns[2]._cells[0] == "***"
    assert table.columns[3]._cells[0].plain == "***"
    assert table.columns[5]._cells[0].plain == "***"
    assert table.columns[6]._cells[0] == "***"
    assert table.columns[7]._cells[0] == "***"
    # 位置百分位不是金额或持仓敏感字段，不随 mask 隐藏。
    assert table.columns[8]._cells[0] == "20.0"


def test_render_hold_footer_prints_account_health_notes_and_disclaimer():
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    terminal.render_hold_footer(_hold_summary(), console)

    output = buffer.getvalue()
    assert "账户" in output
    assert "总市值 171,000.00" in output
    assert "高位 1 只 · 低位 1 只" in output
    assert "盈亏按裸价差计算" in output
    assert "不构成买卖建议" in output


def test_render_hold_footer_respects_mask():
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, color_system=None, width=120)

    terminal.render_hold_footer(_hold_summary(), console, mask=True)

    output = buffer.getvalue()
    assert "总市值 ***" in output
    assert "现金 ***" in output
    assert "今日总盈亏 ***" in output


# ── info_table ────────────────────────────────────────────────────────


def test_info_table_normal_uses_dim_text_for_insufficient():
    """单股 info · insufficient 周期 → 位置单元格用 Text("-", style="dim")。"""
    result = _stock(periods=[
        _period(180, insufficient=True),
        _period(30, pct=42.0),
    ])
    table = terminal.info_table(result, is_industry=False)
    pos_col = table.columns[3]
    # 第 1 行(insufficient) 位置单元格是 Text · 第 2 行是 Text(format_pct 返回)
    assert isinstance(pos_col._cells[0], Text)
    assert pos_col._cells[0].plain == "-"
    assert pos_col._cells[0].style == "dim"


def test_info_table_industry_uses_plain_dash_for_insufficient():
    """行业 / 题材档案 · insufficient → 位置单元格用普通字符串 "-"(字符级保留)。"""
    result = _stock(periods=[
        _period(180, insufficient=True),
        _period(30, pct=42.0),
    ])
    table = terminal.info_table(
        result, is_industry=True, board_meta=_board_meta(),
    )
    pos_col = table.columns[3]
    assert pos_col._cells[0] == "-"  # 字符串 · 不是 Text
    assert not isinstance(pos_col._cells[0], Text)


def test_board_position_table_shape():
    """单股 info 板块对照 · 排名列标明低到高口径。"""
    from kan.core.models import BoardPositionContext, BoardPositionPeriod

    table = terminal.board_position_table(BoardPositionContext(
        industry="食品饮料",
        board_code="801016",
        board_level=1,
        constituent_count=3,
        cached_sample=3,
        periods=[
            BoardPositionPeriod(
                period=30,
                position_pct=12.5,
                board_avg_pct=45.0,
                rank_low_to_high=1,
                sample=3,
            )
        ],
    ))
    assert [c.header for c in table.columns] == ["周期", "本股位置", "板块均值", "低到高排名"]
    assert table.columns[3]._cells[0] == "1/3"


# ── compare_table ─────────────────────────────────────────────────────


def test_compare_table_basic_shape():
    s1 = _stock()
    s2 = _stock(symbol="000858", name="五粮液", low_resonance=1, high_resonance=2)
    table = terminal.compare_table([s1, s2], periods=[30])
    headers = [c.header for c in table.columns]
    # 指标列 + 两支股票列
    assert headers[0] == "指标"
    assert "贵州茅台 600519" in headers[1]
    assert "五粮液 000858" in headers[2]
    # 行:现价 / 30日位置 / 低点共振 / 高点共振 / ST / 涨跌停 / 数据截止 = 7
    assert table.row_count == 7
    assert table.title == "慢慢看 · 多股对比"


def test_compare_table_st_and_limit_up_marked():
    st_stock = _stock(symbol="000333", name="某ST", is_st=True, limit_up=True)
    normal = _stock()
    table = terminal.compare_table([st_stock, normal], periods=[30])
    # ST 行(第 5 行 · 0-indexed 4)第一只股票值=是 · 第二只=—
    st_col_1 = table.columns[1]._cells[4]
    st_col_2 = table.columns[2]._cells[4]
    assert st_col_1 == "是"
    assert st_col_2 == "—"
    # 涨跌停行(第 6 行 · 0-indexed 5)第一只=涨停 · 第二只=—
    limit_col_1 = table.columns[1]._cells[5]
    assert limit_col_1 == "涨停"


# ── trend_title ───────────────────────────────────────────────────────


def test_trend_title_self_close_with_cutoff():
    title = terminal.trend_title(_ctx(), candle=False)
    assert title.startswith("慢慢看 · 连续涨跌看板 · 收盘价口径")
    assert "数据截止 05-21 收盘" in title


def test_trend_title_industry_candle_replaces():
    title = terminal.trend_title(
        _ctx(meta=_board_meta()), candle=True, filter_label=" · 连跌≥3天",
    )
    assert title == "慢慢看 · 半导体 行业连续涨跌 · 阳线阴线口径 · 连跌≥3天"


# ── trend_table ───────────────────────────────────────────────────────


def test_trend_table_basic_no_latest():
    table = terminal.trend_table(
        _ctx(), [_trend(streak=2, pct=3.5)],
        latest=None, candle=False,
    )
    headers = [c.header for c in table.columns]
    assert headers == ["股票", "现价", "连续", "累计"]
    assert table.row_count == 1


def test_trend_table_with_latest_adds_date_columns():
    """latest=2 时加 2 个日期列(MM-DD)。"""
    days = [
        ("2026-05-21", 1.5),
        ("2026-05-20", -0.8),
        ("2026-05-19", 2.0),
    ]
    table = terminal.trend_table(
        _ctx(), [_trend(streak=2, pct=2.5, days=days)],
        latest=2, candle=False,
    )
    headers = [c.header for c in table.columns]
    assert headers[:4] == ["股票", "现价", "连续", "累计"]
    # 后面 2 个是 MM-DD 日期列
    assert headers[4] == "05-21"
    assert headers[5] == "05-20"
    assert len(headers) == 6


def test_trend_table_hot_adds_rank_column():
    table = terminal.trend_table(
        _ctx(meta=_hot_meta()),
        [_trend(symbol="600519"), _trend(symbol="000858", name="五粮液")],
        latest=None, candle=False,
    )
    headers = [c.header for c in table.columns]
    assert headers[0] == "榜"
    assert table.columns[0]._cells == ["3", "7"]
