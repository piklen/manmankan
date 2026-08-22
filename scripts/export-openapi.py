#!/usr/bin/env python3
"""导出 Web API v1 OpenAPI，供 TypeScript 客户端生成稳定类型。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kan.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            create_app(
                session_token="openapi-build",
                recover_jobs=False,
            ).openapi(),
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
