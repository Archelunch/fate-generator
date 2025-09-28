from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.models import CharacterStateInput, GMHintsRequest, GMHintsResponse
from app.core.gm_hints_utils import normalize_gm_hints

router = APIRouter(prefix="/api")


def _normalize_gm_hints(
    state: CharacterStateInput,
    *,
    target_type: str,
    target_id: str,
    raw_prediction: Any,
) -> GMHintsResponse:
    return normalize_gm_hints(state, target_type=target_type, target_id=target_id, raw_prediction=raw_prediction)


@router.post("/hints", response_model=GMHintsResponse)
def gm_hints(request: GMHintsRequest, http_request: Request) -> GMHintsResponse:
    state = CharacterStateInput.model_validate(request.character)
    target_type = request.target.type
    target_id = request.target.id
    _ = request.options.num if request.options else None
    tone = request.options.tone if request.options else None

    services = http_request.app.state.services
    raw_pred = services.gm_hints(state=state, target_type=target_type, target_id=target_id, tone=tone)
    hints = _normalize_gm_hints(state, target_type=target_type, target_id=target_id, raw_prediction=raw_pred)
    return hints


