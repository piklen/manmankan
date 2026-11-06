"""保存观察与显式复看的本地 HTTP 入口。"""

from fastapi import APIRouter, HTTPException

from kan.domain.observation import (
    ObservationEditRequest,
    ObservationRecord,
    ObservationReviewRequest,
    ObservationReviewResult,
    ObservationSaveRequest,
    ObservationSummary,
)
from kan.service import observation
from kan.web.api_models import DeleteResponse

router = APIRouter(prefix="/api/v1/observations", tags=["observations"])


def _error(exc: ValueError) -> HTTPException:
    missing = isinstance(exc, observation.ObservationNotFoundError)
    return HTTPException(status_code=404 if missing else 422, detail={
        "code": "observation_not_found" if missing else "invalid_observation", "message": str(exc),
    })


@router.get("", response_model=list[ObservationSummary])
def observations() -> list[ObservationSummary]:
    return observation.list_observations()


@router.post("", response_model=ObservationRecord, status_code=201)
def save_observation(request: ObservationSaveRequest) -> ObservationRecord:
    try:
        return observation.save_observation(request)
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/{observation_id}", response_model=ObservationRecord)
def get_observation(observation_id: str) -> ObservationRecord:
    try:
        return observation.get_observation(observation_id)
    except observation.ObservationNotFoundError as exc:
        raise _error(exc) from exc


@router.patch("/{observation_id}", response_model=ObservationRecord)
def edit_observation(observation_id: str, request: ObservationEditRequest) -> ObservationRecord:
    try:
        return observation.edit_observation(observation_id, request)
    except observation.ObservationNotFoundError as exc:
        raise _error(exc) from exc


@router.delete("/{observation_id}", response_model=DeleteResponse)
def delete_observation(observation_id: str) -> DeleteResponse:
    return DeleteResponse(deleted=observation.delete_observation(observation_id))


@router.post("/{observation_id}/review", response_model=ObservationReviewResult)
def review_observation(observation_id: str, request: ObservationReviewRequest) -> ObservationReviewResult:
    try:
        return observation.review_observation(observation_id, request.as_of)
    except ValueError as exc:
        raise _error(exc) from exc
