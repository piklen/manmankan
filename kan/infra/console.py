"""终端输出小适配器。"""


def print_err(msg: str) -> None:
    """错误信号写到 stderr · 与正常表格/数据输出区分。"""
    from rich.console import Console

    Console(stderr=True).print(msg)
