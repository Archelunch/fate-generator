import hashlib
from typing import Any, Literal, cast

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.core.constants import DEFAULT_FATE_CORE_SKILLS
from app.core.skeleton import build_sample_character_skeleton
from app.dspy_modules import (
    CharacterSkeletonModule,
    GmHintsModule,
    RemainingSuggestionsModule,
)
from app.models import (
    AspectSuggestion,
    CharacterSheet,
    CharacterSkeleton,
    CharacterStateInput,
    GenerateRemainingRequest,
    GenerateRemainingResult,
    GenerateSkeletonRequest,
    GenerationErrorResponse,
    GMHintsRequest,
    GMHintsResponse,
    RankedSkill,
    SkillSuggestion,
    StuntSuggestion,
    UISkill,
)
from app.utils import merge_suggestions_into_sheet

router = APIRouter(prefix="/api")


_skeleton_mod = CharacterSkeletonModule()
_skeleton_mod.load("/Users/pavluhin/Documents/Projects/Hobby/fate-generator/artifacts/gepa_character_skeleton.json")
_remaining_mod = RemainingSuggestionsModule()
_remaining_mod.load("/Users/pavluhin/Documents/Projects/Hobby/fate-generator/artifacts/gepa_remaining.json")
_gm_hints_mod = GmHintsModule()
_gm_hints_mod.load("/Users/pavluhin/Documents/Projects/Hobby/fate-generator/artifacts/gepa_gm_hints.json")


def _to_remaining_result(prediction: Any) -> GenerateRemainingResult:
    data: dict[str, Any] = {
        "aspects": [getattr(prediction, "aspects", None)] if getattr(prediction, "aspects", None) is not None else None,
        "stunts": [getattr(prediction, "stunts", None)] if getattr(prediction, "stunts", None) is not None else None,
        "notes": getattr(prediction, "notes", None),
    }
    # If the model provides skills despite the signature, accept them.
    if getattr(prediction, "skills", None) is not None:
        data["skills"] = [getattr(prediction, "skills", None)]
    return GenerateRemainingResult.model_validate(data)


