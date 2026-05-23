"""AGENTS.md §6 红线词 audit · 题材功能源码防回归。"""
from pathlib import Path

# 题材功能新增的主体代码文件 · 红线词审查 scope
THEME_SOURCE_FILES = [
    "kan/_scan_targets.py",
    "kan/_confirm.py",
    "kan/cli_theme_cmds.py",
    "kan/render_theme.py",
]

# 硬红线词 · 不允许出现在题材功能任何主体代码中
REDLINE_WORDS = [
    "共振信号",
    "强势题材",
    "高位机会",
    "题材轮动",
    "热点切换",
    "可能回升",
    "可能回落",
]


def test_no_redline_words_in_theme_source():
    """硬红线词不应出现在题材功能主体代码中。"""
    repo = Path(__file__).parent.parent
    violations = []
    for relpath in THEME_SOURCE_FILES:
        p = repo / relpath
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8")
        for word in REDLINE_WORDS:
            if word in content:
                violations.append(f"{relpath}: 含红线词「{word}」")
    assert not violations, "\n".join(violations)


def test_theme_disclaimer_4_lines_present():
    """render_theme.py 必须含 4 行 disclaimer 关键短语。"""
    p = Path(__file__).parent.parent / "kan/render_theme.py"
    content = p.read_text(encoding="utf-8")
    assert "位置 ≠ 买卖信号" in content
    assert "题材分类各家口径不同" in content
    assert "题材跟风风险高于行业" in content
    assert "不预测涨跌" in content
    assert "不荐股" in content


def test_theme_cmds_have_education_disclaimer():
    """cli_theme_cmds.py 必须含散户教育 disclaimer(***REMOVED*** 后 disclaimer 改 SOT · const import)。"""
    p = Path(__file__).parent.parent / "kan/cli_theme_cmds.py"
    content = p.read_text(encoding="utf-8")
    # ***REMOVED*** 后:THEME_VS_INDUSTRY / THEME_CLASSIFICATION / THEME_RISK 三个 const 任一引用
    assert "THEME_VS_INDUSTRY" in content or "THEME_CLASSIFICATION" in content
    assert "THEME_RISK" in content
    # 真跑 theme list 必须输出"用工具看位置不等于买卖建议"散户教育语
    assert "用工具看位置不等于买卖建议" in content
