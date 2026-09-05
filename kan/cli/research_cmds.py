"""研究证据包的终端与 JSON 入口。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer
from pydantic import ValidationError

from kan.app import app
from kan.domain.research import ResearchRequest
from kan.storage import export


class ResearchFormat(StrEnum):
    TERMINAL = "terminal"
    JSON = "json"


@app.command()
def research(
    codes: Annotated[list[str], typer.Argument(help="1–20 个明确股票代码，可空格分隔")],
    dimensions: Annotated[str, typer.Option(
        "--dimensions", help="逗号分隔：market（必含）、valuation、fundamentals、moneyflow、technical、sentiment、chip、shareholder",
    )] = "market,valuation,fundamentals",
    fmt: Annotated[ResearchFormat, typer.Option("--format", help="terminal / json")] = ResearchFormat.TERMINAL,
) -> None:
    """按需整理有来源、日期、单位和缺口的研究事实，供终端与 AI 共同使用。"""
    from kan.service.research_service import build_research_bundle

    try:
        request = ResearchRequest.model_validate({
            "codes": codes, "dimensions": [part.strip() for part in dimensions.split(",")],
        })
    except ValidationError:
        message = "请提供1–20个股票代码及有效维度，dimensions 必须包含 market；参见 kan research --help"
        if fmt is ResearchFormat.JSON:
            typer.echo(export.to_json(export.error_payload("research", code="invalid_params", message=message)))
        else:
            typer.echo(message, err=True)
        raise typer.Exit(2) from None
    bundle = build_research_bundle(request)
    if fmt is ResearchFormat.JSON:
        typer.echo(bundle.model_dump_json())
    else:
        from kan.render.research import print_research_bundle

        print_research_bundle(bundle)
    if not bundle.ok:
        raise typer.Exit(1)