def _normalize_gm_hints(
    state: CharacterStateInput,
    *,
    target_type: str,
    target_id: str,
    raw_prediction: Any,
) -> GMHintsResponse:
    from app.models import GMHint  # local import to avoid cycles

    # Determine if target is the Trouble aspect
    is_trouble = False
    if target_type == "aspect":
        for a in state.aspects:
            if a.id == target_id or (a.name or "").strip().lower() == "trouble":
                is_trouble = True
                break

    raw_hints: list[Any] = list(getattr(raw_prediction, "hints", []) or [])

    def to_hint(obj: Any) -> GMHint | None:
        def _field(name: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(name)
            return getattr(obj, name, None)

        t = (_field("type") or "").strip().lower()
        title = (_field("title") or "").strip() or "Hint"
        narrative = (_field("narrative") or "").strip()
        mechanics = (_field("mechanics") or "").strip()
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
        return GMHint(
            type=cast(
                Literal[
                    "invoke",
                    "compel",
                    "create_advantage",
                    "player_invoke",
                    "trigger",
                    "edge_case",
                    "synergy",
                ],
                t,
            ),
            title=title,
            narrative=narrative,
            mechanics=mechanics,
        )

    normalized = [h for h in (to_hint(h) for h in raw_hints) if h is not None]

    # Deduplicate by (type + narrative)
    uniq: list[GMHint] = []
    seen: set[str] = set()
    for h in normalized:
        key = f"{h.type}|{h.narrative.strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)

    # Enforce counts by target category
    final: list[GMHint] = []
    if target_type == "stunt":
        wants = ["trigger", "edge_case", "synergy"]
        for w in wants:
            cand = next((h for h in uniq if h.type == w), None)
            if cand is None:
                final.append(
                    GMHint(
                        type=cast(
                            Literal[
                                "invoke",
                                "compel",
                                "create_advantage",
                                "player_invoke",
                                "trigger",
                                "edge_case",
                                "synergy",
                            ],
                            w,
                        ),
                        title=w.replace("_", " ").title(),
                        narrative="Usage example.",
                        mechanics="Add a concrete Fate mechanic line.",
                    )
                )
            else:
                final.append(cand)
    else:
        if is_trouble:
            gm_types = ["compel", "create_advantage"]
            for w in gm_types:
                cand = next((h for h in uniq if h.type == w), None)
                if cand is None:
                    final.append(
                        GMHint(
                            type=cast(
                                Literal[
                                    "invoke",
                                    "compel",
                                    "create_advantage",
                                    "player_invoke",
                                    "trigger",
                                    "edge_case",
                                    "synergy",
                                ],
                                w,
                            ),
                            title=w.replace("_", " ").title(),
                            narrative="GM uses the Trouble against the PC.",
                            mechanics="Compel: GM offers a fate point for a complication.",
                        )
                    )
                else:
                    final.append(cand)
            player_cand = next((h for h in uniq if h.type in ("player_invoke", "invoke")), None)
            if player_cand is None:
                final.append(
                    GMHint(
                        type=cast(
                            Literal[
                                "invoke",
                                "compel",
                                "create_advantage",
                                "player_invoke",
                                "trigger",
                                "edge_case",
                                "synergy",
                            ],
                            "player_invoke",
                        ),
                        title="Player Invoke",
                        narrative="Player leverages their Trouble positively in a clutch moment.",
                        mechanics="Spend a fate point to gain +2 or reroll.",
                    )
                )
            else:
                final.append(
                    GMHint(
                        type=cast(
                            Literal[
                                "invoke",
                                "compel",
                                "create_advantage",
                                "player_invoke",
                                "trigger",
                                "edge_case",
                                "synergy",
                            ],
                            "player_invoke",
                        ),
                        title=player_cand.title,
                        narrative=player_cand.narrative,
                        mechanics=player_cand.mechanics,
                    )
                )
        else:
            pool = [h for h in uniq if h.type in {"invoke", "compel", "create_advantage"}]
            if len(pool) >= 2:
                final = pool[:2]
            elif len(pool) == 1:
                final = pool + [
                    GMHint(
                        type="create_advantage",
                        title="Create Advantage",
                        narrative="Set up a favorable situation that this aspect naturally supports.",
                        mechanics="Create an advantage to place a free invoke.",
                    )
                ]
            else:
                final = [
                    GMHint(
                        type="invoke",
                        title="Invoke",
                        narrative="Leverage the aspect to gain advantage.",
                        mechanics="Spend a fate point for +2 or reroll.",
                    ),
                    GMHint(
                        type="create_advantage",
                        title="Create Advantage",
                        narrative="Establish a situational benefit tied to the aspect.",
                        mechanics="Create an advantage and gain a free invoke if you succeed with style.",
                    ),
                ]

    return GMHintsResponse(hints=final, notes=getattr(raw_prediction, "notes", None) or None)


def _get_ranks_for_ladder(ladder_type: str) -> list[int]:
    return [5, 4, 3, 2, 1] if (ladder_type or "").strip() == "1-5" else [4, 3, 2, 1]


def _rebalance_skills_pyramid(
    skills: list[SkillSuggestion] | list[RankedSkill] | list[Any],  # tolerate mixed during processing
    locked_ids: set[str],
    ladder_type: str,
) -> list[dict[str, Any]]:
    # Convert generically to simple dicts for manipulation
    items: list[dict[str, Any]] = [
        {"id": getattr(s, "id", None), "name": getattr(s, "name", None), "rank": int(getattr(s, "rank", 0))}
        for s in skills
        if getattr(s, "name", None) is not None
    ]
    ranks = _get_ranks_for_ladder(ladder_type)
    next_lower = {ranks[i]: (ranks[i + 1] if i + 1 < len(ranks) else ranks[-1]) for i in range(len(ranks))}
    count = {r: 0 for r in ranks}

    locked = [s for s in items if s.get("id") in locked_ids]
    others = [s for s in items if s.get("id") not in locked_ids]

    placed: list[dict[str, Any]] = []

    # Place locked as-is (assume valid; if not, we'll try to balance with others)
    for s in locked:
        r = int(s.get("rank") or 1)
        if r not in ranks:
            r = ranks[0] if r > ranks[0] else ranks[-1]
        s["rank"] = r
        placed.append(s)
        count[r] += 1

    # Place others, demoting until constraint satisfied
    for s in sorted(others, key=lambda x: int(x.get("rank") or 0), reverse=True):
        r = int(s.get("rank") or 1)
        # clamp to allowed
        if r not in ranks:
            r = ranks[0] if r > ranks[0] else ranks[-1]
        # move down until valid
        while True:
            idx_ok = ranks.index(r)
            if idx_ok == len(ranks) - 1:  # lowest always OK
                break
            lower = next_lower[r]
            if (count[r] + 1) <= count[lower]:
                break
            r = lower
        s["rank"] = r
        placed.append(s)
        count[r] += 1

    # Final pass: if still violating due to locked dominance, push any possible unlocked down
    for i in range(len(ranks) - 1):
        high = ranks[i]
        low = ranks[i + 1]
        while count[high] > count[low]:
            # try to demote an unlocked from high
            cand = next((p for p in placed if p["rank"] == high and p.get("id") not in locked_ids), None)
            if cand is None:
                # try to promote from below to low to satisfy
                lower_cand = next(
                    (p for p in placed if p["rank"] not in (high, low) and p.get("id") not in locked_ids), None
                )
                if lower_cand is None:
                    break  # cannot fix without touching locks
                old_r = lower_cand["rank"]
                count[old_r] -= 1
                lower_cand["rank"] = low
                count[low] += 1
                continue
            cand["rank"] = low
            count[high] -= 1
            count[low] += 1

    return placed


def _slugify(name: str) -> str:
    return (name or "").lower().strip().replace(" ", "-").replace("/", "-").replace("_", "-")


def _ensure_skill_ids(
    items: list[SkillSuggestion],
    existing: list[UISkill],
) -> list[SkillSuggestion]:
    name_to_existing: dict[str, str] = {
        (getattr(s, "name", "") or "").strip().lower(): s.id for s in existing if getattr(s, "id", None)
    }
    used_ids: set[str] = set([getattr(s, "id", "") for s in items if getattr(s, "id", None)])
    result: list[SkillSuggestion] = []
    for s in items:
        sid = getattr(s, "id", None)
        nm = (getattr(s, "name", "") or "").strip()
        if not sid:
            existing_id = name_to_existing.get(nm.lower())
            if existing_id and existing_id not in used_ids:
                sid = existing_id
            else:
                base = f"skill-{_slugify(nm)}"
                candidate = base if base not in used_ids else f"{base}-2"
                n = 2
                while candidate in used_ids:
                    n += 1
                    candidate = f"{base}-{n}"
                sid = candidate
        used_ids.add(sid)
        result.append(SkillSuggestion(id=sid, name=getattr(s, "name", None), rank=getattr(s, "rank", None)))
    return result


def _canonicalize_skill_name(name: str, bank: list[str]) -> str | None:
    bank_map = {b.strip().lower(): b for b in bank}
    key = (name or "").strip().lower()
    if key in bank_map:
        return bank_map[key]
    synonyms = {
        "willpower": "Will",
        "cunning": "Deceive",
        "knowledge": "Lore",
        "awareness": "Notice",
        "charisma": "Rapport",
        "strength": "Physique",
        "agility": "Athletics",
        "marksmanship": "Shoot",
    }
    if key in synonyms and synonyms[key].strip().lower() in bank_map:
        return bank_map[synonyms[key].strip().lower()]
    return None


def _get_minimum_quota(ladder_type: str) -> dict[int, int]:
    # Base quotas that create a proper pyramid shape
    if (ladder_type or "").strip() == "1-5":
        return {5: 0, 4: 1, 3: 2, 2: 3}
    return {4: 1, 3: 2, 2: 3}


def _pad_pyramid_to_minimum(
    items: list[dict[str, Any]],
    locked_ids: set[str],
    ladder_type: str,
    skill_bank: list[str],
    total_max: int = 10,
) -> list[dict[str, Any]]:
    ranks = _get_ranks_for_ladder(ladder_type)
    base_quota = _get_minimum_quota(ladder_type)
    # Adjust quota to not exceed total_max; remaining goes to lowest rank
    required_sum = sum(base_quota.values())
    lowest = ranks[-1]
    quota: dict[int, int] = dict(base_quota)
    quota[lowest] = max(0, total_max - required_sum)

    used_names: set[str] = {str(it.get("name") or "").strip().lower() for it in items}
    counts: dict[int, int] = {r: 0 for r in ranks}
    for it in items:
        r = int(it.get("rank", lowest))
        if r in counts:
            counts[r] += 1

    def _next_bank_name() -> str | None:
        for nm in skill_bank:
            key = str(nm or "").strip().lower()
            if key and key not in used_names:
                used_names.add(key)
                return nm
        return None

    padded = list(items)
    for r in ranks:
        need = max(0, quota.get(r, 0) - (counts.get(r, 0)))
        for _ in range(need):
            nm = _next_bank_name()
            if not nm:
                break
            padded.append({"id": None, "name": nm, "rank": r})
            counts[r] = counts.get(r, 0) + 1

    # Rebalance once more to ensure chain validity
    rebalanced = _rebalance_skills_pyramid(padded, locked_ids, ladder_type)
    return rebalanced


@router.post("/generate_skeleton", response_model=CharacterSkeleton | CharacterSheet)
@router.post("/generate_sample_skeleton", response_model=CharacterSheet)
def generate_skeleton(request: GenerateSkeletonRequest | None = None) -> CharacterSheet | CharacterSkeleton:
    if request is not None:
        skills = request.skillList or DEFAULT_FATE_CORE_SKILLS
        prediction = _skeleton_mod(
            idea=request.idea,
            setting=request.setting or "",
            skill_list=skills,
        )
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

    return build_sample_character_skeleton()


@router.post("/generate_remaining", response_model=CharacterSheet, responses={422: {"model": GenerationErrorResponse}})
def generate_remaining(request: GenerateRemainingRequest) -> CharacterSheet | Response:
    """Generate remaining details respecting constraints with retry + validation.

    For now, we stub generation by returning a merged result from the model
    and the input, preserving IDs. This will be expanded in tasks 7.3/7.4.
    """
    from pydantic import ValidationError  # local import to avoid cycles

    # Retry up to 3 total attempts, tightening instructions with feedback.
    feedback: str | None = None
    last_validation_err: ValidationError | None = None

    input_state = CharacterStateInput.model_validate(request.character)

    # Compute aspects slots left (max 3 additional beyond High/Trouble)
    additional_aspects = [a for a in input_state.aspects if a.name not in ("High Concept", "Trouble")]
    aspect_slots_left = max(0, 3 - len(additional_aspects))

    # Resolve target skill id -> name if provided
    target_skill_name: str | None = None
    if request.options and request.options.targetSkillId:
        skill_map = {s.id: s.name for s in input_state.skills}
        target_skill_name = skill_map.get(request.options.targetSkillId)

    # Effective mode and counts
    mode = request.options.mode if request.options and request.options.mode else "stunts"
    num_stunts = None
    if request.options and request.options.count is not None:
        num_stunts = max(1, int(request.options.count))
    # Clamp aspects to available slots when generating aspects
    if mode == "aspects" and num_stunts is None:
        # num_stunts not used for aspects; rely on aspect_slots_left
        pass
    # When regenerating skills, pass only locked/protected skills to the generator
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
        # Debug: show which skills are preserved as anchors for regeneration
        try:
            print(
                "[generate_remaining][skills] preserved locked/protected:",
                [f"{s.name}(+{s.rank})" for s in protected_skills],
            )
        except Exception:
            pass
        gen_state = CharacterStateInput(
            meta=input_state.meta,
            aspects=input_state.aspects,
            skills=protected_skills,
            stunts=input_state.stunts,
        )

    for _ in range(3):
        try:
            _pred = _remaining_mod(
                state=gen_state,
                allow_overwrite=request.allowOverwriteUserEdits,
                default_skills=(
                    request.options.skillBank
                    if (request.options and request.options.skillBank)
                    else DEFAULT_FATE_CORE_SKILLS
                ),
                feedback=feedback,
                mode=mode,
                target_skill_name=target_skill_name,
                action_type=(request.options.actionType if request.options else None),
                aspect_slots_left=aspect_slots_left,
                user_note=(request.options.note if request.options else None),
            )
            suggestions = _to_remaining_result(_pred)
            # Filter suggestions based on mode and counts/slots
            if mode == "aspects":
                aspect_items = list(suggestions.aspects or [])
                # Determine requested count (default 1)
                requested = 1
                if request.options and request.options.count is not None:
                    try:
                        requested = max(1, int(request.options.count))
                    except Exception:
                        requested = 1
                # Respect available slots if present
                if aspect_slots_left:
                    requested = min(requested, aspect_slots_left)
                if len(aspect_items) > requested:
                    aspect_items = aspect_items[:requested]
                # Fallback generation if model returned nothing
                if not aspect_items and aspect_slots_left > 0:
                    idea = (input_state.meta.idea or "").strip() or "Character"
                    base_desc = f"An aspect reflecting: {idea}"
                    aspect_items = [AspectSuggestion(name="Aspect", description=base_desc) for _ in range(requested)]
                suggestions = suggestions.model_copy(
                    update={
                        "aspects": aspect_items,
                        "skills": None,
                        "stunts": None,
                    }
                )
            elif mode in ("stunts", "single_stunt"):
                stunt_items = list(suggestions.stunts or [])
                requested_n = max(1, int(num_stunts or 1))

                # Drop empties first (missing description AND name)
                def _has_content(sug: StuntSuggestion) -> bool:
                    desc = (getattr(sug, "description", None) or "").strip()
                    name = (getattr(sug, "name", None) or "").strip()
                    return bool(desc or name)

                stunt_items = [s for s in stunt_items if _has_content(s)]

                # De-duplicate by normalized description vs existing and within batch
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
                # Fallback generation if model returned nothing
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
                        StuntSuggestion(
                            name="Stunt",
                            description=f"Gain +2 to {skill_name} when you {action_phrase}.",
                        )
                        for _ in range(n)
                    ]
                # If fewer than requested, pad with generic suggestions
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
                # If suggestions lack IDs, assign fresh ones to avoid duplication/collapsing
                import uuid as _uuid

                for _, stunt_sug in enumerate(stunt_items):
                    if not getattr(stunt_sug, "id", None):
                        stunt_sug.id = f"stunt-{str(_uuid.uuid4())[:8]}"
                suggestions = suggestions.model_copy(
                    update={
                        "stunts": stunt_items,
                        "skills": None,
                        "aspects": None,
                    }
                )
            elif mode == "skills":
                # Enforce locks: do not modify locked or protected userEdited skills
                locked_ids: set[str] = set()
                for s in input_state.skills:
                    is_locked = bool(getattr(s, "locked", False))
                    is_user_edited = bool(getattr(s, "userEdited", False))
                    if is_locked or (not request.allowOverwriteUserEdits and is_user_edited):
                        locked_ids.add(s.id)

                skill_items = list(suggestions.skills or [])
                # Optional: ensure at least current skills present
                if not skill_items and input_state.skills:
                    skill_items = [SkillSuggestion(id=s.id, name=s.name, rank=s.rank) for s in input_state.skills]
                # Drop updates that target locked skills
                filtered: list[SkillSuggestion] = []
                for skill_sug in skill_items:
                    target_id = getattr(skill_sug, "id", None)
                    if target_id and target_id in locked_ids:
                        continue
                    filtered.append(skill_sug)
                # Merge new suggestions with anchors (locked/protected) and dedupe by name
                ladder_type = getattr(input_state.meta, "ladderType", "1-4") or "1-4"
                merged: list[SkillSuggestion] = []
                seen_names: set[str] = set()
                # 1) include locked/protected first
                for s in input_state.skills:
                    if s.id in locked_ids:
                        key = (s.name or "").strip().lower()
                        if key and key not in seen_names:
                            seen_names.add(key)
                            merged.append(SkillSuggestion(id=s.id, name=s.name, rank=s.rank))
                # 2) then include model suggestions that don't duplicate locked names and map to bank
                bank = (
                    request.options.skillBank
                    if (request.options and request.options.skillBank)
                    else DEFAULT_FATE_CORE_SKILLS
                )
                for skill_sug2 in filtered:
                    key = (getattr(skill_sug2, "name", "") or "").strip().lower()
                    if key and key in seen_names:
                        continue
                    # Canonicalize to bank to avoid out-of-vocabulary names like "Willpower"
                    canonical = _canonicalize_skill_name(getattr(skill_sug2, "name", ""), bank)
                    if canonical:
                        skill_sug2 = SkillSuggestion(
                            id=getattr(skill_sug2, "id", None), name=canonical, rank=getattr(skill_sug2, "rank", None)
                        )
                        key = canonical.strip().lower()
                    seen_names.add(key)
                    merged.append(
                        SkillSuggestion(
                            id=getattr(skill_sug2, "id", None),
                            name=getattr(skill_sug2, "name", None),
                            rank=getattr(skill_sug2, "rank", None),
                        )
                    )

                # If model proposes too few items, pad from bank to reach minimal pyramid shape and up to 10 total
                # Start by converting to dicts for padding
                merged_dicts = [
                    {"id": getattr(s, "id", None), "name": getattr(s, "name", None), "rank": getattr(s, "rank", 1)}
                    for s in merged
                ]
                balanced = _pad_pyramid_to_minimum(merged_dicts, locked_ids, ladder_type, bank, total_max=10)
                # Map back to suggestions format
                balanced_sugs_raw = [
                    SkillSuggestion(id=item.get("id"), name=item.get("name"), rank=int(item.get("rank", 1)))
                    for item in balanced
                ]
                # Ensure stable deterministic IDs for any suggestions missing IDs
                balanced_sugs = _ensure_skill_ids(balanced_sugs_raw, input_state.skills)
                suggestions = suggestions.model_copy(
                    update={
                        "skills": balanced_sugs,
                        "aspects": None,
                        "stunts": None,
                    }
                )
            elif mode in ("high_concept", "trouble"):
                # Reduce to a single targeted aspect update preserving ID
                target_name = "High Concept" if mode == "high_concept" else "Trouble"
                current_map = {a.name: a for a in input_state.aspects}
                target = current_map.get(target_name)
                # Prefer model's proposed text if provided; otherwise fallback
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
                suggestions = suggestions.model_copy(
                    update={
                        "aspects": targeted,
                        "skills": None,
                        "stunts": None,
                    }
                )
            # Merge suggestions and validate by constructing a CharacterSheet
            model = merge_suggestions_into_sheet(state=input_state, suggestions=suggestions)
            return model
        except ValidationError as ve:
            last_validation_err = ve
            # Add concise feedback for the next attempt
            feedback = f"Validation failed: {ve.errors()[:3]}"
        except Exception as ex:  # pragma: no cover - defensive catch for LM issues
            # Provide generic feedback to nudge the model
            feedback = f"Generation failed: {type(ex).__name__}"

    # If all attempts failed, return structured 422
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


@router.post("/hints", response_model=GMHintsResponse)
def gm_hints(request: GMHintsRequest) -> GMHintsResponse:
    """Return GM/player usage hints for a specific aspect or stunt.

    Rules enforced:
    - Aspect (not Trouble): 2 hints
    - Trouble: 3 hints (2 GM-facing, 1 player-facing)
    - Stunt: 3 hints (trigger, edge_case, synergy)
    """
    state = CharacterStateInput.model_validate(request.character)
    target_type = request.target.type
    target_id = request.target.id
    # num is not used; tone is passed to the module for potential future use
    _ = request.options.num if request.options else None
    tone = request.options.tone if request.options else None
    # 30s timeout is handled client-side; here we just invoke DSPy and normalize
    raw_pred = _gm_hints_mod(state=state, target_type=target_type, target_id=target_id, tone=tone)
    hints = _normalize_gm_hints(state, target_type=target_type, target_id=target_id, raw_prediction=raw_pred)
    return hints
