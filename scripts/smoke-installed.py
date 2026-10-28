#!/usr/bin/env python3
"""用干净环境的解释器核对已安装制品；不依赖启动页固定文案。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import kan

package = Path(kan.__file__).resolve().parent
assert package.is_relative_to(Path(sys.prefix).resolve()), "package must come from the clean environment"
assert version("manmankan") == kan.__version__
assert (package / "tui" / "workbench.tcss").is_file()
spa = package / "web" / "spa"
assert (spa / "index.html").is_file()
assert any((spa / "assets").glob("*.js"))

command = Path(sys.executable).parent / ("kan.exe" if os.name == "nt" else "kan")
with tempfile.TemporaryDirectory(prefix="kan-installed-smoke-") as state:
    env = {
        **os.environ,
        "XDG_DATA_HOME": state,
        "KAN_NO_UPDATE_CHECK": "1",
        "KAN_NO_NAMES_BACKGROUND_REFRESH": "1",
        "NO_COLOR": "1",
    }
    for args in ([], ["--version"], ["web", "--help"], ["tui", "--help"], ["mcp", "--help"]):
        result = subprocess.run(
            [str(command), *args], cwd=state, env=env,
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
        assert result.stdout.strip(), f"empty output for {args}"
    planned = subprocess.run(
        [str(command), "find", "--codes", "600519,000858", "--format", "json", "--dry-run"],
        cwd=state, env=env, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    payload = json.loads(planned.stdout)
    assert payload["mode"] == "query_plan"
    assert payload["data_plan"]["pool_size_estimate"] == 2
print(f"Installed package {kan.__version__}: entries, assets, and JSON contract passed.")
