from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.core.constants import DEFAULT_FATE_CORE_SKILLS
from app.models import (
    AspectSuggestion,
    CharacterSheet,
    CharacterStateInput,
    GenerateRemainingRequest,
    GenerateRemainingResult,
    GenerationErrorResponse,
    SkillSuggestion,
    StuntSuggestion,
    UISkill,
)
from app.utils import merge_suggestions_into_sheet

router = APIRouter(prefix="/api")


def _to_remaining_result(prediction: Any) -> GenerateRemainingResult:
    data: dict[str, Any] = {
        "aspects": [getattr(prediction, "aspects", None)] if getattr(prediction, "aspects", None) is not None else None,
        "stunts": [getattr(prediction, "stunts", None)] if getattr(prediction, "stunts", None) is not None else None,
        "notes": getattr(prediction, "notes", None),
    }
    if getattr(prediction, "skills", None) is not None:
        data["skills"] = [getattr(prediction, "skills", None)]
    return GenerateRemainingResult.model_validate(data)


@router.post("/generate_remaining", response_model=CharacterSheet, responses={422: {"model": GenerationErrorResponse}})
def generate_remaining(request: GenerateRemainingRequest, http_request: Request) -> CharacterSheet | Response:
    from pydantic import ValidationError  # local import to avoid cycles

    services = http_request.app.state.services
    _remaining_mod = services.remaining

    feedback: str | None = None
    last_validation_err: ValidationError | None = None

    input_state = CharacterStateInput.model_validate(request.character)

    additional_aspects = [a for a in input_state.aspects if a.name not in ("High Concept", "Trouble")]
    aspect_slots_left = max(0, 3 - len(additional_aspects))

    target_skill_name: str | None = None
    if request.options and request.options.targetSkillId:
        skill_map = {s.id: s.name for s in input_state.skills}
        target_skill_name = skill_map.get(request.options.targetSkillId)

    mode = request.options.mode if request.options and request.options.mode else "stunts"
    num_stunts = None
    if request.options and request.options.count is not None:
        num_stunts = max(1, int(request.options.count))

    gen_state = input_state
    if mode == "skills":
        protected_ids: set[str] = set()
        protected_skills: list[UISkill] = []
        try:
            for s in input_state.skills:
                is_locked = bool(getattr(s, "locked", False))
                is_user_edited = bool(getattr(s, "userEdited", False))
                is_protected = is_locked or (not request.allowOverwriteUserEdits and is_user_edited)
                if is_protected:
                    protected_ids.add(s.id)
                    protected_skills.append(s)
        except Exception:
            protected_skills = []
        gen_state = CharacterStateInput(
            meta=input_state.meta,
            aspects=input_state.aspects,
            skills=protected_skills,
            stunts=input_state.stunts,
        )

    try:
        _pred = _remaining_mod(
            state=gen_state,
            allow_overwrite=request.allowOverwriteUserEdits,
            default_skills=(
                request.options.skillBank if (request.options and request.options.skillBank) else DEFAULT_FATE_CORE_SKILLS
            ),
            feedback=feedback,
            mode=mode,
            target_skill_name=target_skill_name,
            action_type=(request.options.actionType if request.options else None),
            aspect_slots_left=aspect_slots_left,
            user_note=(request.options.note if request.options else None),
        )
        suggestions = _to_remaining_result(_pred)
        # Keep existing filtering/adjustment logic from legacy router by delegating to utils/inline code.
        # To minimize diff risk in Phase 1, reuse same logic by mapping to/from utils.
        from app.core.skills_utils import _pad_pyramid_to_minimum, _canonicalize_skill_name, _ensure_skill_ids

        if mode == "aspects":
            aspect_items = list(suggestions.aspects or [])
            requested = 1
            if request.options and request.options.count is not None:
                try:
                    requested = max(1, int(request.options.count))
                except Exception:
                    requested = 1
            if aspect_slots_left:
                requested = min(requested, aspect_slots_left)
            if len(aspect_items) > requested:
                aspect_items = aspect_items[:requested]
            if not aspect_items and aspect_slots_left > 0:
                idea = (input_state.meta.idea or "").strip() or "Character"
                base_desc = f"An aspect reflecting: {idea}"
                aspect_items = [AspectSuggestion(name="Aspect", description=base_desc) for _ in range(requested)]
            suggestions = suggestions.model_copy(update={"aspects": aspect_items, "skills": None, "stunts": None})
        elif mode in ("stunts", "single_stunt"):
            stunt_items = list(suggestions.stunts or [])
            requested_n = max(1, int(num_stunts or 1))

            def _has_content(sug: StuntSuggestion) -> bool:
                desc = (getattr(sug, "description", None) or "").strip()
                name = (getattr(sug, "name", None) or "").strip()
                return bool(desc or name)

            stunt_items = [s for s in stunt_items if _has_content(s)]

            def _norm(text: str) -> str:
                return " ".join((text or "").strip().lower().split())

            existing_norm = {
                _norm(getattr(s, "description", "")) for s in input_state.stunts if getattr(s, "description", None)
            }
            dedup: list[StuntSuggestion] = []
            seen: set[str] = set(existing_norm)
            for sug in stunt_items:
                key = _norm(getattr(sug, "description", ""))
                if not key or key in seen:
                    continue
                dedup.append(sug)
                seen.add(key)
            stunt_items = dedup
            if len(stunt_items) > requested_n:
                stunt_items = stunt_items[:requested_n]
            if not stunt_items:
                n = requested_n
                skill_name = target_skill_name or (input_state.skills[0].name if input_state.skills else "Fight")
                action = (request.options.actionType if request.options else None) or "overcome"
                action_phrase = {
                    "overcome": "overcome obstacles",
                    "create_advantage": "create an advantage",
                    "attack": "attack decisively",
                    "defend": "defend effectively",
                }.get(action, "overcome obstacles")
                stunt_items = [
                    StuntSuggestion(name="Stunt", description=f"Gain +2 to {skill_name} when you {action_phrase}.")
                    for _ in range(n)
                ]
            if len(stunt_items) < requested_n:
                pad = requested_n - len(stunt_items)
                skill_name = target_skill_name or (input_state.skills[0].name if input_state.skills else "Fight")
                stunt_items.extend(
                    [
                        StuntSuggestion(
                            name="Stunt",
                            description=f"Gain +2 to {skill_name} when you overcome obstacles.",
                        )
                        for _ in range(pad)
                    ]
                )
            import uuid as _uuid

            for _, stunt_sug in enumerate(stunt_items):
                if not getattr(stunt_sug, "id", None):
                    stunt_sug.id = f"stunt-{str(_uuid.uuid4())[:8]}"
            suggestions = suggestions.model_copy(update={"stunts": stunt_items, "skills": None, "aspects": None})
        elif mode == "skills":
            locked_ids: set[str] = set()
            for s in input_state.skills:
                is_locked = bool(getattr(s, "locked", False))
                is_user_edited = bool(getattr(s, "userEdited", False))
                if is_locked or (not request.allowOverwriteUserEdits and is_user_edited):
                    locked_ids.add(s.id)

            skill_items = list(suggestions.skills or [])
            if not skill_items and input_state.skills:
                skill_items = [SkillSuggestion(id=s.id, name=s.name, rank=s.rank) for s in input_state.skills]
            filtered: list[SkillSuggestion] = []
            for skill_sug in skill_items:
                target_id = getattr(skill_sug, "id", None)
                if target_id and target_id in locked_ids:
                    continue
                filtered.append(skill_sug)
            ladder_type = getattr(input_state.meta, "ladderType", "1-4") or "1-4"
            merged: list[SkillSuggestion] = []
            seen_names: set[str] = set()
            for s in input_state.skills:
                if s.id in locked_ids:
                    key = (s.name or "").strip().lower()
                    if key and key not in seen_names:
                        seen_names.add(key)
                        merged.append(SkillSuggestion(id=s.id, name=s.name, rank=s.rank))
            bank = request.options.skillBank if (request.options and request.options.skillBank) else DEFAULT_FATE_CORE_SKILLS
            for skill_sug2 in filtered:
                key = (getattr(skill_sug2, "name", "") or "").strip().lower()
                if key and key in seen_names:
                    continue
                canonical = _canonicalize_skill_name(getattr(skill_sug2, "name", ""), bank)
                if canonical:
                    skill_sug2 = SkillSuggestion(
                        id=getattr(skill_sug2, "id", None), name=canonical, rank=getattr(skill_sug2, "rank", None)
                    )
                    key = canonical.strip().lower()
                seen_names.add(key)
                merged.append(SkillSuggestion(id=getattr(skill_sug2, "id", None), name=getattr(skill_sug2, "name", None), rank=getattr(skill_sug2, "rank", None)))

            merged_dicts = [
                {"id": getattr(s, "id", None), "name": getattr(s, "name", None), "rank": getattr(s, "rank", 1)}
                for s in merged
            ]
            balanced = _pad_pyramid_to_minimum(merged_dicts, locked_ids, ladder_type, bank, total_max=10)
            balanced_sugs_raw = [
                SkillSuggestion(id=item.get("id"), name=item.get("name"), rank=int(item.get("rank", 1)))
                for item in balanced
            ]
            balanced_sugs = _ensure_skill_ids(balanced_sugs_raw, input_state.skills)
            suggestions = suggestions.model_copy(update={"skills": balanced_sugs, "aspects": None, "stunts": None})
        elif mode in ("high_concept", "trouble"):
            target_name = "High Concept" if mode == "high_concept" else "Trouble"
            current_map = {a.name: a for a in input_state.aspects}
            target = current_map.get(target_name)
            proposed_desc = None
            if suggestions.aspects:
                for a in suggestions.aspects:
                    text = (getattr(a, "description", None) or "").strip()
                    if text:
                        proposed_desc = text
                        break
            if not proposed_desc:
                idea = (input_state.meta.idea or "").strip() or "Character"
                if mode == "high_concept":
                    proposed_desc = f"{idea} with a defining role or theme."
                else:
                    proposed_desc = f"A recurring problem for {idea}."
            targeted = []
            if target is not None:
                targeted.append(AspectSuggestion(id=target.id, name=target_name, description=proposed_desc))
            else:
                targeted.append(AspectSuggestion(name=target_name, description=proposed_desc))
            suggestions = suggestions.model_copy(update={"aspects": targeted, "skills": None, "stunts": None})

        model = merge_suggestions_into_sheet(state=input_state, suggestions=suggestions)
        return model
    except ValidationError as ve:
        last_validation_err = ve
        feedback = f"Validation failed: {ve.errors()[:3]}"
    except Exception as ex:
        feedback = f"Generation failed: {type(ex).__name__}"

    validation_errors = []
    if last_validation_err is not None:
        for err in last_validation_err.errors():
            loc = ".".join(str(x) for x in (err.get("loc") or ()))
            msg = err.get("msg") or "Invalid value"
            validation_errors.append({"path": loc, "message": msg})

    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_FAILED",
            "message": "Model could not produce a valid CharacterSheet after retries",
            "validationErrors": validation_errors or None,
            "conflicts": None,
        },
    )


