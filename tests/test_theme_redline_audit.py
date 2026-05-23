"""AGENTS.md §6 红线词 audit · grep F11 相关源码 · 防回归。"""
from pathlib import Path

# F11 新增的主体代码文件 · 红线词审查 scope
F11_SOURCE_FILES = [
    "kan/_scan_targets.py",
    "kan/_confirm.py",
    "kan/cli_theme_cmds.py",
    "kan/render_theme.py",
]

# 硬红线词 · 不允许出现在 F11 任何主体代码中(spec §12.2)
REDLINE_WORDS = [
    "共振信号",
    "强势题材",
    "高位机会",
    "题材轮动",
    "热点切换",
    "可能回升",
    "可能回落",
]


def test_no_redline_words_in_f11_source():
    """硬红线词不应出现在 F11 主体代码中。"""
    repo = Path(__file__).parent.parent
    violations = []
    for relpath in F11_SOURCE_FILES:
        p = repo / relpath
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8")
        for word in REDLINE_WORDS:
            if word in content:
                violations.append(f"{relpath}: 含红线词「{word}」")
    assert not violations, "\n".join(violations)


def test_theme_disclaimer_4_lines_present():
    """render_theme.py 必须含 spec §12.1 LOCKED 的 4 行 disclaimer 关键短语。"""
    p = Path(__file__).parent.parent / "kan/render_theme.py"
    content = p.read_text(encoding="utf-8")
    assert "位置 ≠ 买卖信号" in content
    assert "题材分类各家口径不同" in content
    assert "题材跟风风险高于行业" in content
    assert "不预测涨跌" in content
    assert "不荐股" in content


def test_theme_cmds_have_education_disclaimer():
    """cli_theme_cmds.py 必须含散户教育 disclaimer(spec §12.3)。"""
    p = Path(__file__).parent.parent / "kan/cli_theme_cmds.py"
    content = p.read_text(encoding="utf-8")
    assert "题材是标签" in content or "一只股可能在多个题材" in content
    assert "投机炒作" in content or "CSRC" in content
