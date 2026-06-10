"""架构边界回归测试。"""
from __future__ import annotations

import ast
from pathlib import Path


def test_lower_layers_do_not_import_cli_helpers() -> None:
    """core/render/service 不应反向依赖 CLI helper。"""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for package in ("core", "render", "service"):
        for path in (root / "kan" / package).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "kan.cli.helpers":
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "kan.cli.helpers":
                            offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == []


def test_storage_export_stays_split() -> None:
    """export 公共入口应保持薄门面，命令族实现继续分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    facade = root / "kan" / "storage" / "export.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == []

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "storage").glob("export_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_find_cli_entrypoint_stays_thin() -> None:
    """find CLI 入口只保留 Typer 参数声明，执行细节拆到同层 helper。"""
    root = Path(__file__).resolve().parents[1]
    entrypoint = root / "kan" / "cli" / "find_cmds.py"
    tree = ast.parse(entrypoint.read_text(encoding="utf-8"), filename=str(entrypoint))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == ["find"]

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "cli").glob("find_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_watchlist_cli_entrypoint_stays_thin() -> None:
    """watchlist CLI 入口只保留 Typer 参数声明，执行细节拆到同层 helper。"""
    root = Path(__file__).resolve().parents[1]
    entrypoint = root / "kan" / "cli" / "watchlist_cmds.py"
    tree = ast.parse(entrypoint.read_text(encoding="utf-8"), filename=str(entrypoint))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == ["add", "remove", "list_stocks", "import_csv", "clear_watchlist"]

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "cli").glob("watchlist_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_watchlist_storage_stays_split() -> None:
    """watchlist storage 公共入口保持薄门面，模型/IO/名称/分组/股票操作分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    facade = root / "kan" / "storage" / "watchlist.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == []

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "storage").glob("watchlist_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_terminal_render_stays_split() -> None:
    """terminal render 公共入口保持薄门面，各命令族表格构建分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    facade = root / "kan" / "render" / "terminal.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == []

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "render").glob("terminal_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_stock_set_stays_split() -> None:
    """StockSet 公共入口保持薄门面，协议/本地集合/外部来源/factory 分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    facade = root / "kan" / "core" / "stock_set.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == []

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "core").glob("stock_set_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_enrich_stays_split() -> None:
    """enrich 公共入口保持薄门面，row/index/results/scan/RS 逻辑分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    facade = root / "kan" / "core" / "enrich.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef)
    ]
    assert definitions == []

    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in (root / "kan" / "core").glob("enrich_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_scanner_auxiliary_modules_stay_split() -> None:
    """scanner 主筛选语义留在入口，快照/历史/趋势/量能辅助职责保持分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "kan" / "core" / "scanner.py",
        *(root / "kan" / "core").glob("scanner_*.py"),
    ]
    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in paths
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_find_service_support_modules_stay_split() -> None:
    """find service 入口保留用例编排，模型/排序/元数据/data-gap 支撑逻辑分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "kan" / "service" / "find_service.py",
        *(root / "kan" / "service").glob("find_service_*.py"),
    ]
    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in paths
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []


def test_find_filter_matchers_stay_split() -> None:
    """find filter 入口保留 apply 编排，matcher 分组模块继续分文件维护。"""
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "kan" / "core" / "find_filter.py",
        *(root / "kan" / "core").glob("find_filter_*.py"),
    ]
    oversized = [
        f"{path.relative_to(root)}:{len(path.read_text(encoding='utf-8').splitlines())}"
        for path in paths
        if len(path.read_text(encoding="utf-8").splitlines()) > 500
    ]
    assert oversized == []
