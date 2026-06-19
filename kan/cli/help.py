"""kan help 命令 · 命令速记 cheat-sheet 注册模块。"""
from kan.app import app
from kan.help_text import print_root_help


@app.command(name="help")
def help_cmd() -> None:
    """查看命令帮助"""
    print_root_help()
