"""市场观察的薄 HTTP 入口。"""

from fastapi import APIRouter, HTTPException

from kan.domain.discovery import DiscoveryQuery, DiscoveryResult
from kan.service.discovery import discover_market

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


@router.post("", response_model=DiscoveryResult)
def discovery(query: DiscoveryQuery) -> DiscoveryResult:
    try:
        return discover_market(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": str(exc)}) from exc


@router.get("", response_model=DiscoveryResult)
def current_discovery() -> DiscoveryResult:
    return discovery(DiscoveryQuery())
