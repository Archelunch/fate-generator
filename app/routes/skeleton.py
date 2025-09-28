from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Request

from app.core.constants import DEFAULT_FATE_CORE_SKILLS
from app.core.skeleton import build_sample_character_skeleton
from app.models import CharacterSheet, CharacterSkeleton, GenerateSkeletonRequest, RankedSkill

router = APIRouter(prefix="/api")


@router.post("/generate_skeleton", response_model=CharacterSkeleton | CharacterSheet)
@router.post("/generate_sample_skeleton", response_model=CharacterSheet)
def generate_skeleton(http_request: Request, request: GenerateSkeletonRequest | None = None) -> CharacterSheet | CharacterSkeleton:
    if request is None:
        return build_sample_character_skeleton()

    services = http_request.app.state.services
    mod = services.skeleton

    skills = request.skillList or DEFAULT_FATE_CORE_SKILLS
    prediction = mod(idea=request.idea, setting=request.setting or "", skill_list=skills)
    predicted: list[str] = list(getattr(prediction, "ranked_skills", []) or [])

    allowed_lower = {s.lower(): s for s in skills}
    seen: set[str] = set()
    sanitized: list[str] = []
    for name in predicted:
        key = (name or "").strip().lower()
        if key in allowed_lower and key not in seen:
            sanitized.append(allowed_lower[key])
            seen.add(key)
    if not sanitized:
        sanitized = list(skills)

    ranked: list[RankedSkill] = []
    total = len(sanitized)
    for idx, skill_name in enumerate(sanitized):
        rank_value = total - idx
        stable_id = f"skill-{hashlib.sha1(skill_name.lower().encode()).hexdigest()[:8]}"
        ranked.append(RankedSkill(id=stable_id, name=skill_name, rank=rank_value))

    high_concept = getattr(prediction, "high_concept", None) or request.idea
    trouble = getattr(prediction, "trouble", None) or (request.setting or "Unknown trouble")

    return CharacterSkeleton(highConcept=high_concept, trouble=trouble, skills=ranked)


