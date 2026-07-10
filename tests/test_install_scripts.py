"""跨平台安装脚本编码约束。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_is_utf8_with_bom() -> None:
    raw = (ROOT / "scripts" / "install.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8-sig")
