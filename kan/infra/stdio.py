"""管道的默认编码与 Windows 控制台代码页可能不同。"""
from io import TextIOWrapper


def utf8_pipes(*streams) -> None:
    for stream in streams:
        if isinstance(stream, TextIOWrapper) and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors=stream.errors)
