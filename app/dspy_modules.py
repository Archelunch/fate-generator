from __future__ import annotations

from typing import Any, Literal

import dspy

from app.models import CharacterStateInput
from app.signatures import (
    GenerateCharacterSkeleton,
    GenerateGmHints,
    GenerateRemainingSuggestions,
)


class CharacterSkeletonModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self._predict = dspy.Predict(GenerateCharacterSkeleton)

    def forward(self, *, idea: str, setting: str | None, skill_list: list[str]) -> dspy.Prediction:
        result = self._predict(idea=idea, setting=setting, skill_list=list(skill_list or []))
        return dspy.Prediction(
            high_concept=result.high_concept,
            trouble=result.trouble,
            ranked_skills=result.ranked_skills,
        )


class RemainingSuggestionsModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self._predict = dspy.Predict(GenerateRemainingSuggestions)

    def _build_constraints_snapshot(self, character_data: dict[str, Any], allow_overwrite: bool) -> list[str]:
        """Extract immutable constraints from raw character data.

        - Always include items with locked == True
        - If allow_overwrite is False, also include items with userEdited == True
        The input is the raw frontend JSON, which may include extra flags that
        aren't part of the backend Pydantic schema.
        """
        constraints: list[str] = []

        def consider_item(prefix: str, item: dict[str, Any]) -> None:
            locked = bool(item.get("locked", False))
            user_edited = bool(item.get("userEdited", False))
            name = (item.get("name") or "").strip()
            description = (item.get("description") or "").strip()
            if locked or (not allow_overwrite and user_edited):
                if description:
                    constraints.append(f"{prefix} '{name}' must keep description: {description}")
                else:
                    constraints.append(f"{prefix} '{name}' must remain unchanged")

        for aspect in character_data.get("aspects") or []:
            if isinstance(aspect, dict):
                consider_item("Aspect", aspect)

        for stunt in character_data.get("stunts") or []:
            if isinstance(stunt, dict):
                consider_item("Stunt", stunt)

        # Skills in the current UI may not carry locked/userEdited flags.
        for skill in character_data.get("skills") or []:
            if isinstance(skill, dict):
                locked = bool(skill.get("locked", False))
                user_edited = bool(skill.get("userEdited", False))
                name = (skill.get("name") or "").strip()
                rank = skill.get("rank")
                if locked or (not allow_overwrite and user_edited):
                    constraints.append(f"Skill '{name}' must remain at rank {rank}")

        return constraints

    def forward(
        self,
        *,
        state: CharacterStateInput,
        allow_overwrite: bool,
        default_skills: list[str] | None = None,
        feedback: str | None = None,
        mode: str = "stunts",
        target_skill_name: str | None = None,
        action_type: str | None = None,
        aspect_slots_left: int | None = None,  # accepted for API symmetry; not used directly by signature
        user_note: str | None = None,
        avoid_stunts: list[str] | None = None,
    ) -> dspy.Prediction:
        state_dict: dict[str, Any] = state.model_dump()
        constraints = self._build_constraints_snapshot(state_dict, allow_overwrite)

        # Only provide default skill list if current state has no skills.
        effective_default_skills: list[str] = []
        if not (state.skills or []):
            effective_default_skills = list(default_skills or [])

        effective_mode = mode
        effective_target_skill = target_skill_name.strip() if target_skill_name else None
        effective_action_type = action_type.strip() if action_type else None

        # Avoid generating duplicates of existing stunt descriptions
        existing_stunts = [
            getattr(s, "description", "") for s in (state.stunts or []) if getattr(s, "description", None)
        ]
        effective_avoid_stunts = list(avoid_stunts or existing_stunts)

        result = self._predict(
            state=state,
            constraints=constraints,
            allow_overwrite=allow_overwrite,
            default_skills=effective_default_skills,
            feedback=(feedback or None),
            mode=effective_mode,
            target_skill_name=effective_target_skill,
            action_type=effective_action_type,
            user_note=user_note,
            avoid_stunts=effective_avoid_stunts,
        )

        return dspy.Prediction(
            aspects=getattr(result, "aspects", None),
            stunts=getattr(result, "stunts", None),
            notes=getattr(result, "notes", None),
        )


class GmHintsModule(dspy.Module):

    GMHintType = Literal[
        "invoke",
        "compel",
        "create_advantage",
        "player_invoke",
        "trigger",
        "edge_case",
        "synergy",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._predict = dspy.Predict(GenerateGmHints)

    # --- helpers ---
    @staticmethod
    def _is_trouble_aspect(state: CharacterStateInput, target_id: str) -> bool:
        for a in state.aspects:
            if a.id == target_id or (a.name or "").strip().lower() == "trouble":
                return True
        return False

    @staticmethod
    def _normalize_hint_obj(obj: dict[str, Any], target_type: str) -> dict[str, str] | None:
        t = (obj.get("type") or "").strip().lower()
        title = (obj.get("title") or "").strip() or "Hint"
        narrative = (obj.get("narrative") or "").strip()
        mechanics = (obj.get("mechanics") or "").strip()
        if not narrative or not mechanics:
            return None
        valid_types = {
            "invoke",
            "compel",
            "create_advantage",
            "player_invoke",
            "trigger",
            "edge_case",
            "synergy",
        }
        if t not in valid_types:
            aliases = {"ca": "create_advantage", "player": "player_invoke", "gm": "compel"}
            t = aliases.get(t, t)
            if t not in valid_types:
                t = "invoke" if target_type == "aspect" else "trigger"
        return {"type": t, "title": title, "narrative": narrative, "mechanics": mechanics}

    def forward(
        self,
        *,
        state: CharacterStateInput,
        target_type: str,
        target_id: str,
        tone: str | None = None,
    ) -> dspy.Prediction:
        setting_hint = getattr(state.meta, "setting", "") if getattr(state, "meta", None) else None
        result = self._predict(
            state=state,
            target_type=target_type,
            target_id=target_id,
            setting_hint=setting_hint,
        )
        return result
